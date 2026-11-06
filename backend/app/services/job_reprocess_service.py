"""Bulk reprocessing of terminally failed background jobs (plan 184).

A failed job is never mutated back into the queue: requeue appends a
FRESH ``BackgroundJob`` row (same type/payload/user, fresh attempts)
carrying ``requeue_of`` = the old id, while the old row keeps ``failed``
and gains ``result.requeued_as`` — both directions of the chain stay
queryable and the failure record stays intact. Mechanics: the preview
scan is bounded (``ORDER BY created_at DESC LIMIT 1000``, the overflow
reported as ``truncated``), grouping happens in Python by
``(job_type, error family)`` where the family is the whitespace-collapsed
first line of the error truncated at 80 chars, the dedupe guard compares
payloads structurally (``dict ==`` — never SQL payload equality, which
would fork between Postgres JSONB and SQLite JSON-over-TEXT) against the
bounded queued/running twins of the same type, the cap is 200 requeues
per confirmed action with the overflow reported, payload-ignoring global
sweeps collapse to ONE requeue per window, and a single bulk action runs
at a time via an ``app_settings`` guard row flipped by conditional UPDATE
(rowcount arbitrates — the queue's own claim pattern, dialect-safe); the
claim carries its timestamp and a claim older than ``LOCK_STALE_SECONDS``
is re-claimed by the same UPDATE, so a guard stranded by a mid-requeue
failure (the session is in pending-rollback state and the ``finally``
release cannot commit) never blocks a later requeue forever.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.models.background_job_model import BackgroundJob
from app.models.settings_model import AppSetting
from app.services.analytics.time_buckets import range_bounds

CAP = 200
SCAN_LIMIT = 1000
ERROR_FAMILY_MAX = 80
LOCK_KEY = "background_jobs.reprocess_lock"
LOCK_STALE_SECONDS = 600

FULL_RERUN_TYPES = frozenset({"autopilot_run", "digest", "radar_digest", "smart_digest"})
SWEEP_TYPES = frozenset(
    {
        "query_curator",
        "proposal_sweep",
        "followup_sweep",
        "checkpoint_prune",
        "market_history_capture",
    }
)

ACTIVE_STATUSES = ("queued", "running")


def error_family(error: str | None) -> str:
    """The display grouping family: first line, whitespace-collapsed, ≤80 chars."""
    first_line = (error or "").strip().splitlines()
    collapsed = " ".join(first_line[0].split()) if first_line else ""
    return (collapsed[:ERROR_FAMILY_MAX] or "unknown error").strip()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JobReprocessService:
    """Preview and bulk-requeue terminally failed jobs (admin surface)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def preview(
        self,
        *,
        job_type: str | None = None,
        user_id: uuid.UUID | None = None,
        window: str | None = "24h",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        job_ids: Sequence[uuid.UUID] | None = None,
    ) -> dict[str, Any]:
        """Grouped failure counts with the dedupe/cap estimates a requeue
        would apply — read-only, mutates nothing."""
        rows = await self._scan(job_type, user_id, window, date_from, date_to, job_ids)
        twins = await self._active_payload_twins({row.job_type for row in rows})

        by_type: dict[str, list[BackgroundJob]] = {}
        for row in rows:
            by_type.setdefault(row.job_type, []).append(row)

        groups: list[dict[str, Any]] = []
        skipped_dup_preview = 0
        ranked = sorted(by_type.items(), key=lambda item: (-len(item[1]), item[0]))
        for type_name, members in ranked:
            families: Counter[str] = Counter(error_family(member.error) for member in members)
            eligible = sum(1 for member in members if not self._is_dup(member, twins))
            est = min(eligible, 1) if type_name in SWEEP_TYPES else eligible
            groups.append(
                {
                    "job_type": type_name,
                    "window_count": len(members),
                    "top_error": families.most_common(1)[0][0],
                    "est_jobs": est,
                    "full_rerun": type_name in FULL_RERUN_TYPES,
                    "sweep": type_name in SWEEP_TYPES,
                }
            )
            skipped_dup_preview += len(members) - eligible

        total = (
            await self.db.execute(
                select(func.count())
                .select_from(BackgroundJob)
                .where(
                    *self._scope_conditions(job_type, user_id, window, date_from, date_to, job_ids)
                )
            )
        ).scalar() or 0
        return {
            "groups": groups,
            "cap": CAP,
            "total_failed": int(total),
            "truncated": max(int(total) - SCAN_LIMIT, 0),
            "skipped_dup_preview": skipped_dup_preview,
        }

    async def requeue(
        self,
        *,
        job_type: str | None = None,
        user_id: uuid.UUID | None = None,
        window: str | None = "24h",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        job_ids: Sequence[uuid.UUID] | None = None,
    ) -> dict[str, Any]:
        """Requeue failed jobs as fresh rows; per-job outcomes with the
        dedupe/cap/sweep verdicts. Stamp-old + insert-new share ONE
        transaction; the singleton guard is released in ``finally``."""
        await self._acquire_lock()
        try:
            rows = await self._scan(job_type, user_id, window, date_from, date_to, job_ids)
            twins = await self._active_payload_twins({row.job_type for row in rows})

            requeued = 0
            skipped_dup = 0
            skipped_cap = 0
            collapsed = 0
            swept: set[str] = set()
            items: list[dict[str, Any]] = []
            for row in rows:
                if self._is_dup(row, twins):
                    skipped_dup += 1
                    items.append({"job_id": row.id, "outcome": "skipped_dup", "new_job_id": None})
                    continue
                if row.job_type in SWEEP_TYPES and not job_ids:
                    if row.job_type in swept:
                        collapsed += 1
                        continue
                    swept.add(row.job_type)
                if requeued >= CAP:
                    skipped_cap += 1
                    items.append({"job_id": row.id, "outcome": "skipped_cap", "new_job_id": None})
                    continue
                clone = BackgroundJob(
                    user_id=row.user_id,
                    job_type=row.job_type,
                    payload=dict(row.payload or {}),
                    max_attempts=row.max_attempts,
                    requeue_of=row.id,
                )
                self.db.add(clone)
                await self.db.flush()
                row.result = {**(row.result or {}), "requeued_as": str(clone.id)}
                requeued += 1
                items.append({"job_id": row.id, "outcome": "requeued", "new_job_id": clone.id})
            await self.db.commit()
            return {
                "requeued": requeued,
                "skipped_dup": skipped_dup,
                "skipped_cap": skipped_cap,
                "collapsed": collapsed,
                "cap": CAP,
                "items": items,
            }
        finally:
            await self._release_lock()

    def _scope_conditions(
        self,
        job_type: str | None,
        user_id: uuid.UUID | None,
        window: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        job_ids: Sequence[uuid.UUID] | None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [
            BackgroundJob.status == "failed",
            BackgroundJob.attempts >= BackgroundJob.max_attempts,
        ]
        if job_type:
            conditions.append(BackgroundJob.job_type == job_type)
        if user_id is not None:
            conditions.append(BackgroundJob.user_id == user_id)
        if window or date_from is not None:
            start, _, end = range_bounds(window, date_from, date_to)
            conditions.append(BackgroundJob.created_at >= start)
            if end is not None:
                conditions.append(BackgroundJob.created_at < end)
        if job_ids:
            conditions.append(BackgroundJob.id.in_(job_ids))
        return conditions

    async def _scan(
        self,
        job_type: str | None,
        user_id: uuid.UUID | None,
        window: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        job_ids: Sequence[uuid.UUID] | None,
    ) -> list[BackgroundJob]:
        rows = await self.db.execute(
            select(BackgroundJob)
            .where(*self._scope_conditions(job_type, user_id, window, date_from, date_to, job_ids))
            .order_by(BackgroundJob.created_at.desc())
            .limit(SCAN_LIMIT)
        )
        return list(rows.scalars().all())

    async def _active_payload_twins(self, job_types: set[str]) -> dict[str, list[dict]]:
        if not job_types:
            return {}
        rows = await self.db.execute(
            select(BackgroundJob.job_type, BackgroundJob.payload)
            .where(
                BackgroundJob.job_type.in_(job_types),
                BackgroundJob.status.in_(ACTIVE_STATUSES),
            )
            .order_by(BackgroundJob.created_at.desc())
            .limit(SCAN_LIMIT)
        )
        twins: dict[str, list[dict]] = {}
        for twin_type, payload in rows.all():
            twins.setdefault(str(twin_type), []).append(
                payload if isinstance(payload, dict) else {}
            )
        return twins

    def _is_dup(self, row: BackgroundJob, twins: dict[str, list[dict]]) -> bool:
        payload = row.payload if isinstance(row.payload, dict) else {}
        return any(twin == payload for twin in twins.get(row.job_type, []))

    def _lock_free_clause(self) -> ColumnElement[bool]:
        """The guard row is free when its ``locked`` JSON value is null or
        absent — tested by TYPE, never by key presence (both dialects) —
        or when the claim went stale: a claim older than
        ``LOCK_STALE_SECONDS`` is a stranded release (a failure after a
        bad flush leaves the session in pending-rollback state, so the
        ``finally`` release UPDATE cannot commit) and is re-claimed by
        this very UPDATE."""
        value_col = AppSetting.__table__.c["value"]
        if self.db.get_bind().dialect.name == "postgresql":
            kind = func.jsonb_typeof(value_col.op("->")("locked"))
        else:
            kind = func.json_type(value_col, "$.locked")
        free = func.coalesce(kind, "null") == "null"
        stale = AppSetting.updated_at < _utcnow() - timedelta(seconds=LOCK_STALE_SECONDS)
        return or_(free, stale)

    async def _acquire_lock(self) -> None:
        existing = (
            await self.db.execute(select(AppSetting).where(AppSetting.key == LOCK_KEY))
        ).scalar_one_or_none()
        if existing is None:
            self.db.add(AppSetting(key=LOCK_KEY, value={"locked": None}))
            try:
                await self.db.commit()
            except IntegrityError:
                await self.db.rollback()
        claim_at = _utcnow()
        claim = await self.db.execute(
            update(AppSetting)
            .where(AppSetting.key == LOCK_KEY, self._lock_free_clause())
            .values(
                value={
                    "locked": True,
                    "claimed_at": claim_at.isoformat(),
                    "action": uuid.uuid4().hex,
                },
                updated_at=claim_at,
            )
        )
        await self.db.commit()
        if claim.rowcount == 0:  # type: ignore[attr-defined]
            raise DomainError("A bulk requeue is already running — try again once it finishes")

    async def _release_lock(self) -> None:
        await self.db.execute(
            update(AppSetting)
            .where(AppSetting.key == LOCK_KEY)
            .values(value={"locked": None}, updated_at=_utcnow())
        )
        await self.db.commit()
