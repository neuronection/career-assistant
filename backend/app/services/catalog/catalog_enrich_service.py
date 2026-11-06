"""Catalog enrichment sweep: archetypes gain the v2 lifestyle
vocabulary through a moderation-reviewed AI pass.

The sweep picks published jobs that
carry none of the v2 fields, runs one audited CATALOG_ENRICH call per
job, and stores the proposal in `ai_metadata["enrichment_proposal"]` —
nothing merges automatically. Admins apply or reject; the patch contract
covers v2 fields only, so salary/education stay human-owned.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.catalog_enricher import EnrichmentPatch
from app.core.errors import NotFoundError
from app.models.job_model import Job
from app.services.catalog.job_service import JobService

logger = logging.getLogger(__name__)

V2_KEYS = (
    "contract_type",
    "work_hours",
    "schedule_cues",
    "travel_required",
    "benefits_kinds",
)


def _proposal_of(job: Job) -> dict | None:
    return (job.ai_metadata or {}).get("enrichment_proposal") or None


def _pending_predicate(dialect_name: str):
    """Rows carrying a live enrichment proposal, filtered in the database.

    The key's JSON *type* decides it, not mere presence: rejection stores
    an explicit JSON ``null`` under the same key (``enrichment_rejected_at``
    keeps the audit trail), so a presence test would resurrect discarded
    proposals on PostgreSQL while SQLite's NULL-extracting accessor hid
    the divergence. ``object`` is the only live shape — the writer stores
    validated, non-empty patches.
    """
    if dialect_name == "postgresql":
        return text("jsonb_typeof(ai_metadata -> 'enrichment_proposal') = 'object'")
    return text("json_type(ai_metadata, '$.enrichment_proposal') = 'object'")


class CatalogEnrichService:
    """Sweep + moderation for archetype v2 enrichment."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def candidates(self, limit: int = 50) -> list[Job]:
        """Published jobs carrying none of the v2 fields, oldest first."""
        rows = await self.db.execute(
            select(Job).where(Job.status == "published").order_by(Job.created_at)
        )
        jobs = list(rows.scalars().all())
        missing = [
            job
            for job in jobs
            if not any((job.attributes or {}).get(key) for key in V2_KEYS)
            and _proposal_of(job) is None
        ]
        return missing[: max(1, min(limit, 200))]

    async def run_sweep(self, limit: int = 5) -> dict:
        """Propose v2 patches for up to `limit` jobs (one audited call each)."""
        proposed = 0
        for job in await self.candidates(limit=limit):
            patch = await self._propose(job)
            if not patch.non_empty():
                continue
            job.ai_metadata = {
                **(job.ai_metadata or {}),
                "enrichment_proposal": patch.model_dump(mode="json"),
                "enrichment_proposed_at": datetime.now(UTC).isoformat(),
            }
            self.db.add(job)
            proposed += 1
        await self.db.commit()
        return {"proposed": proposed}

    async def _propose(self, job: Job) -> EnrichmentPatch:
        from app.ai.agents.catalog_enricher import propose_enrichment

        return await propose_enrichment(
            self.db,
            job.created_by,
            title=job.title,
            description=job.short_description,
            attributes=job.attributes or {},
        )

    async def pending(
        self,
        *,
        cursor: tuple[datetime, UUID] | None = None,
        limit: int = 50,
    ) -> list[Job]:
        """Jobs with an enrichment proposal awaiting review, oldest job first.

        Keyset-ordered by ``(created_at, id)`` — never ``updated_at``: every
        moderation rewrites it, which makes a paging cursor skip or repeat
        rows. One extra row is fetched so the caller can answer ``next_cursor``
        without a second count.
        """
        stmt = select(Job).where(
            Job.status == "published",
            _pending_predicate(self.db.get_bind().dialect.name),
        )
        if cursor is not None:
            created_at, job_id = cursor
            stmt = stmt.where(
                or_(
                    Job.created_at > created_at,
                    and_(Job.created_at == created_at, Job.id > job_id),
                )
            )
        rows = await self.db.execute(
            stmt.order_by(Job.created_at, Job.id).limit(max(1, min(limit, 200)) + 1)
        )
        return list(rows.scalars().all())

    async def count_pending(self) -> int:
        """Cheap backlog count for the taxonomy stats bar (plan 161)."""
        total = await self.db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.status == "published", _pending_predicate(self.db.get_bind().dialect.name))
        )
        return int(total or 0)

    async def _merge(self, job: Job) -> Job:
        """Merge the proposal's fields and commit — no derived rebuild."""
        proposal = _proposal_of(job)
        if not proposal:
            raise NotFoundError("No enrichment proposal pending for this job")
        patch = EnrichmentPatch.model_validate(proposal)
        from app.schemas.job import JobAttributes

        attributes = JobAttributes.model_validate(
            {**(job.attributes or {}), **patch.model_dump(exclude={"note"})}
        )
        job.attributes = attributes.model_dump(mode="json")
        job.ai_metadata = {
            **(job.ai_metadata or {}),
            "enrichment_proposal": None,
            "enrichment_applied_at": datetime.now(UTC).isoformat(),
        }
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def apply(self, job: Job) -> Job:
        """Merge the proposal's v2 fields into the curated attributes."""
        job = await self._merge(job)
        await JobService(self.db)._refit_job(job.id)
        await JobService(self.db)._refresh_transferability()
        return job

    async def reject(self, job: Job) -> Job:
        if not _proposal_of(job):
            raise NotFoundError("No enrichment proposal pending for this job")
        job.ai_metadata = {
            **(job.ai_metadata or {}),
            "enrichment_proposal": None,
            "enrichment_rejected_at": datetime.now(UTC).isoformat(),
        }
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def bulk(self, ids: list[UUID], action: str) -> "EnrichBulkReport":
        """Apply or reject a batch with per-item outcomes (plan 200).

        Each row commits on its own, so a partial batch keeps what landed.
        The fit refit and the transferability rebuild run ONCE for the whole
        batch; if they fail after the commits, the report carries a warning
        instead of turning applied rows into reported failures.
        """
        report = EnrichBulkReport()
        for job_id in ids:
            job = (await self.db.execute(select(Job).where(Job.id == job_id))).scalars().first()
            if job is None:
                report.failed.append((job_id, "Job not found"))
                continue
            try:
                if action == "apply":
                    await self._merge(job)
                else:
                    await self.reject(job)
            except NotFoundError as exc:
                report.failed.append((job_id, str(exc)))
                continue
            report.affected.append(job_id)
        if action == "apply" and report.affected:
            try:
                from app.services.postings.fit.service import FitService

                await FitService(self.db).refit_jobs(report.affected)
                await JobService(self.db)._refresh_transferability()
            except Exception:
                logger.exception(
                    "bulk enrichment refit failed after applying %s job(s)",
                    len(report.affected),
                )
                report.warning = (
                    "The proposals were applied, but the fit refresh failed; "
                    "it will catch up on the next catalog rebuild."
                )
        return report


@dataclass
class EnrichBulkReport:
    """Outcome of one enrichment bulk call."""

    affected: list[UUID] = field(default_factory=list)
    failed: list[tuple[UUID, str]] = field(default_factory=list)
    warning: str | None = None
