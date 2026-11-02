"""Resolution KPI aggregation over ``background_jobs`` (plan 153 slice 4).

One read seam for the admin Resolution surface: the newest succeeded
POSTING_EXTRACT job's result summary (last run) and rolling sums/rates
over a preset window. Aggregation is dialect-aware by construction —
the counters are read through SQLAlchemy's typed JSON accessors
(``->>``/``::integer`` on PostgreSQL, ``JSON_EXTRACT``/``CAST`` on
SQLite), so the desktop SQLite lane answers with the same SQL shape —
and the totals come back from one grouped query, never raw rows.
Read-only by design: the summaries are written by the extract handlers.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus, BackgroundJobType
from app.models.schedule_model import Schedule
from app.services.analytics.time_buckets import range_bounds

WINDOWS: dict[str, str] = {"24h": "24h", "7d": "7d", "30d": "30d"}
DEFAULT_WINDOW = "7d"


def _int_or(value: Any, default: int = 0) -> int:
    """Mistyped/missing counters read as defaults — a stats view never
    500s on an old run's result (the run-ledger renderer rule)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _bool_or(value: Any) -> bool:
    return value is True


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _last_run_shape(job: BackgroundJob | None) -> dict[str, Any]:
    if job is None:
        return {
            "job_id": None,
            "status": None,
            "created_at": None,
            "finished_at": None,
            "labels": 0,
            "exact_hits": 0,
            "pass2_matches": 0,
            "new_proposals": 0,
            "gate_blocks": 0,
            "degraded": False,
            "replay": False,
        }
    raw = job.result if isinstance(job.result, dict) else {}
    return {
        "job_id": str(job.id),
        "status": job.status,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "labels": _int_or(raw.get("labels")),
        "exact_hits": _int_or(raw.get("exact_hits")),
        "pass2_matches": _int_or(raw.get("pass2_matches")),
        "new_proposals": _int_or(raw.get("new_proposals")),
        "gate_blocks": _int_or(raw.get("gate_blocks")),
        "degraded": _bool_or(raw.get("degraded")),
        "replay": _bool_or(raw.get("replay")),
    }


async def resolution_stats(db: AsyncSession, *, window: str = DEFAULT_WINDOW) -> dict[str, Any]:
    """Last-run summary + rolling match/new/block/replay/degrade rates
    over the succeeded POSTING_EXTRACT jobs of the window, plus the
    enabled schedules currently failing (the automations deep link's
    number — never a second scheduler surface)."""
    start, _prev_start, end = range_bounds(window, None, None)
    base_conditions = [
        BackgroundJob.job_type == BackgroundJobType.POSTING_EXTRACT.value,
        BackgroundJob.status == BackgroundJobStatus.SUCCEEDED.value,
        BackgroundJob.created_at >= start,
    ]
    if end is not None:
        base_conditions.append(BackgroundJob.created_at < end)

    result = BackgroundJob.result
    row = (
        await db.execute(
            select(
                func.count(BackgroundJob.id),
                func.coalesce(func.sum(result["labels"].as_integer()), 0),
                func.coalesce(func.sum(result["exact_hits"].as_integer()), 0),
                func.coalesce(func.sum(result["pass2_matches"].as_integer()), 0),
                func.coalesce(func.sum(result["new_proposals"].as_integer()), 0),
                func.coalesce(func.sum(result["gate_blocks"].as_integer()), 0),
                func.coalesce(
                    func.sum(case((result["replay"].as_boolean().is_(True), 1), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((result["degraded"].as_boolean().is_(True), 1), else_=0)), 0
                ),
            ).where(*base_conditions)
        )
    ).one()

    runs = int(row[0] or 0)
    labels = int(row[1] or 0)
    exact_hits = int(row[2] or 0)
    pass2_matches = int(row[3] or 0)
    new_proposals = int(row[4] or 0)
    gate_blocks = int(row[5] or 0)
    replay_runs = int(row[6] or 0)
    degraded_runs = int(row[7] or 0)

    last = (
        (
            await db.execute(
                select(BackgroundJob)
                .where(*base_conditions)
                .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )

    failing_schedules = (
        await db.execute(
            select(func.count(Schedule.id)).where(
                Schedule.enabled.is_(True), Schedule.consecutive_failures > 0
            )
        )
    ).scalar() or 0

    return {
        "last_run": _last_run_shape(last),
        "rolling": {
            "window": window,
            "runs": runs,
            "replay_runs": replay_runs,
            "degraded_runs": degraded_runs,
            "labels": labels,
            "exact_hits": exact_hits,
            "pass2_matches": pass2_matches,
            "new_proposals": new_proposals,
            "gate_blocks": gate_blocks,
            "match_rate": _rate(exact_hits + pass2_matches, labels),
            "new_rate": _rate(new_proposals, labels),
            "block_rate": _rate(gate_blocks, new_proposals),
            "replay_rate": _rate(replay_runs, runs),
            "degrade_rate": _rate(degraded_runs, runs),
        },
        "failing_schedules": int(failing_schedules),
    }
