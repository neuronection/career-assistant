"""Durable background job queue: claim-based in-process worker pool.

A `background_jobs` table is the queue (see dev/plans/12-background-jobs.md).
Workers claim with a conditional UPDATE whose rowcount decides the winner —
portable across PostgreSQL and SQLite with no extra infrastructure. Handlers
reuse the existing services; only the entry point moves off the request path.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.errors import DomainError
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus

logger = logging.getLogger(__name__)

TERMINAL = (
    BackgroundJobStatus.SUCCEEDED.value,
    BackgroundJobStatus.FAILED.value,
    BackgroundJobStatus.CANCELLED.value,
)

ProgressCb = Callable[[int, str], Awaitable[None]]
CancelledCb = Callable[[], Awaitable[bool]]
Handler = Callable[..., Awaitable[dict]]


async def enqueue(
    db: AsyncSession,
    job_type: str,
    payload: dict,
    user_id: uuid.UUID | None = None,
    max_attempts: int = 2,
) -> BackgroundJob:
    """Queue a job for the worker pool."""
    job = BackgroundJob(
        user_id=user_id,
        job_type=job_type,
        payload=payload,
        max_attempts=max_attempts,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


class JobWorker:
    """Single-worker loop; instantiate one per configured concurrency."""

    def __init__(self, db: AsyncSession, poll_interval: float = 1.0):
        self.db = db
        self.poll_interval = poll_interval

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
        """Claim the oldest queued job, or None when the queue is empty.

        The conditional UPDATE (status still 'queued') arbitrates between
        competing claimants without dialect-specific locking.
        """
        now = _utcnow()
        rows = await self.db.execute(
            select(BackgroundJob)
            .where(BackgroundJob.status == BackgroundJobStatus.QUEUED.value)
            .order_by(BackgroundJob.created_at)
            .limit(1)
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
        if result.rowcount == 0:
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

            async def progress(value: int, stage: str) -> None:
                await self.db.execute(
                    update(BackgroundJob)
                    .where(BackgroundJob.id == job_id)
                    .values(progress=value, stage=stage[:200], heartbeat_at=_utcnow())
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
        except Exception as exc:  # noqa: BLE001 — queue must survive any handler
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
            select(BackgroundJob).where(
                BackgroundJob.status == BackgroundJobStatus.RUNNING.value
            )
        )
        orphans = list(rows.scalars().all())
        for job in orphans:
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
    return datetime.now(timezone.utc)


async def _run_document_parse(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    progress: ProgressCb,
    cancelled: CancelledCb,
) -> dict:
    from app.services.document_service import DocumentService

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
    from app.services.generation_service import run_generation

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
    from app.services.matching_service import MatchingService

    user_id = _require_user(job)
    payload = job.payload
    service = MatchingService(db)
    profile = await service.profile_for(user_id)
    targets = await service.resolve_targets(
        profile,
        job_ids=[uuid.UUID(j) for j in payload["job_ids"]]
        if payload.get("job_ids")
        else None,
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
    from app.services.export_service import build_export

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
    from app.services.job_service import JobService
    from app.services.taxonomy_service import TaxonomyService

    payload = job.payload or {}
    job_service = JobService(db)
    if payload.get("job_ids"):
        targets = []
        for ref in payload["job_ids"]:
            found = await job_service.get_by_code_or_id(ref)
            if found is not None:
                targets.append(found)
    else:
        targets, _ = await job_service.list_jobs(status="published", page_size=100)
    with_paths = {
        row[0] for row in await db.execute(select(CareerPath.job_id).distinct())
    }
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
                        select(Skill).where(
                            Skill.key == step.skill_key, Skill.status == "active"
                        )
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
    """Deterministic refit (plan 22) — never calls AI.

    Payload `{"scope": "stale"}` sweeps every user whose stored fits are
    on an old fit_version (the plan-29 refit sweep); default refits the
    job's user."""
    from app.services.fit.service import FitService

    await progress(10, "recomputing fit")
    payload = job.payload or {}
    if payload.get("scope") == "stale":
        from sqlalchemy import select

        from app.models.matching_model import MatchInsight
        from app.services.fit.dimensions import FIT_VERSION

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
        for index, user_id in enumerate(stale_users):
            await FitService(db).refit_user(user_id)
            done += 1
            await progress(
                min(90, 10 + int(done / max(1, len(stale_users)) * 80)),
                "refitting users",
            )
        await progress(100, "done")
        return {"refitted_users": done}
    user_id = _require_user(job)

    async def report(done: int) -> None:
        await progress(min(90, 10 + done), "recomputing fit")

    refitted = await FitService(db).refit_user(user_id, progress=report)
    await progress(100, "done")
    return {"refitted": refitted}


async def _run_posting_sync(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Fetch every (or one) enabled source; expire stale postings after."""
    from app.services.postings_service import run_sync_job

    return await run_sync_job(db, job.payload or {})


async def _run_digest(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Weekly digest (plan 29): radar + new-posting counts as one
    notification through the plan-24 machinery."""
    from datetime import datetime, timezone

    from app.services.digest_service import build_and_emit_digest

    payload = job.payload or {}
    user_id = payload.get("user_id") or _require_user(job)
    return await build_and_emit_digest(
        db, uuid.UUID(str(user_id)), now=datetime.now(timezone.utc)
    )


async def _run_saved_search(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """A scheduled saved search: evaluate filters, notify on new matches."""
    from app.services.digest_service import run_saved_search

    payload = job.payload or {}
    return await run_saved_search(db, payload)


async def _run_posting_extract(db: AsyncSession, job: BackgroundJob, **_kw) -> dict:
    """Deep posting extraction (plan 31): one structured AI call per
    posting, normalized into posting_skills + typed columns."""
    from app.services.extract_service import run_extract_job

    return await run_extract_job(db, job.payload or {})


def _require_user(job: BackgroundJob) -> uuid.UUID:
    if job.user_id is None:
        raise DomainError(f"{job.job_type} requires a user")
    return job.user_id


HANDLERS: dict[str, Handler] = {
    "document_parse": _run_document_parse,
    "job_generate": _run_job_generate,
    "match_score": _run_match_score,
    "data_export": _run_data_export,
    "path_suggest": _run_path_suggest,
    "fit_refit": _run_fit_refit,
    "posting_sync": _run_posting_sync,
    "posting_extract": _run_posting_extract,
    "digest": _run_digest,
    "saved_search_run": _run_saved_search,
}


async def start_workers(worker_count: int) -> list[asyncio.Task]:
    """Recover orphaned jobs, purge stale exports, start `worker_count` tasks."""
    async with AsyncSessionLocal() as db:
        recovered = await JobWorker(db).recover_orphans()
        if recovered:
            logger.info("Recovered %d orphaned background job(s)", recovered)
    from app.services.export_service import cleanup_old_exports

    purged = cleanup_old_exports()
    if purged:
        logger.info("Purged %d stale export archive(s)", purged)
    return [asyncio.create_task(_worker_loop()) for _ in range(max(worker_count, 0))]


async def drain_queue(db: AsyncSession | None = None) -> int:
    """Claim + execute queued jobs until the queue is empty (shutdown path).

    Single-claimant semantics (same as plan 12); the caller bounds it via
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


async def _worker_loop() -> None:
    async with AsyncSessionLocal() as db:
        await JobWorker(db).run_forever()
