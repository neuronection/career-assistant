"""Durable background job queue: claim-based in-process worker pool.

A `background_jobs` table is the queue.
Workers claim with a conditional UPDATE whose rowcount decides the winner —
portable across PostgreSQL and SQLite with no extra infrastructure. Handlers
reuse the existing services; only the entry point moves off the request path.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.errors import DomainError
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus, BackgroundJobType
from app.services.progress import ProgressCb, bound_progress_detail

logger = logging.getLogger(__name__)

TERMINAL = (
    BackgroundJobStatus.SUCCEEDED.value,
    BackgroundJobStatus.FAILED.value,
    BackgroundJobStatus.CANCELLED.value,
)

CancelledCb = Callable[[], Awaitable[bool]]
Handler = Callable[..., Awaitable[dict]]

#: The posting-ingest stage jobs (plan 203). One lane, serial by default: the
#: lane moves ingest work off the generic pool so a long sync or a backlog
#: drain cannot starve digests, CV generation, fit sweeps or the vector store.
INGEST_JOB_TYPES = frozenset(
    {
        BackgroundJobType.POSTING_SYNC.value,
        BackgroundJobType.DETAIL_ENRICHMENT.value,
        BackgroundJobType.POSTING_EXTRACT.value,
        BackgroundJobType.COMPANY_TRIAGE.value,
        BackgroundJobType.POSTING_REMAP.value,
    }
)

#: The vector-store writes and bulk retrieval runs (plan 50/51/201).
VECTOR_JOB_TYPES = frozenset(
    {
        BackgroundJobType.VECTOR_INDEX.value,
        BackgroundJobType.VECTOR_RECONCILE.value,
        BackgroundJobType.VECTOR_MAINTENANCE.value,
        BackgroundJobType.VECTOR_CUTOVER.value,
    }
)


@dataclass(frozen=True)
class WorkerSpec:
    """One worker's claim scope: only ``job_types``, never ``exclude_types``."""

    job_types: frozenset[str] | None = None
    exclude_types: frozenset[str] | None = None


def worker_specs(*, generic: int, ingest: int = 0, vector: int = 0) -> list[WorkerSpec]:
    """The worker layout for the configured counts (plan 203).

    A family with its own lane is excluded from the generic pool; without a
    lane the pool claims anything, so ``generic=1`` alone is exactly the
    pre-plan-203 behaviour.
    """
    excluded: frozenset[str] = frozenset()
    if ingest > 0:
        excluded |= INGEST_JOB_TYPES
    if vector > 0:
        excluded |= VECTOR_JOB_TYPES
    specs = [WorkerSpec(exclude_types=excluded or None) for _ in range(max(int(generic), 0))]
    specs += [WorkerSpec(job_types=INGEST_JOB_TYPES) for _ in range(max(int(ingest), 0))]
    specs += [WorkerSpec(job_types=VECTOR_JOB_TYPES) for _ in range(max(int(vector), 0))]
    return specs


async def enqueue(
    db: AsyncSession,
    job_type: str,
    payload: dict,
    user_id: uuid.UUID | None = None,
    max_attempts: int = 2,
    *,
    commit: bool = True,
) -> BackgroundJob:
    """Queue a job for the worker pool.

    ``commit=False`` is the request-path form: the row is ``add``ed and
    ``flush``ed only, so it becomes durable with the caller's own commit and
    disappears if the caller rolls back. The committing form stays the norm
    everywhere else.
    """
    job = BackgroundJob(
        user_id=user_id,
        job_type=job_type,
        payload=payload,
        max_attempts=max_attempts,
    )
    db.add(job)
    if commit:
        await db.commit()
        await db.refresh(job)
    else:
        await db.flush()
    return job


class JobWorker:
    """Single-worker loop; instantiate one per configured concurrency.

    ``job_types`` / ``exclude_types`` are the lane filters (plan 203): a worker
    with ``job_types`` claims only that family, and the generic pool excludes a
    family once it has its own lane — otherwise the generic worker could still
    grab the long job and the race would decide.
    """

    def __init__(
        self,
        db: AsyncSession,
        poll_interval: float = 1.0,
        *,
        job_types: frozenset[str] | None = None,
        exclude_types: frozenset[str] | None = None,
    ):
        self.db = db
        self.poll_interval = poll_interval
        self.job_types = job_types or None
        self.exclude_types = exclude_types or None

    async def run_forever(self) -> None:
        """Claim and execute jobs until cancelled (app shutdown)."""
        logger.info("Background job worker started")
        try:
            while True:
                worked = await self.run_once()
                if not worked:
                    await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            logger.info("Background job worker stopped")
            raise

    async def run_once(self) -> bool:
        """Claim and run at most one job; True when a job was executed."""
        job = await self.claim_next()
        if job is None:
            return False
        await self.execute(job)
        return True

    async def claim_next(self) -> BackgroundJob | None:
        """Claim the oldest queued job of this worker's lane, or None.

        The conditional UPDATE (status still 'queued') arbitrates between
        competing claimants without dialect-specific locking.
        """
        now = _utcnow()
        conditions = [BackgroundJob.status == BackgroundJobStatus.QUEUED.value]
        if self.job_types is not None:
            conditions.append(BackgroundJob.job_type.in_(self.job_types))
        if self.exclude_types is not None:
            conditions.append(BackgroundJob.job_type.not_in(self.exclude_types))
        rows = await self.db.execute(
            select(BackgroundJob).where(*conditions).order_by(BackgroundJob.created_at).limit(1)
        )
        job = rows.scalars().first()
        if job is None:
            return None
        result = await self.db.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.id == job.id,
                BackgroundJob.status == BackgroundJobStatus.QUEUED.value,
            )
            .values(
                status=BackgroundJobStatus.RUNNING.value,
                attempts=BackgroundJob.attempts + 1,
                claimed_at=now,
                heartbeat_at=now,
                updated_at=now,
            )
        )
        await self.db.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            return None
        await self.db.refresh(job)
        return job

    async def execute(self, job: BackgroundJob) -> None:
        """Run a claimed job; handles progress, cancellation, retry, failure."""
        job_id = job.id
        try:
            handler = HANDLERS.get(job.job_type)
            if handler is None:
                raise DomainError(f"Unknown job type: {job.job_type}")

            async def progress(
                value: int, stage: str, detail: dict[str, Any] | None = None
            ) -> None:
                """Write progress/stage and, when supplied, the bounded detail.

                The detail rides this single UPDATE — vector handlers never
                issue a second per-document write.
                """
                values: dict[str, Any] = {
                    "progress": value,
                    "stage": stage[:200],
                    "heartbeat_at": _utcnow(),
                }
                bounded = bound_progress_detail(detail)
                if bounded is not None:
                    values["progress_detail"] = bounded
                await self.db.execute(
                    update(BackgroundJob).where(BackgroundJob.id == job_id).values(**values)
                )
                await self.db.commit()

            async def cancelled() -> bool:
                fresh = await self.db.get(BackgroundJob, job_id)
                return bool(fresh and fresh.cancel_requested)

            result = await handler(self.db, job, progress=progress, cancelled=cancelled)

            fresh = await self.db.get(BackgroundJob, job_id)
            if fresh is not None and fresh.cancel_requested:
                await self._finish(job_id, BackgroundJobStatus.CANCELLED)
            else:
                await self._finish(
                    job_id,
                    BackgroundJobStatus.SUCCEEDED,
                    result=result,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Job %s failed: %s", job_id, exc)
            await self._fail(job_id, exc)

    async def _finish(
        self,
        job_id: uuid.UUID,
        status: BackgroundJobStatus,
        *,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": status.value,
            "error": error,
            "finished_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        if status == BackgroundJobStatus.SUCCEEDED:
            values["progress"] = 100
            values["stage"] = "done"
            values["result"] = result
            # The result is authoritative once it commits: the live detail is
            # telemetry, so it never survives next to the audit counters.
            values["progress_detail"] = None
        await self.db.execute(
            update(BackgroundJob).where(BackgroundJob.id == job_id).values(**values)
        )
        await self.db.commit()

    async def _fail(self, job_id: uuid.UUID, exc: Exception) -> None:
        """Retry with the remaining attempts budget, else fail terminally."""
        await self.db.rollback()
        job = await self.db.get(BackgroundJob, job_id)
        if job is None:
            return
        if job.cancel_requested:
            await self._finish(job_id, BackgroundJobStatus.CANCELLED)
            return
        if job.attempts < job.max_attempts:
            await self.db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(
                    status=BackgroundJobStatus.QUEUED.value,
                    stage=f"retrying (attempt {job.attempts}/{job.max_attempts})",
                    error=str(exc)[:500],
                    updated_at=_utcnow(),
                )
            )
            await self.db.commit()
            await asyncio.sleep(1.0 * job.attempts)
            return
        await self._finish(job_id, BackgroundJobStatus.FAILED, error=str(exc)[:500])

    async def recover_orphans(self) -> int:
        """Requeue jobs stuck in `running` (process died mid-flight)."""
        rows = await self.db.execute(
            select(BackgroundJob).where(BackgroundJob.status == BackgroundJobStatus.RUNNING.value)
        )
        orphans = list(rows.scalars().all())
        for job in orphans:
            if job.job_type == BackgroundJobType.VECTOR_CUTOVER.value:
                # A synchronous cutover evaluation cannot resume; re-running
                # the action is the only honest recovery (plan 51 Q1b).
                job.status = BackgroundJobStatus.FAILED.value
                job.error = "Interrupted by restart; re-run the action"
                job.finished_at = _utcnow()
                job.lock_key = None
                job.updated_at = _utcnow()
                continue
            if job.attempts < job.max_attempts:
                job.status = BackgroundJobStatus.QUEUED.value
                job.stage = "recovered after restart"
            else:
                job.status = BackgroundJobStatus.FAILED.value
                job.error = "Interrupted by restart"
                job.finished_at = _utcnow()
            job.updated_at = _utcnow()
        if orphans:
            await self.db.commit()
        return len(orphans)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _run_document_parse(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    from app.services.profile.document_service import DocumentService

    document_id = uuid.UUID(str(job.payload["document_id"]))
    user_id = _require_user(job)
    await progress(10, "extracting text")
    service = DocumentService(db)
    document = await service.parse(document_id, user_id)
    if document.status == "error":
        raise DomainError(document.error or "Parsing failed")
    await progress(100, "parsed")
    return {
        "document_id": str(document.id),
        "status": document.status,
        "universities": len((document.extraction or {}).get("universities", [])),
    }


async def _run_job_generate(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    from app.services.catalog.generation_service import run_generation

    result = await run_generation(
        db, _require_user(job), job.payload, progress=progress, cancelled=cancelled
    )
    return {
        "draft_count": len(result["drafts"]),
        "relation_count": len(result["relations"]),
        "note": result["note"],
    }


async def _run_match_score(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    from app.services.catalog.matching_service import MatchingService

    user_id = _require_user(job)
    payload = job.payload
    service = MatchingService(db)
    profile = await service.profile_for(user_id)
    targets = await service.resolve_targets(
        profile,
        job_ids=[uuid.UUID(j) for j in payload["job_ids"]] if payload.get("job_ids") else None,
        limit=int(payload.get("limit", 10)),
    )
    scored = 0
    insights = []
    total = max(len(targets), 1)
    for index, job_row in enumerate(targets):
        if await cancelled():
            raise DomainError("Cancelled")
        insight = await service.score_one(
            user_id,
            profile,
            job_row,
            force=bool(payload.get("force")),
        )
        if insight is not None:
            insights.append(insight)
            scored += 1
        await progress(
            int(10 + 85 * (index + 1) / total),
            f"scored {index + 1}/{total}: {job_row.title}",
        )
    await db.commit()
    return {"scored": scored, "job_ids": [str(i.job_id) for i in insights]}


async def _run_data_export(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    from app.models.user_model import User
    from app.services.admin.export_service import build_export

    await progress(20, "collecting your data")
    user = await db.get(User, _require_user(job))
    if user is None:
        raise DomainError("User not found")
    archive = await build_export(db, user, job.id)
    await progress(100, "export ready")
    return {
        "export_path": str(archive),
        "filename": archive.name,
        "size_bytes": archive.stat().st_size,
    }


async def _run_path_suggest(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """Draft career paths via AI for jobs without any (admin-triggered)."""
    from sqlalchemy import select

    from app.ai.agents import suggest_paths
    from app.models.career_path_model import CareerPath, CareerPathStep
    from app.models.enums import PathSource, PathStatus
    from app.models.taxonomy_model import Skill
    from app.services.catalog.job_service import JobService
    from app.services.catalog.taxonomy_service import TaxonomyService

    payload = job.payload or {}
    job_service = JobService(db)
    if payload.get("job_ids"):
        targets = []
        for ref in payload["job_ids"]:
            found = await job_service.get_by_code_or_id(ref)
            if found is not None:
                targets.append(found)
    else:
        targets, _, _ = await job_service.list_jobs(status="published", page_size=100)
    with_paths = {row[0] for row in await db.execute(select(CareerPath.job_id).distinct())}
    targets = [t for t in targets if t.id not in with_paths]
    if not targets:
        return {"paths_created": 0, "jobs": []}

    families = await job_service.families()
    family_keys = [f.key for f in families]
    skill_keys = [s.key for s in await TaxonomyService(db).skills(status="active")]
    created = 0
    touched = []
    total = len(targets)
    for index, target in enumerate(targets):
        if await cancelled():
            raise DomainError("Cancelled")
        draft_set = await suggest_paths(
            db,
            _require_user(job),
            JobService.job_snapshot(target),
            family_keys,
            skill_keys,
        )
        family_by_key = {f.key: f for f in families}
        for draft in draft_set.paths[:3]:
            if not draft.steps:
                continue
            path = CareerPath(
                job_id=target.id,
                title=draft.title,
                description=draft.description,
                source=PathSource.AI.value,
                status=PathStatus.DRAFT.value,
            )
            db.add(path)
            await db.flush()
            for position, step in enumerate(draft.steps[:8]):
                family = family_by_key.get(step.family_key) if step.family_key else None
                skill = None
                if step.skill_key:
                    rows = await db.execute(
                        select(Skill).where(Skill.key == step.skill_key, Skill.status == "active")
                    )
                    skill = rows.scalars().first()
                if step.kind == "education" and not step.education_level:
                    continue
                db.add(
                    CareerPathStep(
                        path_id=path.id,
                        position=position,
                        kind=step.kind,
                        family_id=family.id if family else None,
                        skill_id=skill.id if skill else None,
                        education_level=step.education_level,
                        label=step.label,
                        optional=step.optional,
                    )
                )
            created += 1
            touched.append(target.code)
        await progress(
            int(10 + 85 * (index + 1) / total),
            f"drafted paths for {index + 1}/{total}: {target.title}",
        )
    await db.commit()
    return {"paths_created": created, "jobs": touched[:20]}


async def _run_fit_refit(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """Deterministic refit — never calls AI.

    Payload `{"scope": "stale"}` sweeps every user whose stored job fits
    are on an old fit_version and backfills/refreshes the posting-fit
    cache within a row budget (the refit sweep); the default refits the
    job's user."""
    from app.services.postings.fit.service import FitService

    await progress(10, "recomputing fit")
    payload = job.payload or {}
    if payload.get("scope") == "stale":
        from sqlalchemy import select

        from app.models.matching_model import MatchInsight
        from app.services.postings.fit.dimensions import FIT_VERSION

        stale_users = (
            (
                await db.execute(
                    select(MatchInsight.user_id)
                    .where(MatchInsight.fit_version != FIT_VERSION)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        done = 0
        for _index, user_id in enumerate(stale_users):
            await FitService(db).refit_user(user_id)
            done += 1
            await progress(
                min(70, 10 + int(done / max(1, len(stale_users)) * 60)),
                "refitting users",
            )
        from datetime import timedelta

        from app.services.postings.posting_fit_service import (
            POSTING_FIT_SWEEP_AGE,
            POSTING_FIT_SWEEP_BUDGET,
            sweep_posting_fits,
        )

        posting_fits = await sweep_posting_fits(
            db,
            budget=int(payload.get("posting_fit_budget", POSTING_FIT_SWEEP_BUDGET)),
            older_than=timedelta(
                minutes=int(
                    payload.get("older_than_minutes", POSTING_FIT_SWEEP_AGE.total_seconds() / 60)
                )
            ),
            progress=progress,
        )
        await progress(100, "done")
        return {"refitted_users": done, "posting_fits": posting_fits}
    user_id = _require_user(job)

    async def report(done: int) -> None:
        await progress(min(90, 10 + done), "recomputing fit")

    refitted = await FitService(db).refit_user(user_id, progress=report)
    await progress(100, "done")
    return {"refitted": refitted}


async def _run_posting_sync(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Fetch every (or one) enabled source; expire stale postings after."""
    from app.services.postings.postings_service import run_sync_job

    return await run_sync_job(db, job.payload or {}, job_id=job.id)


async def _run_digest(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Weekly digest: radar + new-posting counts as one
    notification through the machinery."""
    from datetime import datetime

    from app.services.postings.digest_service import build_and_emit_digest

    payload = job.payload or {}
    user_id = payload.get("user_id") or _require_user(job)
    return await build_and_emit_digest(db, uuid.UUID(str(user_id)), now=datetime.now(UTC))


async def _run_followup_sweep(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Daily follow-up sweep: nudges for applied postings."""
    from app.services.postings.followups_service import sweep

    emitted = await sweep(db)
    await db.commit()
    return {"emitted": emitted}


async def _run_market_history_capture(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Daily demand-history capture: one snapshot per family
    and job scope with live postings; analytics only, never a fit input."""
    from app.services.postings.market_history_service import capture_all

    payload = job.payload or {}
    captured = await capture_all(db, limit=int(payload.get("limit") or 500))
    return {"captured": captured}


async def _run_proposal_sweep(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Daily HITL proposal TTL sweep (plan 77): pending cards older than
    14 days expire so the list endpoint stays authoritative."""
    from app.services.profile_proposal_service import ProfileProposalService

    expired = await ProfileProposalService(db).sweep_expired()
    return {"expired": expired}


async def _run_checkpoint_prune(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Daily checkpoint retention (plan 98 phase 4): prune stale LangGraph
    checkpoint threads (server Postgres; the desktop prunes SQLite at
    boot)."""
    from app.ai.checkpointer import prune_postgres_checkpoints
    from app.core.config import settings

    pruned = await prune_postgres_checkpoints(db, settings.checkpoint_ttl_days)
    await db.commit()
    return {"pruned": pruned}


async def _run_extension_reconcile(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """GitOps desired-state reconcile (plan 32 Phase 3 / ADR-0040 D13):
    installs and moves pins only — never enables, never deletes data."""
    from app.extensions.lifecycle import reconcile

    report = await reconcile(db)
    return {"report": {key: len(items) for key, items in report.items()}}


async def _run_demand_import(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Daily external demand import (plan 122): market sources feed salary
    and outlook data into `market_snapshots` and `jobs.demand`."""
    from app.services.postings.demand_import_service import ensure_demand_source, run_demand_import

    await ensure_demand_source(db)
    await db.commit()
    return await run_demand_import(db, job.payload or {})


async def _run_saved_search(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """A scheduled saved search: evaluate filters, notify on new matches."""
    from app.services.postings.digest_service import run_saved_search

    payload = job.payload or {}
    return await run_saved_search(db, payload)


async def _run_radar_digest(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """A scheduled job radar: the saved configuration as a live search,
    notifying on unseen matches (the saved-search contract)."""
    from app.services.postings.radar_service import run_radar_digest

    payload = job.payload or {}
    return await run_radar_digest(db, payload)


async def _run_smart_digest(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """The opt-in daily smart digest (plan 179): the S1 smart ranking over
    fresh/unseen/unapplied, notifying only when new matches exist — and
    the smart-search cache's TTL prune."""
    from app.services.postings.digest_service import run_smart_digest

    payload = job.payload or {}
    return await run_smart_digest(db, payload)


async def _run_detail_enrichment(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    from app.services.postings.detail_service import run_detail_enrichment

    return await run_detail_enrichment(db, job.payload or {}, user_id=job.user_id, job_id=job.id)


async def _run_company_triage(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Plan 135: drain one bounded pass of the gray-band company queue."""
    from app.services.catalog.company_triage_service import run_company_triage

    return await run_company_triage(db, job_id=job.id)


async def _run_posting_extract(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Deep posting extraction: one structured AI call per
    posting, normalized into posting_skills + typed columns."""
    from app.services.postings.extract_service import run_extract_job

    return await run_extract_job(db, job.payload or {}, job_id=job.id)


async def _run_cv_extract_text(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """CV source processing: text layer + OCR fallback."""
    from app.services.cv.cv_source_service import process_cv_document

    document_id = uuid.UUID(str(job.payload["document_id"]))
    user_id = _require_user(job)
    await progress(10, "extracting text")
    document = await process_cv_document(db, document_id, user_id)
    if document.status == "failed":
        raise DomainError(document.error or "CV text extraction failed")
    await progress(100, "done")
    if document.status == "ready":
        await enqueue(
            db,
            BackgroundJobType.CV_PARSE.value,
            {"document_id": str(document.id)},
            user_id=user_id,
        )
    return {
        "document_id": str(document.id),
        "status": document.status,
        "pages": document.page_count,
        "ocr_used": bool((document.extraction or {}).get("ocr_used")),
    }


async def _run_cv_ocr(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """Re-run OCR on every renderable page."""
    from app.services.cv.cv_source_service import process_cv_document

    document_id = uuid.UUID(str(job.payload["document_id"]))
    user_id = _require_user(job)
    await progress(10, "running OCR")
    document = await process_cv_document(db, document_id, user_id, force_ocr=True)
    if document.status == "failed":
        raise DomainError(document.error or "CV OCR failed")
    await progress(100, "done")
    return {
        "document_id": str(document.id),
        "status": document.status,
        "pages": document.page_count,
        "ocr_used": bool((document.extraction or {}).get("ocr_used")),
    }


async def _run_cv_parse(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """CV field extraction: text → review-first CvParseDraft."""
    from app.services.cv.cv_intake_service import CvIntakeService

    document_id = uuid.UUID(str(job.payload["document_id"]))
    user_id = _require_user(job)
    await progress(20, "parsing fields")
    draft = await CvIntakeService(db).parse_to_draft(document_id, user_id)
    await progress(100, "draft ready")
    payload = draft.payload or {}
    return {
        "document_id": str(document_id),
        "draft_id": str(draft.id),
        "experience": len(payload.get("experience") or []),
        "skills": len(payload.get("skills") or []),
        "education": len(payload.get("education") or []),
    }


def _require_user(job: BackgroundJob) -> uuid.UUID:
    if job.user_id is None:
        raise DomainError(f"{job.job_type} requires a user")
    return job.user_id


async def _run_catalog_enrich(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """sweep: propose v2 lifestyle attributes for archetypes
    missing them; proposals wait in ai_metadata for moderation."""
    from app.services.catalog.catalog_enrich_service import CatalogEnrichService

    return await CatalogEnrichService(db).run_sweep(
        limit=int((job.payload or {}).get("limit") or 5)
    )


async def _run_autopilot(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """One autopilot goal run: LangGraph flow on the queue."""
    from app.services.growth.autopilot_service import AutopilotService

    goal_id = uuid.UUID(str(job.payload["goal_id"]))
    user_id = _require_user(job)
    result = await AutopilotService(db).run_goal(
        goal_id,
        user_id,
        progress=progress,
        cancelled=cancelled,
    )
    await db.commit()
    return result


async def _run_cv_generate(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """One-shot CV generation: LangGraph flow on the queue."""
    from app.schemas.cv_generate import CvGenerateRequest
    from app.services.cv.cv_generate_service import CvGenerateService

    request = CvGenerateRequest.model_validate((job.payload or {}).get("request") or {})
    return await CvGenerateService(db).generate(
        _require_user(job),
        request,
        run_id=job.id,
        progress=progress,
        cancelled=cancelled,
    )


async def _run_cv_synth(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """Bulk synthesized-variant generation on the queue (plan 62)."""
    from app.models.enums import CvSynthStatus
    from app.schemas.cv_synth import CvSynthItemGenerate
    from app.services.cv.cv_synth_service import CvSynthService

    request = CvSynthItemGenerate.model_validate((job.payload or {}).get("request") or {})
    service = CvSynthService(db)
    rows = await service.generate(_require_user(job), request)
    activate = bool((job.payload or {}).get("activate"))
    if activate:
        from app.schemas.cv_synth import CvSynthItemUpdate

        settled = []
        for row in rows:
            if row.status == CvSynthStatus.DRAFT.value:
                row = await service.update(
                    row.id, _require_user(job), CvSynthItemUpdate(status="active")
                )
            settled.append(row)
        rows = settled
    drafts = [row for row in rows if row.status == CvSynthStatus.DRAFT.value]
    body = ""
    if activate and rows:
        # Approve-and-pin (plan-104 follow-up): a queued batch from a
        # builder-bound card pins on that CV as part of the apply.
        raw_request = (job.payload or {}).get("request") or {}
        raw_cv = str(raw_request.get("cv_id") or "")
        if raw_cv:
            try:
                cv_id = uuid.UUID(raw_cv)
                pinned_now = await service.pin_variants_on_cv(_require_user(job), cv_id, rows)
            except ValueError:
                pinned_now = False
            except Exception:
                # lose the completion notification over a failed pin.
                logger.exception("cv_synth pin-on-cv failed for job %s", job.id)
                pinned_now = False
            if pinned_now:
                body = (
                    f"{len(rows)} new variants were activated and pinned "
                    "— the CV preview refreshes in the Studio."
                )
    if activate and rows:
        from app.services.notification_service import NotificationService

        body = body or (
            f"{len(rows)} new variants were activated — find them in the CV synth library."
        )
        await NotificationService(db).emit(
            "cv_synth_ready",
            [_require_user(job)],
            title="Synthesized variants are active",
            body=body,
            payload={"count": len(rows), "ids": [str(r.id) for r in rows]},
            source_ref={"kind": "cv_synth", "job_id": str(job.id)},
        )
    elif drafts:
        from app.services.notification_service import NotificationService

        await NotificationService(db).emit(
            "cv_synth_ready",
            [_require_user(job)],
            title="Synthesized variants are ready for review",
            body=f"{len(drafts)} new variants are drafts — review them in the CV synth library.",
            payload={"count": len(drafts), "ids": [str(r.id) for r in drafts]},
            source_ref={"kind": "cv_synth", "job_id": str(job.id)},
        )
    return {"created": len(rows)}


async def _run_cv_polish(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """Polish-only run over a committed CV (plan 64 resume path)."""
    from app.services.cv.cv_generate_service import CvGenerateService

    payload = job.payload or {}
    return await CvGenerateService(db).polish(
        _require_user(job),
        uuid.UUID(payload.get("cv_id")),
        run_id=job.id,
        progress=progress,
        cancelled=cancelled,
        resumed_from=str(payload.get("resumed_from") or ""),
    )


async def _run_notification_delivery(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Send one queued webhook delivery (retries ride the job's attempts)."""
    from app.services.notification_webhook import process_delivery

    payload = job.payload or {}
    delivery_id = payload.get("delivery_id")
    if not delivery_id:
        return {"skipped": "delivery id missing"}
    return await process_delivery(db, uuid.UUID(str(delivery_id)))


async def _run_query_curator(db: AsyncSession, job, progress=None, cancelled=None) -> dict:
    """Plan 130 Layer 2: cluster radar tokens into role groups (AI optional)."""
    from app.services.postings.query_curator import rebuild_all_query_caches

    return await rebuild_all_query_caches(db)


async def _run_skill_relation_learn(
    db: AsyncSession, job: BackgroundJob, *, cancelled=None, **_kw
) -> dict:
    """Discovery pass: propose typed skill-relation edges from evidence."""
    from app.services.catalog.skill_relation_learn import run_skill_relation_learn

    return await run_skill_relation_learn(db, run_id=job.id, cancelled=cancelled)


def _payload_window(payload: dict) -> int:
    """The payload's ``window_documents``, defaulting to the service's 128."""
    from app.services.vector_reconcile_service import DEFAULT_WINDOW_DOCUMENTS

    try:
        return int(payload.get("window_documents") or DEFAULT_WINDOW_DOCUMENTS)
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DOCUMENTS


async def _run_vector_reconcile(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """Backfill/reconcile the vector store (plan 50 §5.7, P1d).

    Payload: ``{kinds?, limit?, budget?, batch_size?, scan_limit?, since?,
    force?, after?, carry?, completed_kinds?, auto_continue?}``. The scan is
    a bounded keyset batch; a partial result returns ``next_after`` and the
    handler enqueues one follow-up with the same options plus that cursor
    (``auto_continue`` defaults to true) so the chain resumes without a
    ledger. System budget: no ``user_id`` reaches the gateway, so the embed
    calls are attributed to the system path — an admin-triggered run is never
    charged to that admin's personal budget. A cancelled run never chains.
    """
    from app.ai.gateway import RunRef
    from app.services.vector_index_service import CONTENT_SPACE
    from app.services.vector_reconcile_service import (
        DEFAULT_SCAN_LIMIT,
        RECONCILE_KINDS,
        VectorReconcileService,
        parse_after,
        parse_carry,
        parse_completed_kinds,
        parse_kinds,
        parse_only,
        parse_progress_carry,
        parse_since,
    )

    payload = job.payload or {}
    try:
        kinds = parse_kinds(payload.get("kinds"))
        since = parse_since(payload.get("since"))
        after = parse_after(payload.get("after"))
        carry = parse_carry(payload.get("carry"))
        progress_carry = parse_progress_carry(payload.get("progress_carry"))
        completed = parse_completed_kinds(payload.get("completed_kinds"))
        only = parse_only(payload.get("source_ids"))
    except ValueError as exc:
        raise DomainError(str(exc)) from exc
    space = str(payload.get("space") or CONTENT_SPACE)
    space_id = payload.get("space_id")
    service = VectorReconcileService(
        db,
        space_name=space,
        space_id=str(space_id) if space_id else None,
        kinds=kinds,
        limit=int(payload.get("limit") or 200),
        budget=int(payload.get("budget") or 2000),
        batch_size=int(payload.get("batch_size") or 10),
        window_documents=_payload_window(payload),
        scan_limit=int(payload.get("scan_limit") or DEFAULT_SCAN_LIMIT),
        after=after,
        carry=carry,
        progress_carry=progress_carry,
        completed_kinds=completed,
        since=since,
        force=bool(payload.get("force")),
        only=only,
        run=RunRef(id=job.id, stage="vector_reconcile"),
    )
    result = await service.run(progress=progress, cancelled=cancelled)
    if result.cancelled:
        await progress(95, "cancelled")
    elif (
        only is None
        and not result.done
        and payload.get("auto_continue", True)
        and result.scanned > 0
    ):
        follow = _continuation_payload(
            payload,
            result,
            space=space,
            kinds=kinds or RECONCILE_KINDS,
        )
        if not await has_pending_reconcile(db, follow["continuation_key"]):
            # Transfer the single-active-run lock to the continuation: the
            # parent is about to finish, and releasing the lock in between
            # would let another admin start a competing run.
            parent_lock = job.lock_key
            if parent_lock:
                job.lock_key = None
                await db.execute(
                    update(BackgroundJob).where(BackgroundJob.id == job.id).values(lock_key=None)
                )
                await db.flush()
            follow_job = BackgroundJob(
                user_id=job.user_id,
                job_type=BackgroundJobType.VECTOR_RECONCILE.value,
                payload=follow,
                lock_key=parent_lock,
                max_attempts=job.max_attempts,
            )
            db.add(follow_job)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                logger.warning(
                    "vector reconcile continuation for %s could not take the space lock",
                    space_id or space,
                )
    return result.as_dict()


def _continuation_key(space: str, kinds: Sequence[str], after: dict[str, dict]) -> str:
    """A stable identity for one continuation cursor (idempotency key)."""
    parts = [space, ",".join(sorted(str(kind) for kind in kinds))]
    for kind in sorted(after):
        cursor = after[kind]
        parts.append(f"{kind}@{cursor.get('updated_at')}@{cursor.get('id')}")
    return "|".join(parts)


def _continuation_payload(
    payload: dict,
    result,
    *,
    space: str,
    kinds: Sequence[str],
) -> dict:
    """The same run options plus the cursor state that resumes the chain."""
    follow = {
        key: value
        for key, value in payload.items()
        if key not in {"after", "carry", "completed_kinds", "continuation_key", "progress_carry"}
    }
    after = {kind: cursor for kind, cursor in result.next_after.items() if cursor is not None}
    follow["after"] = after
    follow["carry"] = result.carry
    follow["progress_carry"] = getattr(result, "progress", {})
    follow["completed_kinds"] = list(result.completed_kinds)
    follow["continuation_key"] = _continuation_key(space, kinds, after)
    return follow


async def has_pending_reconcile(db: AsyncSession, continuation_key: str) -> bool:
    """True when a continuation job for this exact cursor is queued/running."""
    rows = await db.execute(
        select(BackgroundJob.id).where(
            BackgroundJob.job_type == BackgroundJobType.VECTOR_RECONCILE.value,
            BackgroundJob.status.in_(
                [
                    BackgroundJobStatus.QUEUED.value,
                    BackgroundJobStatus.RUNNING.value,
                ]
            ),
            BackgroundJob.payload["continuation_key"].as_string() == continuation_key,
        )
    )
    return rows.scalars().first() is not None


async def _run_job_proposal_backfill(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """Regenerate or clear legacy v1 job proposals (plan 202 AD8)."""
    from app.services.postings.job_proposal_backfill import run_job_proposal_backfill

    return await run_job_proposal_backfill(
        db,
        job.payload or {},
        run_id=job.id,
        progress=progress,
        cancelled=cancelled,
    )


async def _run_mapping_coverage_capture(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """One daily mapping-coverage snapshot (plan 205 S9)."""
    from app.services.postings import mapping_ops

    del job
    await progress(10, "capturing the mapping coverage snapshot")
    if await cancelled():
        return {"captured": False, "reason": "cancelled"}
    row = await mapping_ops.capture_snapshot(db)
    pruned = await mapping_ops.prune_snapshots(db)
    await db.commit()
    await progress(100, "snapshot captured")
    return {
        "captured": True,
        "snapshot_id": str(row.id),
        "total": row.total,
        "accounted": row.accounted,
        "pruned": pruned,
    }


async def _run_mapping_alert_sweep(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """One bounded mapping-alert evaluation pass (plan 205 S9)."""
    from app.services.postings import mapping_ops

    del job
    await progress(10, "evaluating mapping alerts")
    if await cancelled():
        return {"emitted": 0, "reason": "cancelled"}
    result = await mapping_ops.evaluate_mapping_alerts(db)
    await db.commit()
    await progress(100, "sweep complete")
    return result


async def _run_mapping_outcome_backfill(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """Derive the typed mapping outcome for legacy rows (plan 205 S2)."""
    from app.services.postings.mapping_outcome_backfill import run_mapping_outcome_backfill

    return await run_mapping_outcome_backfill(
        db,
        job.payload or {},
        progress=progress,
        cancelled=cancelled,
    )


async def _run_posting_remap(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """Re-decide semantic mapping rows after a space cutover (plan 50 P2b).

    Payload: ``{space_key?, all_postings?, batch_size?, after_id?,
    auto_continue?}``. Only rows whose ``mapping_method`` is ``semantic`` or
    ``semantic_rerank`` are selected — ``manual`` never is. The handler
    commits its batch and enqueues one continuation with the next cursor;
    plan 51's space-retirement action calls
    :func:`invalidate_mapping_space` to start the chain.
    """
    from app.services.postings.mapping_remap import run_posting_remap

    return await run_posting_remap(
        db,
        job.payload or {},
        run_id=job.id,
        progress=progress,
        cancelled=cancelled,
    )


async def _run_vector_index(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """Index one source document into the family vector store (plan 50 P1c).

    Payload: ``{kind, source_id, space?, force?}``. Composes, embeds only the
    changed records, writes with ``prune=False`` and prunes the leftover
    keys; a missing embed provider returns a degraded result instead of
    failing the run.
    """
    from app.ai.gateway import RunRef
    from app.services.vector_index_service import CONTENT_SPACE, VectorIndexService

    payload = job.payload or {}
    kind = str(payload.get("kind") or "")
    source_id = str(payload.get("source_id") or "")
    if not kind or not source_id:
        raise DomainError("vector_index requires kind and source_id")
    await progress(5, "loading source")
    service = VectorIndexService(
        db,
        space_name=str(payload.get("space") or CONTENT_SPACE),
        user_id=job.user_id,
        run=RunRef(id=job.id, stage="vector_index"),
    )
    outcome = await service.index_document(
        kind=kind,
        source_id=source_id,
        force=bool(payload.get("force")),
        progress=progress,
    )
    if await cancelled():
        raise DomainError("Cancelled")
    return outcome.as_result()


async def _run_vector_maintenance(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """One typed maintenance action (plan 51 Q1b).

    Payload: ``{space_id, action, dry_run?, limit?}``. The bounded
    implementation lives in :mod:`app.services.vector_maintenance`; this
    handler only supplies progress and the run-result envelope.
    """
    from app.services.vector_maintenance import run_maintenance

    payload = job.payload or {}
    space_id = payload.get("space_id")
    if not space_id:
        raise DomainError("vector_maintenance requires space_id")
    await progress(10, f"maintenance {payload.get('action') or 'unknown'}")
    if await cancelled():
        raise DomainError("Cancelled")
    result = await run_maintenance(
        db,
        space_id=str(space_id),
        action=str(payload.get("action") or ""),
        dry_run=bool(payload.get("dry_run")),
        limit=int(payload["limit"]) if payload.get("limit") is not None else None,
        cancelled=cancelled,
    )
    await progress(100, "maintenance done")
    return result


async def _run_tokenizer_fetch(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """One bounded pinned tokenizer fetch (plan 52 T2b)."""
    from app.services.tokenizer_fetch import handle_tokenizer_fetch

    return await handle_tokenizer_fetch(db, job, progress=progress, cancelled=cancelled)


async def _run_vector_cutover(
    db: AsyncSession,
    job: BackgroundJob,
    **_kw,
) -> dict:
    """Cutover/gate evaluations are executed by the action API.

    A queued row here means something bypassed the action seam; fail honestly
    instead of pretending a cutover ran.
    """
    del db, job
    raise DomainError(
        "VECTOR_CUTOVER evaluations are recorded by /admin/retrieval actions; "
        "nothing is queued to execute"
    )


async def _run_retrieval_alert_sweep(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    """One bounded retrieval-alert evaluation pass (plan 51 Q1c)."""
    from app.services.retrieval_alerts import evaluate_retrieval_alerts

    del job
    await progress(10, "evaluating retrieval alerts")
    if await cancelled():
        raise DomainError("Cancelled")
    result = await evaluate_retrieval_alerts(db)
    await progress(100, "retrieval alerts evaluated")
    return result


HANDLERS: dict[str, Handler] = {
    "document_parse": _run_document_parse,
    "job_generate": _run_job_generate,
    "match_score": _run_match_score,
    "data_export": _run_data_export,
    "path_suggest": _run_path_suggest,
    "fit_refit": _run_fit_refit,
    "posting_sync": _run_posting_sync,
    "posting_extract": _run_posting_extract,
    "detail_enrichment": _run_detail_enrichment,
    "company_triage": _run_company_triage,
    "digest": _run_digest,
    "followup_sweep": _run_followup_sweep,
    "market_history_capture": _run_market_history_capture,
    "proposal_sweep": _run_proposal_sweep,
    "checkpoint_prune": _run_checkpoint_prune,
    "extension_reconcile": _run_extension_reconcile,
    "saved_search_run": _run_saved_search,
    "radar_digest": _run_radar_digest,
    "smart_digest": _run_smart_digest,
    "query_curator": _run_query_curator,
    "cv_extract_text": _run_cv_extract_text,
    "cv_ocr": _run_cv_ocr,
    "cv_parse": _run_cv_parse,
    "catalog_enrich": _run_catalog_enrich,
    "autopilot_run": _run_autopilot,
    "cv_generate": _run_cv_generate,
    "cv_polish": _run_cv_polish,
    "cv_synth": _run_cv_synth,
    "notification_delivery": _run_notification_delivery,
    "demand_import": _run_demand_import,
    "skill_relation_learn": _run_skill_relation_learn,
    "vector_index": _run_vector_index,
    "vector_reconcile": _run_vector_reconcile,
    "vector_maintenance": _run_vector_maintenance,
    "vector_cutover": _run_vector_cutover,
    "retrieval_alert_sweep": _run_retrieval_alert_sweep,
    "posting_remap": _run_posting_remap,
    "job_proposal_backfill": _run_job_proposal_backfill,
    "mapping_outcome_backfill": _run_mapping_outcome_backfill,
    "mapping_coverage_capture": _run_mapping_coverage_capture,
    "mapping_alert_sweep": _run_mapping_alert_sweep,
    "tokenizer_fetch": _run_tokenizer_fetch,
}


async def start_workers(
    worker_count: int,
    *,
    ingest_worker_count: int = 0,
    vector_worker_count: int = 0,
) -> list[asyncio.Task]:
    """Recover orphaned jobs, purge stale exports, start the worker lanes.

    The lane layout comes from :func:`worker_specs`: ``worker_count`` generic
    workers (they exclude a family that has its own lane), plus one serial lane
    per requested family (plan 203). The stale-run reaper stays a single task.
    """
    from app.services.retrieval_jobs import reap_stale_runs, reaper_loop

    async with AsyncSessionLocal() as db:
        # Reap stale vector runs *before* the boot orphan recovery: a crashed
        # run past the 15-minute heartbeat window must fail (and release its
        # space lock) rather than be silently requeued forever.
        reaped = await reap_stale_runs(db)
        if reaped:
            logger.warning("Reaped %d stale vector run(s) at boot", len(reaped))
        recovered = await JobWorker(db).recover_orphans()
        if recovered:
            logger.info("Recovered %d orphaned background job(s)", recovered)
    from app.services.admin.export_service import cleanup_old_exports

    purged = cleanup_old_exports()
    if purged:
        logger.info("Purged %d stale export archive(s)", purged)
    specs = worker_specs(
        generic=worker_count, ingest=ingest_worker_count, vector=vector_worker_count
    )
    logger.info(
        "Starting %d background worker(s): %s",
        len(specs),
        ", ".join(
            "generic" if spec.job_types is None else f"lane={sorted(spec.job_types)}"
            for spec in specs
        )
        or "none",
    )
    tasks = [asyncio.create_task(_worker_loop(spec)) for spec in specs]
    tasks.append(asyncio.create_task(reaper_loop()))
    return tasks


async def drain_queue(db: AsyncSession | None = None) -> int:
    """Claim + execute queued jobs until the queue is empty (shutdown path).

    Single-claimant semantics (same as); the caller bounds it via
    asyncio.wait_for so a failing job can never hang the quit.
    """
    executed = 0
    if db is None:
        async with AsyncSessionLocal() as owned:
            return await drain_queue(owned)
    worker = JobWorker(db)
    while await worker.run_once():
        executed += 1
    return executed


async def _worker_loop(spec: WorkerSpec | None = None) -> None:
    async with AsyncSessionLocal() as db:
        spec = spec or WorkerSpec()
        await JobWorker(
            db, job_types=spec.job_types, exclude_types=spec.exclude_types
        ).run_forever()
