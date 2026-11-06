"""One-shot mapping-outcome backfill (plan 205 AD3).

Selects active postings whose typed outcome is still NULL, oldest first,
bounded by ``limit``/``posting_ids``. Each row's outcome derives
deterministically from ``catalog_job_id``/``mapping_method``/
``mapping_signals`` — no AI, no prose parsing. Idempotent: a row that
already carries an outcome is skipped, and re-running converges (the
result reports ``remaining`` so the console can offer the action again).
Terminal postings (expired/hidden) are invisible to the funnel and stay
NULL.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus, BackgroundJobType
from app.models.posting_model import JobPosting
from app.services.postings.mapping_outcome import backfill_postings_outcome

logger = logging.getLogger(__name__)

BACKFILL_LIMIT_DEFAULT = 200
BACKFILL_LIMIT_MAX = 500
ACTIVE_POSTING_STATUSES = ("new", "mapped")


async def legacy_outcome_count(db: AsyncSession) -> int:
    """Active postings without a derived outcome (the overview's legacy number)."""
    rows = await db.execute(
        select(func.count())
        .select_from(JobPosting)
        .where(
            JobPosting.status.in_(ACTIVE_POSTING_STATUSES),
            JobPosting.mapping_outcome_state.is_(None),
        )
    )
    return int(rows.scalar_one())


async def run_mapping_outcome_backfill(
    db: AsyncSession,
    payload: dict,
    *,
    run_id: uuid.UUID | None = None,
    progress=None,
    cancelled=None,
) -> dict:
    """Derive the outcome for up to ``limit`` legacy rows in one transaction."""
    del run_id
    limit = max(1, min(int(payload.get("limit") or BACKFILL_LIMIT_DEFAULT), BACKFILL_LIMIT_MAX))
    posting_ids = [uuid.UUID(str(value)) for value in payload.get("posting_ids") or []]
    statement = (
        select(JobPosting)
        .where(
            JobPosting.status.in_(ACTIVE_POSTING_STATUSES),
            JobPosting.mapping_outcome_state.is_(None),
        )
        .order_by(JobPosting.created_at, JobPosting.id)
        .limit(limit)
    )
    if posting_ids:
        statement = statement.where(JobPosting.id.in_(posting_ids))
    rows = list((await db.execute(statement)).scalars().all())
    if progress is not None:
        await progress(10, f"backfill {len(rows)} postings")
    result = await backfill_postings_outcome(db, rows)
    remaining = await legacy_outcome_count(db)
    if progress is not None:
        await progress(100, "backfill complete")
    return {**result, "remaining": remaining}


async def _queued_backfill(db: AsyncSession) -> BackgroundJob | None:
    rows = await db.execute(
        select(BackgroundJob).where(
            BackgroundJob.job_type == BackgroundJobType.MAPPING_OUTCOME_BACKFILL.value,
            BackgroundJob.status.in_(
                [BackgroundJobStatus.QUEUED.value, BackgroundJobStatus.RUNNING.value]
            ),
        )
    )
    return rows.scalars().first()


async def enqueue_mapping_outcome_backfill(
    db: AsyncSession,
    *,
    limit: int = BACKFILL_LIMIT_DEFAULT,
    posting_ids: list[uuid.UUID] | None = None,
) -> tuple[BackgroundJob, bool]:
    """Enqueue one backfill run, reusing a queued/running one."""
    existing = await _queued_backfill(db)
    if existing is not None:
        return existing, False
    from app.services.job_worker import enqueue

    payload = {
        "limit": max(1, min(int(limit), BACKFILL_LIMIT_MAX)),
        "posting_ids": [str(value) for value in posting_ids or []],
    }
    job = await enqueue(db, BackgroundJobType.MAPPING_OUTCOME_BACKFILL.value, payload)
    return job, True


__all__ = [
    "BACKFILL_LIMIT_DEFAULT",
    "BACKFILL_LIMIT_MAX",
    "enqueue_mapping_outcome_backfill",
    "legacy_outcome_count",
    "run_mapping_outcome_backfill",
]
