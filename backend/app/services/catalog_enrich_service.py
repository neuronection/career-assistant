"""Catalog enrichment sweep: archetypes gain the v2 lifestyle
vocabulary through a moderation-reviewed AI pass.

The sweep picks published jobs that
carry none of the v2 fields, runs one audited CATALOG_ENRICH call per
job, and stores the proposal in `ai_metadata["enrichment_proposal"]` —
nothing merges automatically. Admins apply or reject; the patch contract
covers v2 fields only, so salary/education stay human-owned.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.catalog_enricher import EnrichmentPatch
from app.models.job_model import Job
from app.services.job_service import JobService

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
                "enrichment_proposed_at": datetime.now(timezone.utc).isoformat(),
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

    async def pending(self) -> list[Job]:
        """Jobs with an enrichment proposal awaiting review."""
        rows = await self.db.execute(
            select(Job).where(Job.status == "published").order_by(Job.updated_at)
        )
        return [job for job in rows.scalars().all() if _proposal_of(job)]

    async def apply(self, job: Job) -> Job:
        """Merge the proposal's v2 fields into the curated attributes."""
        proposal = _proposal_of(job)
        if not proposal:
            from app.core.errors import NotFoundError

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
            "enrichment_applied_at": datetime.now(timezone.utc).isoformat(),
        }
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        await JobService(self.db)._refit_job(job.id)
        await JobService(self.db)._refresh_transferability()
        return job

    async def reject(self, job: Job) -> Job:
        if not _proposal_of(job):
            from app.core.errors import NotFoundError

            raise NotFoundError("No enrichment proposal pending for this job")
        job.ai_metadata = {
            **(job.ai_metadata or {}),
            "enrichment_proposal": None,
            "enrichment_rejected_at": datetime.now(timezone.utc).isoformat(),
        }
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job
