"""One-shot v1 → v2 job-proposal backfill (plan 202 AD8).

Selects every live v1 proposal object (object + ``proposal_version <> 2``),
oldest first, bounded by ``limit``/``posting_ids``. Each selected row ends
with a v2 object or no ``job_proposal`` at all: the v1 shape can never
survive the release. No re-extract; the stored extract is the input.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus, BackgroundJobType
from app.models.posting_model import JobPosting
from app.models.settings_model import AppSetting
from app.services.postings.job_proposal_service import (
    MIN_PROPOSAL_SKILLS,
    clear_job_proposal,
    legacy_proposal_count,
    proposal_version_predicate,
)

logger = logging.getLogger(__name__)

BACKFILL_LIMIT_DEFAULT = 50
BACKFILL_LIMIT_MAX = 200
FIRST_BOOT_MARKER = "catalog.job_proposal_backfill.boot"
TERMINAL_STATUSES = ("expired", "hidden")


async def run_job_proposal_backfill(
    db: AsyncSession,
    payload: dict,
    *,
    run_id: uuid.UUID | None = None,
    progress=None,
    cancelled=None,
) -> dict:
    """Regenerate or clear the selected v1 proposals; per-row transactions."""
    from app.services.postings.catalog_settings import job_proposals_enabled
    from app.services.postings.mapping_remap import redecide_and_propose

    limit = max(1, min(int(payload.get("limit") or BACKFILL_LIMIT_DEFAULT), BACKFILL_LIMIT_MAX))
    posting_ids = [uuid.UUID(str(value)) for value in payload.get("posting_ids") or []]
    predicate = proposal_version_predicate(db.get_bind().dialect.name, legacy=True)
    statement = (
        select(JobPosting)
        .where(predicate)
        .order_by(JobPosting.created_at, JobPosting.id)
        .limit(limit)
    )
    if posting_ids:
        statement = statement.where(JobPosting.id.in_(posting_ids))
    rows = list((await db.execute(statement)).scalars().all())

    regenerated = cleared = skipped = failed = 0
    for index, posting in enumerate(rows):
        posting_id = posting.id
        if cancelled is not None and await cancelled():
            break
        if progress is not None:
            await progress(
                int(10 + (index / max(len(rows), 1)) * 80),
                f"backfill {index + 1}/{len(rows)}",
            )
        try:
            if posting.mapping_method is not None or posting.status in TERMINAL_STATUSES:
                await _clear(db, posting, "mapped")
                cleared += 1
                continue
            if not await job_proposals_enabled(db):
                await _clear(db, posting, "disabled")
                cleared += 1
                continue
            extract = posting.extract or {}
            skills = [
                skill
                for skill in extract.get("skills") or []
                if isinstance(skill, dict) and (skill.get("skill_key") or skill.get("raw_label"))
            ]
            if not str(extract.get("title_norm") or "").strip() or len(skills) < (
                MIN_PROPOSAL_SKILLS
            ):
                await _clear(db, posting, "short_extract")
                cleared += 1
                continue

            await _clear(db, posting, "regenerating")
            await db.commit()
            outcome = await redecide_and_propose(
                db, posting, run_id=run_id, refresh=True, proposal_event="regenerated"
            )
            proposal = outcome.get("proposal") or {}
            if outcome.get("mapping_method") is not None:
                cleared += 1
            elif proposal.get("status") == "stored":
                regenerated += 1
            elif proposal.get("status") == "failed":
                failed += 1
            else:
                cleared += 1
        except Exception:
            await db.rollback()
            failed += 1
            logger.warning("job proposal backfill failed for %s", posting_id, exc_info=True)

    result = {
        "regenerated": regenerated,
        "cleared": cleared,
        "skipped": skipped,
        "failed": failed,
    }
    if progress is not None:
        await progress(100, "backfill complete")
    if failed and regenerated == 0 and cleared == 0:
        raise RuntimeError(
            f"job proposal backfill failed for all selected rows ({failed}); see the job log"
        )
    return result


async def _clear(db: AsyncSession, posting: JobPosting, reason: str) -> None:
    await clear_job_proposal(
        db,
        posting,
        reason=reason,
        actor_ref={"trigger": "job_proposal_backfill"},
    )
    await db.commit()


async def _queued_backfill(db: AsyncSession) -> BackgroundJob | None:
    rows = await db.execute(
        select(BackgroundJob).where(
            BackgroundJob.job_type == BackgroundJobType.JOB_PROPOSAL_BACKFILL.value,
            BackgroundJob.status.in_(
                [BackgroundJobStatus.QUEUED.value, BackgroundJobStatus.RUNNING.value]
            ),
        )
    )
    return rows.scalars().first()


async def enqueue_job_proposal_backfill(
    db: AsyncSession,
    *,
    limit: int = BACKFILL_LIMIT_DEFAULT,
    posting_ids: list[uuid.UUID] | None = None,
) -> tuple[BackgroundJob, bool]:
    """Enqueue one backfill run, reusing a queued/running one.

    Returns ``(job, created)``; the explicit singleton guard exists because
    the queue has no structural dedupe for differing payloads.
    """
    existing = await _queued_backfill(db)
    if existing is not None:
        return existing, False
    from app.services.job_worker import enqueue

    payload = {
        "limit": max(1, min(int(limit), BACKFILL_LIMIT_MAX)),
        "posting_ids": [str(value) for value in posting_ids or []],
    }
    job = await enqueue(db, BackgroundJobType.JOB_PROPOSAL_BACKFILL.value, payload)
    return job, True


async def enqueue_first_boot_backfill(db: AsyncSession) -> BackgroundJob | None:
    """Run once after the change: enqueue when legacy v1 rows exist."""
    setting = (
        (await db.execute(select(AppSetting).where(AppSetting.key == FIRST_BOOT_MARKER)))
        .scalars()
        .first()
    )
    if setting is not None and (setting.value or {}).get("done"):
        return None
    if await legacy_proposal_count(db) == 0:
        if setting is None:
            db.add(AppSetting(key=FIRST_BOOT_MARKER, value={"done": True}))
        else:
            setting.value = {"done": True}
        await db.commit()
        return None
    existing = await _queued_backfill(db)
    job = existing
    if job is None:
        job, _created = await enqueue_job_proposal_backfill(db)
    if setting is None:
        db.add(AppSetting(key=FIRST_BOOT_MARKER, value={"done": True}))
    else:
        setting.value = {"done": True}
        flag_modified(setting, "value")
    await db.commit()
    return job


__all__ = [
    "BACKFILL_LIMIT_DEFAULT",
    "BACKFILL_LIMIT_MAX",
    "FIRST_BOOT_MARKER",
    "enqueue_first_boot_backfill",
    "enqueue_job_proposal_backfill",
    "run_job_proposal_backfill",
]
