"""Runtime idempotency, the single-active-run lock and the stall reaper (plan 51 Q1b).

The migration added the columns and partial unique indexes; this module is
the runtime that allocates them:

* every mutating retrieval action carries an ``Idempotency-Key`` scoped to
  ``(job_type, key)`` with a 24 hour replay window. Reusing a key with the
  same request returns the original run; reusing it with a different
  request is a 409.
* bulk runs (reconcile, maintenance, cutover evaluations) hold
  ``lock_key = vector_space:<space_id>``. The partial unique index over
  ``queued``/``running`` is the database-level one-active-run invariant, so
  two concurrent admins cannot both start work on one space.
* a periodic reaper flips a ``running`` vector row whose heartbeat is older
  than the contract's stale window to ``failed`` — releasing the lock and
  recording ``vector.run.stalled`` — so a crashed process no longer blocks
  a space until the next restart.

Only retrieval job types are touched; the generic :func:`app.services.
job_worker.enqueue` contract is unchanged for every other job family.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus, BackgroundJobType
from app.models.identity_model import AuditEvent
from app.storage import retrieval_ops as ops

logger = logging.getLogger(__name__)

#: The bulk-run job types that carry the one-active-run lock. A single-document
#: ``vector_index`` write is intentionally not serialized: the writer enqueues
#: one per changed source row, and serializing those would drop index updates.
LOCKED_JOB_TYPES = (
    BackgroundJobType.VECTOR_RECONCILE.value,
    BackgroundJobType.VECTOR_MAINTENANCE.value,
    BackgroundJobType.VECTOR_CUTOVER.value,
)

#: Every VECTOR_* row the stall reaper owns (a crashed index write is failed
#: too, even though it holds no space lock).
REAPABLE_JOB_TYPES = (
    BackgroundJobType.VECTOR_INDEX.value,
    *LOCKED_JOB_TYPES,
)

ACTIVE_STATUSES = (
    BackgroundJobStatus.QUEUED.value,
    BackgroundJobStatus.RUNNING.value,
)

STALE_ERROR = f"stalled: no heartbeat for {ops.HEARTBEAT_STALE_SECONDS // 60}m"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def replay_cutoff(now: datetime | None = None) -> datetime:
    """The 24 hour idempotency replay window start."""
    return (now or _utcnow()) - timedelta(seconds=ops.IDEMPOTENCY_TTL_SECONDS)


def validate_key(value: Any) -> str:
    """Validate an idempotency key through the family contract."""
    try:
        return ops.validate_idempotency_key(value)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def lock_key_for(space_id: str | uuid.UUID) -> str:
    """The per-space lock key (``vector_space:<space_id>``)."""
    return ops.run_lock_key(str(space_id))


def _same_request(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """True when two action payloads describe the same request.

    Both sides are built deterministically by the action seam, so a direct
    comparison is the honest replay test; a list/dict is compared by value
    after JSON normalization.
    """
    import json

    def _canonical(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    return _canonical(left or {}) == _canonical(right or {})


async def find_replay(
    db: AsyncSession, *, job_type: str, idempotency_key: str
) -> BackgroundJob | None:
    """The request's previous run inside the 24h window (any terminal state)."""
    row = await db.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.job_type == job_type,
            BackgroundJob.idempotency_key == idempotency_key,
            BackgroundJob.created_at >= replay_cutoff(),
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    return row.first()


async def active_run_for_space(db: AsyncSession, space_id: str | uuid.UUID) -> BackgroundJob | None:
    """The queued/running bulk run holding this space's lock, if any."""
    row = await db.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.lock_key == lock_key_for(space_id),
            BackgroundJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(BackgroundJob.created_at)
        .limit(1)
    )
    return row.first()


def _conflict_for_active(space_id: str, active: BackgroundJob) -> ConflictError:
    name = (active.payload or {}).get("name")
    label = f" ({name})" if name else ""
    return ConflictError(
        f"space {space_id}{label} already has an active retrieval run {active.id} "
        f"({active.job_type}, {active.status}); wait for it to finish or cancel it"
    )


async def _replay_or_conflict(
    db: AsyncSession, *, job_type: str, payload: dict[str, Any], key: str
) -> BackgroundJob | None:
    existing = await find_replay(db, job_type=job_type, idempotency_key=key)
    if existing is None:
        return None
    if not _same_request(existing.payload or {}, payload):
        raise ConflictError(
            "this Idempotency-Key was already used with a different request; "
            "use a new key for a new action"
        )
    return existing


async def _lock_or_conflict(db: AsyncSession, *, space_id: str | uuid.UUID | None) -> str | None:
    if space_id is None:
        return None
    lock_key = lock_key_for(space_id)
    active = await active_run_for_space(db, space_id)
    if active is not None:
        # A same-key replay was handled before this point.
        raise _conflict_for_active(str(space_id), active)
    return lock_key


async def _collision_fallback(
    db: AsyncSession,
    *,
    job_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    space_id: str | uuid.UUID | None,
) -> BackgroundJob | None:
    """Resolve an IntegrityError to a replay or a clear lock conflict."""
    replay = await _replay_or_conflict(db, job_type=job_type, payload=payload, key=idempotency_key)
    if replay is not None:
        return replay
    if space_id is not None:
        active = await active_run_for_space(db, space_id)
        if active is not None:
            raise _conflict_for_active(str(space_id), active)
    raise ConflictError("a concurrent retrieval action collided on the same key or space; retry")


async def enqueue_retrieval_job(
    db: AsyncSession,
    *,
    job_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    user_id: uuid.UUID | None = None,
    space_id: str | uuid.UUID | None = None,
    lock: bool = True,
    max_attempts: int = 2,
    audit: AuditEvent | None = None,
) -> tuple[BackgroundJob, bool]:
    """Queue a retrieval run with replay + single-active-run semantics.

    Returns ``(job, deduplicated)``. A replay returns the original row and
    never enqueues a second run; a lock conflict raises ``ConflictError``
    (409) instead of silently joining another run. ``audit`` is written in
    the same transaction as the new row (and ignored on a replay).
    """
    key = validate_key(idempotency_key)
    replay = await _replay_or_conflict(db, job_type=job_type, payload=payload, key=key)
    if replay is not None:
        return replay, True

    lock_key = await _lock_or_conflict(db, space_id=space_id) if lock else None
    job = BackgroundJob(
        user_id=user_id,
        job_type=job_type,
        status=BackgroundJobStatus.QUEUED.value,
        payload=payload,
        max_attempts=max_attempts,
        idempotency_key=key,
        lock_key=lock_key,
    )
    db.add(job)
    if audit is not None:
        db.add(audit)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await _collision_fallback(
            db,
            job_type=job_type,
            payload=payload,
            idempotency_key=key,
            space_id=space_id if lock else None,
        )
        if replay is not None:
            return replay, True
        raise
    await db.refresh(job)
    return job, False


async def begin_action_run(
    db: AsyncSession,
    *,
    job_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    user_id: uuid.UUID | None = None,
    space_id: str | uuid.UUID | None = None,
    lock: bool = True,
) -> tuple[BackgroundJob, bool]:
    """Open a synchronous action run (status ``running``) and hold its lock.

    The lifecycle/compare actions execute inside the request; the row is the
    request-replay record, the space lock while it runs and the persisted
    result afterwards. A replay returns the original row untouched.
    """
    key = validate_key(idempotency_key)
    replay = await _replay_or_conflict(db, job_type=job_type, payload=payload, key=key)
    if replay is not None:
        return replay, True

    lock_key = await _lock_or_conflict(db, space_id=space_id) if lock else None
    now = _utcnow()
    job = BackgroundJob(
        user_id=user_id,
        job_type=job_type,
        status=BackgroundJobStatus.RUNNING.value,
        payload=payload,
        progress=5,
        stage="started",
        max_attempts=1,
        idempotency_key=key,
        lock_key=lock_key,
        claimed_at=now,
        heartbeat_at=now,
    )
    db.add(job)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await _collision_fallback(
            db,
            job_type=job_type,
            payload=payload,
            idempotency_key=key,
            space_id=space_id if lock else None,
        )
        if replay is not None:
            return replay, True
        raise
    await db.refresh(job)
    return job, False


def _add_audit(db: AsyncSession, audit: AuditEvent | Sequence[AuditEvent] | None) -> None:
    if audit is None:
        return
    if isinstance(audit, AuditEvent):
        db.add(audit)
        return
    for event in audit:
        db.add(event)


async def finish_action_run(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    result: dict[str, Any],
    audit: AuditEvent | Sequence[AuditEvent] | None = None,
) -> BackgroundJob:
    """Commit a successful synchronous action and its audit row(s) together."""
    now = _utcnow()
    job.status = BackgroundJobStatus.SUCCEEDED.value
    job.progress = 100
    job.stage = "done"
    job.result = result
    job.finished_at = now
    job.heartbeat_at = now
    job.lock_key = None
    job.updated_at = now
    _add_audit(db, audit)
    await db.commit()
    await db.refresh(job)
    return job


async def fail_action_run(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    error: str,
    result: dict[str, Any] | None = None,
    audit: AuditEvent | Sequence[AuditEvent] | None = None,
) -> BackgroundJob:
    """Commit a refused/failed synchronous action (the lock is released)."""
    now = _utcnow()
    job.status = BackgroundJobStatus.FAILED.value
    job.stage = "failed"
    job.error = error[:500]
    if result is not None:
        job.result = result
    job.finished_at = now
    job.heartbeat_at = now
    job.lock_key = None
    job.updated_at = now
    _add_audit(db, audit)
    await db.commit()
    await db.refresh(job)
    return job


def stalled_audit(job: BackgroundJob, *, now: datetime | None = None) -> AuditEvent:
    """The ``vector.run.stalled`` audit row for one reaped run."""
    return AuditEvent(
        actor="system",
        action="vector.run.stalled",
        resource=f"run:{job.id}",
        outcome="error",
        created_at=now or _utcnow(),
    )


async def reap_stale_runs(db: AsyncSession, *, now: datetime | None = None) -> list[BackgroundJob]:
    """Fail running VECTOR_* rows whose heartbeat outlived the stale window.

    A row with no heartbeat falls back to ``claimed_at`` (a worker that died
    before its first progress tick). Terminal rows are untouched, and a
    reaped row releases its lock because ``failed`` is outside the partial
    unique index. Each reap writes ``vector.run.stalled``.
    """
    moment = now or _utcnow()
    cutoff = moment - timedelta(seconds=ops.HEARTBEAT_STALE_SECONDS)
    rows = list(
        await db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.job_type.in_(REAPABLE_JOB_TYPES),
                BackgroundJob.status == BackgroundJobStatus.RUNNING.value,
            )
        )
    )
    reaped: list[BackgroundJob] = []
    for job in rows:
        beat = _as_utc(job.heartbeat_at) or _as_utc(job.claimed_at) or _as_utc(job.created_at)
        if beat is None or beat >= cutoff:
            continue
        job.status = BackgroundJobStatus.FAILED.value
        job.stage = "stalled"
        job.error = STALE_ERROR
        job.finished_at = moment
        job.lock_key = None
        job.updated_at = moment
        db.add(stalled_audit(job, now=moment))
        reaped.append(job)
    if reaped:
        await db.commit()
        logger.warning("Reaped %d stale vector run(s)", len(reaped))
    return reaped


async def reaper_loop(interval: float = float(ops.REAPER_INTERVAL_SECONDS)) -> None:
    """Periodic stale-heartbeat sweep (started beside the job workers)."""
    import asyncio

    from app.core.database import AsyncSessionLocal

    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as session:
                await reap_stale_runs(session)
        except asyncio.CancelledError:
            raise
        except Exception:  # a reaper failure must never kill the worker pool
            logger.exception("stale vector-run reaper failed")


__all__ = [
    "ACTIVE_STATUSES",
    "LOCKED_JOB_TYPES",
    "REAPABLE_JOB_TYPES",
    "STALE_ERROR",
    "active_run_for_space",
    "begin_action_run",
    "enqueue_retrieval_job",
    "fail_action_run",
    "find_replay",
    "finish_action_run",
    "lock_key_for",
    "reap_stale_runs",
    "reaper_loop",
    "replay_cutoff",
    "stalled_audit",
    "validate_key",
]
