"""Cross-stream audit & monitoring reads (plans 151-152).

Server-side aggregation over the append-only ledgers (``ai_generations``,
``audit_events``, ``background_jobs``, ``source_runs``, ``posting_changes``,
``skill_changes``, ``schedules``) — the dashboard never charts raw rows
client-side. Time bucketing is dialect-aware: the desktop profile runs
SQLite (``strftime``), web runs PostgreSQL (``date_trunc``).

Every reader accepts a preset ``window`` OR an explicit ``from``/``to``
range (the explicit range wins). Read-only by design: every writer keeps
its own seam (the AI gateway, the auth-kit sink, the job worker, the
scheduler, the journals).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_model import AIGeneration
from app.models.background_job_model import BackgroundJob
from app.models.company_model import CompanyProfile
from app.models.identity_model import AuditEvent
from app.models.job_model import Job
from app.models.posting_model import JobPosting, JobSource, PostingChange, SourceRun
from app.models.schedule_model import Schedule
from app.models.taxonomy_model import SkillChange
from app.models.user_model import User
from app.services.analytics.time_buckets import (
    bucket_expr,
    bucket_key,
    range_bounds,
    zero_filled,
)

WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

BUCKETS: dict[str, str] = {"24h": "hour", "7d": "day", "30d": "day"}

FAILURES_LIMIT = 8
EXPORT_LIMIT = 10_000


def _range_conditions(
    column: Any,
    window: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[Any]:
    start, _, end = range_bounds(window, date_from, date_to)
    conditions = [column >= start]
    if end is not None:
        conditions.append(column < end)
    return conditions


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


async def overview(
    db: AsyncSession,
    window: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """One round trip of dashboard KPIs + the recent-failure feed."""
    start, prev_start, end = range_bounds(window, date_from, date_to)
    upper = [BackgroundJob.created_at < end] if end is not None else []
    current = await _ai_window_stats(db, start, end)
    previous = await _ai_window_stats(db, prev_start, start)

    job_rows = (
        await db.execute(
            select(BackgroundJob.status, func.count(BackgroundJob.id))
            .where(BackgroundJob.created_at >= start, *upper)
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

    auth_conditions = [AuditEvent.created_at >= start]
    if end is not None:
        auth_conditions.append(AuditEvent.created_at < end)
    auth_total = (
        await db.execute(select(func.count(AuditEvent.id)).where(*auth_conditions))
    ).scalar() or 0
    auth_denied = (
        await db.execute(
            select(func.count(AuditEvent.id)).where(*auth_conditions, AuditEvent.outcome != "ok")
        )
    ).scalar() or 0

    failures: list[dict[str, Any]] = []
    ai_conditions = [AIGeneration.status == "error", AIGeneration.created_at >= start]
    if end is not None:
        ai_conditions.append(AIGeneration.created_at < end)
    ai_failures = (
        await db.execute(
            select(AIGeneration)
            .where(*ai_conditions)
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
            .where(BackgroundJob.status == "failed", BackgroundJob.created_at >= start, *upper)
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
            .where(AuditEvent.outcome != "ok", *auth_conditions)
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


async def timeseries(
    db: AsyncSession,
    window: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Time-bucketed call/error/token series for the volume chart,
    zero-filled across the whole window so sparse activity does not
    compress the timeline. Custom ranges bucket hourly up to 48h, then
    daily."""
    start, _, end = range_bounds(window, date_from, date_to)
    span = (end or datetime.now(UTC)) - start
    if date_from is not None:
        bucket = "hour" if span <= timedelta(hours=48) else "day"
    else:
        bucket = BUCKETS.get(window or "24h", "hour")
    stop = end or datetime.now(UTC)
    grouped = bucket_expr(db.get_bind().dialect.name, AIGeneration.created_at, bucket)
    rows = (
        await db.execute(
            select(
                grouped.label("bucket"),
                func.count(AIGeneration.id),
                func.sum(case((AIGeneration.status == "error", 1), else_=0)),
                func.coalesce(func.sum(AIGeneration.tokens_in), 0),
                func.coalesce(func.sum(AIGeneration.tokens_out), 0),
            )
            .where(*_range_conditions(AIGeneration.created_at, window, date_from, date_to))
            .group_by(grouped)
            .order_by(grouped)
        )
    ).all()
    by_key = {
        bucket_key(row[0], bucket): {
            "calls": int(row[1] or 0),
            "errors": int(row[2] or 0),
            "tokens_in": int(row[3] or 0),
            "tokens_out": int(row[4] or 0),
        }
        for row in rows
    }

    points = zero_filled(
        by_key,
        start,
        stop,
        bucket,
        {"calls": 0, "errors": 0, "tokens_in": 0, "tokens_out": 0},
    )

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
    db: AsyncSession,
    dimension: str,
    window: str,
    limit: int = 20,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Per-key call/error/token splits — the source for the category
    chart, the facet-driven filter options and the model-usage view."""
    if dimension == "model":
        provider = AIGeneration.provider
        model = AIGeneration.model
        column = func.concat(provider, "/", model)
        rows = (
            await db.execute(
                select(
                    column,
                    func.count(AIGeneration.id),
                    func.sum(case((AIGeneration.status == "error", 1), else_=0)),
                    func.coalesce(func.sum(AIGeneration.tokens_in), 0),
                    func.coalesce(func.sum(AIGeneration.tokens_out), 0),
                    func.avg(AIGeneration.latency_ms),
                )
                .where(*_range_conditions(AIGeneration.created_at, window, date_from, date_to))
                .group_by(provider, model)
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
                    "avg_latency_ms": round(float(avg or 0), 1) if avg is not None else None,
                }
                for key, calls, errors, tokens_in, tokens_out, avg in rows
            ],
        }
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
            .where(*_range_conditions(AIGeneration.created_at, window, date_from, date_to))
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


async def production(
    db: AsyncSession,
    window: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Content-production throughput (plan 153): what the system *made*
    in the range — postings ingested and processed, skill lifecycle
    events, company profiles created, catalog jobs by status and origin.
    Reads over the domain tables and the two append-only journals."""
    posting_range = _range_conditions(JobPosting.created_at, window, date_from, date_to)
    posting_rows = (
        await db.execute(
            select(JobPosting.status, func.count(JobPosting.id))
            .where(*posting_range)
            .group_by(JobPosting.status)
        )
    ).all()
    by_status = {status: int(count) for status, count in posting_rows}

    items_sum = (
        await db.execute(
            select(func.coalesce(func.sum(SourceRun.items_synced), 0)).where(
                *_range_conditions(SourceRun.started_at, window, date_from, date_to)
            )
        )
    ).scalar() or 0

    activity_rows = (
        await db.execute(
            select(PostingChange.actor_kind, func.count(PostingChange.id))
            .where(*_range_conditions(PostingChange.occurred_at, window, date_from, date_to))
            .group_by(PostingChange.actor_kind)
        )
    ).all()

    skill_rows = (
        await db.execute(
            select(SkillChange.event, func.count(SkillChange.id))
            .where(*_range_conditions(SkillChange.occurred_at, window, date_from, date_to))
            .group_by(SkillChange.event)
        )
    ).all()

    company_range = _range_conditions(CompanyProfile.created_at, window, date_from, date_to)
    company_rows = (
        await db.execute(
            select(CompanyProfile.source, func.count(CompanyProfile.id))
            .where(*company_range)
            .group_by(CompanyProfile.source)
        )
    ).all()
    companies = {source: int(count) for source, count in company_rows}

    job_rows = (
        await db.execute(
            select(Job.status, Job.source, func.count(Job.id))
            .where(*_range_conditions(Job.created_at, window, date_from, date_to))
            .group_by(Job.status, Job.source)
        )
    ).all()
    jobs_by_status: dict[str, int] = {}
    jobs_by_source: dict[str, int] = {}
    for status, source, count in job_rows:
        jobs_by_status[status] = jobs_by_status.get(status, 0) + int(count)
        jobs_by_source[source] = jobs_by_source.get(source, 0) + int(count)

    return {
        "postings": {
            "ingested": sum(by_status.values()),
            "by_status": by_status,
            "ingested_items": int(items_sum),
            "activity": {kind: int(count) for kind, count in activity_rows},
        },
        "skills": {event: int(count) for event, count in skill_rows},
        "companies": {
            "created": sum(companies.values()),
            "by_source": companies,
        },
        "catalog_jobs": {
            "created": sum(jobs_by_status.values()),
            "by_status": jobs_by_status,
            "by_source": jobs_by_source,
        },
    }


async def events(
    db: AsyncSession,
    window: str,
    group: str = "all",
    outcome: str | None = None,
    actor: str | None = None,
    limit: int = 50,
    offset: int = 0,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Filtered ``audit_events`` rows with a best-effort actor email —
    the identity trail's first read surface (plan 151 D5)."""
    conditions = _range_conditions(AuditEvent.created_at, window, date_from, date_to)
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
    generation_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[int, list[AIGeneration]]:
    """The AI ledger with the full filter matrix (plan 151 D7). ``id``
    resolves one exact row (detail deep links, plan 154)."""
    conditions = []
    if generation_id:
        conditions.append(AIGeneration.id == generation_id)
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
    if window or date_from is not None:
        conditions.extend(_range_conditions(AIGeneration.created_at, window, date_from, date_to))
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


async def jobs(
    db: AsyncSession,
    *,
    status: str | None = None,
    job_type: str | None = None,
    user_id: str | None = None,
    window: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """The admin-wide background-jobs view (plan 152): every user's jobs,
    with a best-effort owner email."""
    conditions = []
    if status:
        conditions.append(BackgroundJob.status == status)
    if job_type:
        conditions.append(BackgroundJob.job_type == job_type)
    if user_id:
        conditions.append(BackgroundJob.user_id == user_id)
    if window or date_from is not None:
        conditions.extend(_range_conditions(BackgroundJob.created_at, window, date_from, date_to))

    total = (
        await db.execute(select(func.count(BackgroundJob.id)).where(*conditions))
    ).scalar() or 0
    rows = (
        await db.execute(
            select(BackgroundJob, User.email)
            .outerjoin(User, User.id == BackgroundJob.user_id)
            .where(*conditions)
            .order_by(BackgroundJob.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = [
        {
            "id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "error": job.error or "",
            "created_at": job.created_at,
            "finished_at": job.finished_at,
            "user_id": job.user_id,
            "user_email": email,
            "payload": job.payload,
            "result": job.result,
        }
        for job, email in rows
    ]
    return int(total), items


async def job_facets(
    db: AsyncSession,
    window: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict[str, Any]]:
    """job_type counts for the filter dropdown. No window and no explicit
    range means all time."""
    conditions = (
        _range_conditions(BackgroundJob.created_at, window, date_from, date_to)
        if window or date_from is not None
        else []
    )
    rows = (
        await db.execute(
            select(BackgroundJob.job_type, func.count(BackgroundJob.id))
            .where(*conditions)
            .group_by(BackgroundJob.job_type)
            .order_by(func.count(BackgroundJob.id).desc())
        )
    ).all()
    return [{"key": key, "count": int(count or 0)} for key, count in rows]


async def source_runs(
    db: AsyncSession,
    *,
    status: str | None = None,
    trigger: str | None = None,
    window: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """The cross-source ingestion run ledger (plan 152)."""
    conditions = []
    if status:
        conditions.append(SourceRun.status == status)
    if trigger:
        conditions.append(SourceRun.trigger == trigger)
    if window or date_from is not None:
        conditions.extend(_range_conditions(SourceRun.started_at, window, date_from, date_to))

    total = (await db.execute(select(func.count(SourceRun.id)).where(*conditions))).scalar() or 0
    rows = (
        await db.execute(
            select(SourceRun, JobSource.key, JobSource.connector_key)
            .outerjoin(JobSource, JobSource.id == SourceRun.source_id)
            .where(*conditions)
            .order_by(SourceRun.started_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = [
        {
            "id": run.id,
            "source_id": run.source_id,
            "source_key": source_key,
            "connector_key": connector_key,
            "trigger": run.trigger,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "duration_ms": run.duration_ms,
            "items_synced": run.items_synced,
            "error": run.error or "",
        }
        for run, source_key, connector_key in rows
    ]
    return int(total), items


async def changes(
    db: AsyncSession,
    *,
    entity: str,
    actor_kind: str | None = None,
    outcome: str | None = None,
    event: str | None = None,
    window: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """The cross-entity data-change journal (plan 152): posting_changes
    or skill_changes rows, newest first."""
    range_filter = (
        _range_conditions(PostingChange.occurred_at, window, date_from, date_to)
        if window or date_from is not None
        else []
    )
    if entity == "postings":
        conditions = list(range_filter)
        if actor_kind:
            conditions.append(PostingChange.actor_kind == actor_kind)
        if outcome:
            conditions.append(PostingChange.outcome == outcome)
        total = (
            await db.execute(select(func.count(PostingChange.id)).where(*conditions))
        ).scalar() or 0
        rows = (
            await db.execute(
                select(PostingChange)
                .where(*conditions)
                .order_by(PostingChange.occurred_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
        items = [
            {
                "id": row.id,
                "occurred_at": row.occurred_at,
                "actor_kind": row.actor_kind,
                "outcome": row.outcome,
                "posting_id": row.posting_id,
                "duration_ms": row.duration_ms,
                "actor_ref": row.actor_ref,
                "operation": row.operation,
                "diff": row.diff,
            }
            for row in rows
        ]
    else:
        conditions = (
            _range_conditions(SkillChange.occurred_at, window, date_from, date_to)
            if window or date_from is not None
            else []
        )
        if actor_kind:
            conditions.append(SkillChange.actor_kind == actor_kind)
        if event:
            conditions.append(SkillChange.event == event)
        total = (
            await db.execute(select(func.count(SkillChange.id)).where(*conditions))
        ).scalar() or 0
        rows = (
            await db.execute(
                select(SkillChange)
                .where(*conditions)
                .order_by(SkillChange.occurred_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
        items = [
            {
                "id": row.id,
                "occurred_at": row.occurred_at,
                "actor_kind": row.actor_kind,
                "event": row.event,
                "skill_id": row.skill_id,
                "skill_key": row.skill_key,
                "skill_label": row.skill_label,
                "actor_ref": row.actor_ref,
                "detail": row.detail,
            }
            for row in rows
        ]
    return int(total), items


EXPORT_COLUMNS = {
    "ai": [
        "created_at",
        "task_type",
        "provider",
        "model",
        "status",
        "tokens_in",
        "tokens_out",
        "latency_ms",
        "error",
        "run_id",
        "user_id",
    ],
    "events": ["created_at", "action", "actor", "actor_email", "outcome", "resource"],
    "jobs": [
        "created_at",
        "job_type",
        "status",
        "user_email",
        "attempts",
        "stage",
        "finished_at",
        "error",
    ],
    "source_runs": [
        "started_at",
        "source_key",
        "trigger",
        "status",
        "duration_ms",
        "items_synced",
        "error",
    ],
    "changes_postings": [
        "occurred_at",
        "actor_kind",
        "outcome",
        "posting_id",
        "duration_ms",
    ],
    "changes_skills": [
        "occurred_at",
        "event",
        "actor_kind",
        "skill_key",
        "skill_label",
    ],
}


def _csv_safe(value: Any) -> str:
    """Neutralize spreadsheet formula injection: a cell whose first
    character is `=`, `+`, `-` or `@` is prefixed with an apostrophe so
    Excel/Sheets renders it as text instead of executing it."""
    text = "" if value is None else str(value)
    if text[:1] in {"=", "+", "-", "@"}:
        return f"'{text}"
    return text


async def export_csv(
    db: AsyncSession,
    stream: str,
    *,
    window: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    task: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    query: str | None = None,
    group: str = "all",
    outcome: str | None = None,
    actor: str | None = None,
    job_type: str | None = None,
    trigger: str | None = None,
    entity: str = "postings",
    event: str | None = None,
) -> tuple[str, bool]:
    """The filtered ledger as CSV (plans 152/157), capped at EXPORT_LIMIT
    rows. Returns (csv_text, truncated)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    columns_key = f"changes_{entity}" if stream == "changes" else stream
    writer.writerow(EXPORT_COLUMNS[columns_key])
    truncated = False
    if stream == "ai":
        _, rows = await generations(
            db,
            task=task,
            provider=provider,
            status=status,
            query=query,
            window=window,
            date_from=date_from,
            date_to=date_to,
            limit=EXPORT_LIMIT,
        )
        truncated = len(rows) >= EXPORT_LIMIT
        for row in rows:
            writer.writerow(
                [
                    _csv_safe(row.created_at.isoformat()),
                    _csv_safe(row.task_type),
                    _csv_safe(row.provider),
                    _csv_safe(row.model),
                    _csv_safe(row.status),
                    row.tokens_in if row.tokens_in is not None else "",
                    row.tokens_out if row.tokens_out is not None else "",
                    row.latency_ms if row.latency_ms is not None else "",
                    _csv_safe(row.error),
                    _csv_safe(row.run_id),
                    _csv_safe(row.user_id),
                ]
            )
    elif stream == "events":
        window = window or "7d"
        _, rows = await events(
            db,
            window=window,
            group=group,
            outcome=outcome,
            actor=actor,
            date_from=date_from,
            date_to=date_to,
            limit=EXPORT_LIMIT,
        )
        truncated = len(rows) >= EXPORT_LIMIT
        for row in rows:
            writer.writerow(
                [
                    _csv_safe(row["created_at"].isoformat()),
                    _csv_safe(row["action"]),
                    _csv_safe(row["actor"]),
                    _csv_safe(row["actor_email"] or ""),
                    _csv_safe(row["outcome"]),
                    _csv_safe(row["resource"]),
                ]
            )
    elif stream == "jobs":
        _, rows = await jobs(
            db,
            status=status,
            job_type=job_type,
            window=window,
            date_from=date_from,
            date_to=date_to,
            limit=EXPORT_LIMIT,
        )
        truncated = len(rows) >= EXPORT_LIMIT
        for row in rows:
            writer.writerow(
                [
                    _csv_safe(row["created_at"].isoformat()),
                    _csv_safe(row["job_type"]),
                    _csv_safe(row["status"]),
                    _csv_safe(row["user_email"] or ""),
                    row["attempts"],
                    _csv_safe(row["stage"] or ""),
                    _csv_safe(row["finished_at"].isoformat() if row["finished_at"] else ""),
                    _csv_safe(row["error"]),
                ]
            )
    elif stream == "source_runs":
        _, rows = await source_runs(
            db,
            status=status,
            trigger=trigger,
            window=window,
            date_from=date_from,
            date_to=date_to,
            limit=EXPORT_LIMIT,
        )
        truncated = len(rows) >= EXPORT_LIMIT
        for row in rows:
            writer.writerow(
                [
                    _csv_safe(row["started_at"].isoformat() if row["started_at"] else ""),
                    _csv_safe(row["source_key"] or ""),
                    _csv_safe(row["trigger"]),
                    _csv_safe(row["status"]),
                    row["duration_ms"],
                    row["items_synced"],
                    _csv_safe(row["error"]),
                ]
            )
    elif stream == "changes":
        _, rows = await changes(
            db,
            entity=entity,
            actor_kind=status,
            outcome=outcome,
            event=event,
            window=window,
            date_from=date_from,
            date_to=date_to,
            limit=EXPORT_LIMIT,
        )
        truncated = len(rows) >= EXPORT_LIMIT
        for row in rows:
            if entity == "postings":
                writer.writerow(
                    [
                        row["occurred_at"].isoformat(),
                        _csv_safe(row["actor_kind"]),
                        _csv_safe(row.get("outcome") or ""),
                        _csv_safe(str(row.get("posting_id") or "")),
                        row.get("duration_ms") if row.get("duration_ms") is not None else "",
                    ]
                )
            else:
                writer.writerow(
                    [
                        row["occurred_at"].isoformat(),
                        _csv_safe(row.get("event") or ""),
                        _csv_safe(row["actor_kind"]),
                        _csv_safe(row.get("skill_key") or ""),
                        _csv_safe(row.get("skill_label") or ""),
                    ]
                )
    return buffer.getvalue(), truncated
