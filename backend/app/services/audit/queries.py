"""Cross-stream audit & monitoring reads (plan 151).

Server-side aggregation over the append-only ledgers (``ai_generations``,
``audit_events``, ``background_jobs``, ``schedules``) — the dashboard never
charts raw rows client-side. Time bucketing is dialect-aware: the desktop
profile runs SQLite (``strftime``), web runs PostgreSQL (``date_trunc``).

Read-only by design: every writer keeps its own seam (the AI gateway, the
auth-kit sink, the job worker, the scheduler).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_model import AIGeneration
from app.models.background_job_model import BackgroundJob
from app.models.identity_model import AuditEvent
from app.models.schedule_model import Schedule
from app.models.user_model import User

WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

BUCKETS: dict[str, str] = {"24h": "hour", "7d": "day", "30d": "day"}

FAILURES_LIMIT = 8


def window_bounds(window: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """(start, prev_start) for a preset window — UTC aware."""
    span = WINDOWS[window]
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return current - span, current - span * 2


def _bucket_expr(dialect_name: str, column: Any, bucket: str) -> Any:
    if dialect_name == "postgresql":
        return func.date_trunc(bucket, column)
    fmt = "%Y-%m-%dT%H:00:00" if bucket == "hour" else "%Y-%m-%d"
    return func.strftime(fmt, column)


async def _ai_window_stats(
    db: AsyncSession, start: datetime, end: datetime | None = None
) -> dict[str, Any]:
    conditions = [AIGeneration.created_at >= start]
    if end is not None:
        conditions.append(AIGeneration.created_at < end)
    row = (
        await db.execute(
            select(
                func.count(AIGeneration.id),
                func.sum(case((AIGeneration.status == "error", 1), else_=0)),
                func.coalesce(func.sum(AIGeneration.tokens_in), 0),
                func.coalesce(func.sum(AIGeneration.tokens_out), 0),
                func.avg(AIGeneration.latency_ms),
                func.max(AIGeneration.latency_ms),
            ).where(*conditions)
        )
    ).one()
    calls = int(row[0] or 0)
    errors = int(row[1] or 0)
    return {
        "calls": calls,
        "errors": errors,
        "error_rate": round(errors / calls, 4) if calls else 0.0,
        "tokens_in": int(row[2] or 0),
        "tokens_out": int(row[3] or 0),
        "avg_latency_ms": round(float(row[4]), 1) if row[4] is not None else None,
        "max_latency_ms": round(float(row[5]), 1) if row[5] is not None else None,
    }


async def overview(db: AsyncSession, window: str) -> dict[str, Any]:
    """One round trip of dashboard KPIs + the recent-failure feed."""
    start, prev_start = window_bounds(window)
    current = await _ai_window_stats(db, start)
    previous = await _ai_window_stats(db, prev_start, start)

    job_rows = (
        await db.execute(
            select(BackgroundJob.status, func.count(BackgroundJob.id))
            .where(BackgroundJob.created_at >= start)
            .group_by(BackgroundJob.status)
        )
    ).all()
    jobs = {status: int(count) for status, count in job_rows}

    schedules_failing = (
        await db.execute(
            select(func.count(Schedule.id)).where(
                Schedule.enabled.is_(True), Schedule.consecutive_failures > 0
            )
        )
    ).scalar() or 0

    auth_total = (
        await db.execute(select(func.count(AuditEvent.id)).where(AuditEvent.created_at >= start))
    ).scalar() or 0
    auth_denied = (
        await db.execute(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.created_at >= start,
                AuditEvent.outcome != "ok",
            )
        )
    ).scalar() or 0

    failures: list[dict[str, Any]] = []

    ai_failures = (
        await db.execute(
            select(AIGeneration)
            .where(AIGeneration.status == "error", AIGeneration.created_at >= start)
            .order_by(AIGeneration.created_at.desc())
            .limit(FAILURES_LIMIT)
        )
    ).scalars()
    for row in ai_failures:
        failures.append(
            {
                "stream": "ai",
                "title": row.task_type,
                "detail": (row.error or "")[:200],
                "occurred_at": row.created_at,
            }
        )

    job_failures = (
        await db.execute(
            select(BackgroundJob)
            .where(BackgroundJob.status == "failed", BackgroundJob.created_at >= start)
            .order_by(BackgroundJob.created_at.desc())
            .limit(FAILURES_LIMIT)
        )
    ).scalars()
    for row in job_failures:
        failures.append(
            {
                "stream": "job",
                "title": row.job_type,
                "detail": (row.error or "")[:200],
                "occurred_at": row.created_at,
            }
        )

    auth_failures = (
        await db.execute(
            select(AuditEvent)
            .where(AuditEvent.outcome != "ok", AuditEvent.created_at >= start)
            .order_by(AuditEvent.created_at.desc())
            .limit(FAILURES_LIMIT)
        )
    ).scalars()
    for row in auth_failures:
        failures.append(
            {
                "stream": "auth",
                "title": row.action,
                "detail": row.resource[:200],
                "occurred_at": row.created_at,
            }
        )

    failures.sort(key=lambda item: item["occurred_at"], reverse=True)

    return {
        "window": window,
        "ai": {**current, "prev_calls": previous["calls"], "prev_errors": previous["errors"]},
        "jobs": {
            "failed": jobs.get("failed", 0),
            "running": jobs.get("running", 0),
            "queued": jobs.get("queued", 0),
        },
        "schedules": {"failing": int(schedules_failing)},
        "auth": {"events": int(auth_total), "denied": int(auth_denied)},
        "recent_failures": failures[:FAILURES_LIMIT],
    }


def _bucket_key(value: Any, bucket: str) -> str:
    """Canonical text key for a bucket label — datetime (Postgres
    ``date_trunc``) or text (SQLite ``strftime``) both normalize to the
    same `YYYY-MM-DDTHH:00:00` / `YYYY-MM-DD` form."""
    if isinstance(value, datetime):
        return _key_for(value, bucket)
    return str(value).split("+")[0]


def _key_for(moment: datetime, bucket: str) -> str:
    if bucket == "hour":
        return moment.strftime("%Y-%m-%dT%H:00:00")
    return moment.strftime("%Y-%m-%d")


async def timeseries(db: AsyncSession, window: str) -> dict[str, Any]:
    """Time-bucketed call/error/token series for the volume chart,
    zero-filled across the whole window so sparse activity does not
    compress the timeline."""
    now = datetime.now(UTC)
    start, _ = window_bounds(window, now)
    bucket = BUCKETS[window]
    bucket_expr = _bucket_expr(db.get_bind().dialect.name, AIGeneration.created_at, bucket)
    rows = (
        await db.execute(
            select(
                bucket_expr.label("bucket"),
                func.count(AIGeneration.id),
                func.sum(case((AIGeneration.status == "error", 1), else_=0)),
                func.coalesce(func.sum(AIGeneration.tokens_in), 0),
                func.coalesce(func.sum(AIGeneration.tokens_out), 0),
            )
            .where(AIGeneration.created_at >= start)
            .group_by(bucket_expr)
            .order_by(bucket_expr)
        )
    ).all()
    by_key = {
        _bucket_key(row[0], bucket): {
            "calls": int(row[1] or 0),
            "errors": int(row[2] or 0),
            "tokens_in": int(row[3] or 0),
            "tokens_out": int(row[4] or 0),
        }
        for row in rows
    }

    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    cursor = start.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        cursor = cursor.replace(hour=0)
    points: list[dict[str, Any]] = []
    while cursor <= now:
        key = _key_for(cursor, bucket)
        point = by_key.pop(
            key, {"calls": 0, "errors": 0, "tokens_in": 0, "tokens_out": 0}
        )
        points.append({"bucket": key, **point})
        cursor += step
    for key in sorted(by_key):
        points.append({"bucket": key, **by_key[key]})
    points.sort(key=lambda point: point["bucket"])

    return {
        "window": window,
        "bucket": bucket,
        "points": points,
    }


def _actor_join_clause() -> Any:
    """Actor↔user join that works on both dialects: SQLite stores Uuid as
    32-char hex (no hyphens) while PostgreSQL casts to hyphenated text, so
    both sides are normalized by stripping hyphens."""
    return func.replace(cast(User.id, String), "-", "") == func.replace(AuditEvent.actor, "-", "")


def _like_needle(term: str) -> str:
    """Escape LIKE wildcards so a literal `%`/`_` in user input can not
    silently widen the match."""
    escaped = term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped.lower()}%"


async def breakdown(
    db: AsyncSession, dimension: str, window: str, limit: int = 20
) -> dict[str, Any]:
    """Per-key call/error/token splits — the source for both the category
    chart and the facet-driven filter options."""
    start, _ = window_bounds(window)
    column = {
        "task": AIGeneration.task_type,
        "provider": AIGeneration.provider,
    }[dimension]
    rows = (
        await db.execute(
            select(
                column,
                func.count(AIGeneration.id),
                func.sum(case((AIGeneration.status == "error", 1), else_=0)),
                func.coalesce(func.sum(AIGeneration.tokens_in), 0),
                func.coalesce(func.sum(AIGeneration.tokens_out), 0),
            )
            .where(AIGeneration.created_at >= start)
            .group_by(column)
            .order_by(func.count(AIGeneration.id).desc())
            .limit(limit)
        )
    ).all()
    return {
        "dimension": dimension,
        "window": window,
        "rows": [
            {
                "key": key,
                "calls": int(calls or 0),
                "errors": int(errors or 0),
                "tokens_in": int(tokens_in or 0),
                "tokens_out": int(tokens_out or 0),
            }
            for key, calls, errors, tokens_in, tokens_out in rows
        ],
    }


async def events(
    db: AsyncSession,
    window: str,
    group: str = "all",
    outcome: str | None = None,
    actor: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """Filtered ``audit_events`` rows with a best-effort actor email —
    the identity trail's first read surface (plan 151 D5)."""
    start, _ = window_bounds(window)
    conditions = [AuditEvent.created_at >= start]
    if group == "auth":
        conditions.append(AuditEvent.action.like("auth.%"))
    elif group == "admin":
        conditions.append(AuditEvent.action.like("admin.%"))
    if outcome:
        conditions.append(AuditEvent.outcome == outcome)
    if actor:
        needle = _like_needle(actor)
        conditions.append(
            or_(
                func.lower(AuditEvent.actor).like(needle, escape="\\"),
                func.lower(User.email).like(needle, escape="\\"),
            )
        )

    total = (
        await db.execute(
            select(func.count(AuditEvent.id))
            .outerjoin(User, _actor_join_clause())
            .where(*conditions)
        )
    ).scalar() or 0
    joined = select(AuditEvent, User.email).outerjoin(User, _actor_join_clause())
    rows = (
        await db.execute(
            joined.where(*conditions)
            .order_by(AuditEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = [
        {
            "id": event.id,
            "action": event.action,
            "actor": event.actor,
            "actor_email": email,
            "resource": event.resource,
            "outcome": event.outcome,
            "created_at": event.created_at,
        }
        for event, email in rows
    ]
    return int(total), items


async def generations(
    db: AsyncSession,
    *,
    task: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    status: str | None = None,
    user_id: str | None = None,
    run_id: str | None = None,
    tier: str | None = None,
    window: str | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[AIGeneration]]:
    """The AI ledger with the full filter matrix (plan 151 D7)."""
    conditions = []
    if task:
        conditions.append(AIGeneration.task_type == task)
    if provider:
        conditions.append(AIGeneration.provider == provider)
    if model:
        conditions.append(AIGeneration.model == model)
    if status:
        conditions.append(AIGeneration.status == status)
    if user_id:
        conditions.append(AIGeneration.user_id == user_id)
    if run_id:
        conditions.append(AIGeneration.run_id == run_id)
    if tier:
        conditions.append(AIGeneration.task_tier == tier)
    if window:
        start, _ = window_bounds(window)
        conditions.append(AIGeneration.created_at >= start)
    if query:
        needle = _like_needle(query)
        conditions.append(
            func.lower(AIGeneration.prompt).like(needle, escape="\\")
            | func.lower(AIGeneration.error).like(needle, escape="\\")
        )

    count_stmt = select(func.count(AIGeneration.id))
    list_stmt = select(AIGeneration)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
        list_stmt = list_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0
    rows = (
        (
            await db.execute(
                list_stmt.order_by(AIGeneration.created_at.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return int(total), list(rows)
