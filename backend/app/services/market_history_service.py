"""Demand history: persist periodic market snapshots.

Analytics only — the snapshots feed the trend endpoint/UI and are
never a fit input. Capture is idempotent per
scope per day: re-running upserts today's row.
"""

from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_model import MarketSnapshot
from app.services.growth_service import market_snapshot

SNAPSHOT_DAY_WINDOW = 366


def _scope_fields(
    *, family_key: Optional[str] = None, job_id: Optional[UUID] = None
) -> tuple[str, str, Optional[str], Optional[UUID]]:
    """(scope_kind, scope_key, family_key, job_id) from one scope arg."""
    if family_key is not None and job_id is None:
        return "family", f"family:{family_key}", family_key, None
    if job_id is not None and family_key is None:
        return "job", f"job:{job_id}", None, job_id
    raise ValueError("exactly one of family_key / job_id is required")


def _today(now: datetime) -> date:
    return now.astimezone(timezone.utc).date()


async def capture_scope(
    db: AsyncSession,
    *,
    family_key: Optional[str] = None,
    job_id: Optional[UUID] = None,
    now: Optional[datetime] = None,
) -> MarketSnapshot:
    """Snapshot one scope now; upsert today's row (same-day idempotent)."""

    now = now or datetime.now(timezone.utc)
    scope_kind, scope_key, family_key, job_id = _scope_fields(
        family_key=family_key, job_id=job_id
    )
    payload = await market_snapshot(db, family_key=family_key, job_id=job_id)
    row = (
        (
            await db.execute(
                select(MarketSnapshot).where(
                    MarketSnapshot.scope_kind == scope_kind,
                    MarketSnapshot.scope_key == scope_key,
                    MarketSnapshot.capture_date == _today(now),
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        row = MarketSnapshot(
            scope_kind=scope_kind,
            scope_key=scope_key,
            family_key=family_key,
            job_id=job_id,
            capture_date=_today(now),
            captured_at=now,
        )
        db.add(row)
    row.payload = payload
    row.sample_size = int(payload.get("sample_size") or 0)
    row.thin_sample = bool(payload.get("thin_sample"))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def scopes_with_data(db: AsyncSession) -> list[tuple[str, object]]:
    """Every family key / job id that has live postings to snapshot."""
    from app.models.job_model import Job, JobFamily
    from app.models.posting_model import JobPosting

    rows = await db.execute(
        select(JobFamily.key, Job.id)
        .join(Job, Job.family_id == JobFamily.id)
        .join(JobPosting, JobPosting.catalog_job_id == Job.id)
        .where(JobPosting.status.in_(["mapped", "new"]))
        .group_by(JobFamily.key, Job.id)
    )
    seen_families: set[str] = set()
    scopes: list[tuple[str, object]] = []
    for family_key, job_id in rows.all():
        if family_key not in seen_families:
            seen_families.add(family_key)
            scopes.append(("family", family_key))
        scopes.append(("job", job_id))
    return scopes


async def capture_all(db: AsyncSession, *, limit: int = 500) -> int:
    """Capture every scope with live postings; returns rows written."""
    scopes = (await scopes_with_data(db))[:limit]
    done = 0
    for kind, value in scopes:
        if kind == "family":
            await capture_scope(db, family_key=value)
        else:
            await capture_scope(db, job_id=value)
        done += 1
    return done


async def trend(
    db: AsyncSession,
    *,
    family_key: Optional[str] = None,
    job_id: Optional[UUID] = None,
    limit: int = 60,
) -> list[dict]:
    """Ordered history for one scope, oldest first."""
    _, scope_key, _, _ = _scope_fields(family_key=family_key, job_id=job_id)
    rows = (
        (
            await db.execute(
                select(MarketSnapshot)
                .where(
                    MarketSnapshot.scope_key == scope_key,
                    MarketSnapshot.scope_kind == ("family" if family_key else "job"),
                )
                .order_by(MarketSnapshot.capture_date.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "capture_date": row.capture_date.isoformat(),
            "captured_at": row.captured_at.isoformat(),
            "sample_size": row.sample_size,
            "thin_sample": row.thin_sample,
            "salary_band": (row.payload or {}).get("salary_band"),
            "months": (row.payload or {}).get("months") or [],
        }
        for row in reversed(rows)
    ]
