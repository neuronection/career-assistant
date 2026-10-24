"""Localized catalog views: apply approved label overlays to read models.

Every surface that renders catalog labels goes through this module so the
resolution rule lives in exactly one place (approved overlay -> base
label -> key slug). Endpoints resolve the caller's locale once and pass
the rows here; nothing else knows about `label_overrides`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LabelEntityKind
from app.models.job_model import Job
from app.models.user_model import User
from app.schemas.job import JobOut
from app.services.catalog.label_overlay_service import LabelOverlayService
from app.services.locale_service import effective_locale


async def resolve_locale(db: AsyncSession, user: User | None) -> str:
    """The caller's effective locale (thin alias for endpoint readability)."""
    return await effective_locale(db, user)


async def job_outs(db: AsyncSession, jobs: Sequence[Job], locale: str) -> list[JobOut]:
    """Serialize jobs with approved title/summary/skill labels applied."""
    service = LabelOverlayService(db)
    job_ids = [job.id for job in jobs]
    job_overlays = await service.approved_map(LabelEntityKind.JOB, job_ids, locale)
    skill_ids = {
        link.skill_id
        for job in jobs
        for link in (job.skill_links or [])
        if link.skill_id is not None
    }
    skill_overlays = await service.approved_map(LabelEntityKind.SKILL, skill_ids, locale)
    family_ids = {job.family_id for job in jobs if job.family_id is not None}
    family_overlays = await service.approved_map(LabelEntityKind.FAMILY, family_ids, locale)
    return [
        JobOut.from_model(
            job,
            overlay=job_overlays.get(job.id),
            skill_labels={
                skill_id: values["label"]
                for skill_id, values in skill_overlays.items()
                if values.get("label")
            },
            family_label=(
                family_overlays.get(job.family_id, {}).get("label")
                if job.family_id is not None
                else None
            )
            or (job.family.label if job.family else ""),
        )
        for job in jobs
    ]


async def job_out(db: AsyncSession, job: Job, locale: str) -> JobOut:
    """One localized job view."""
    return (await job_outs(db, [job], locale))[0]


async def localize_family_tree(db: AsyncSession, nodes: list[dict], locale: str) -> list[dict]:
    """Apply family label/description overlays to a nested tree in place."""
    service = LabelOverlayService(db)
    flat: list[dict] = []

    def collect(rows: list[dict]) -> None:
        for row in rows:
            flat.append(row)
            collect(row.get("children") or [])

    collect(nodes)
    ids = [uuid.UUID(str(row["id"])) for row in flat]
    overlays = await service.approved_map(LabelEntityKind.FAMILY, ids, locale)
    for row in flat:
        values = overlays.get(uuid.UUID(str(row["id"])), {})
        if values.get("label"):
            row["label"] = values["label"]
        if values.get("description"):
            row["description"] = values["description"]
    return nodes
