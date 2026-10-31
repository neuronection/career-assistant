"""Shared time-window mechanism (plan 170 slice 0).

One time axis, one truth: every posted window reads the effective posted
date ``coalesce(posted_at, created_at)`` (a posting without a market date
lands by ingestion date instead of falling in no window) and every
time-bucketed series keys on the same dialect-aware bucket expressions
(PostgreSQL ``date_trunc``, SQLite ``strftime``/``date``). The module
carries the mechanism only — window policy (which windows a surface
accepts) stays with each consumer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, func
from sqlalchemy.sql.elements import ColumnElement

from app.models.posting_model import JobPosting

POSTED_WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}

BUCKETS = ("hour", "day", "week", "month")


def as_utc(moment: datetime) -> datetime:
    """Normalize a datetime to UTC — query params may arrive tz-naive
    (``?from=2026-10-01T00:00:00``) and break arithmetic against aware
    ``now``."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def effective_posted_expr() -> ColumnElement:
    """The one time axis: a posting's effective posted date."""
    return func.coalesce(JobPosting.posted_at, JobPosting.created_at)


def window_clause(window: str, now: datetime) -> ColumnElement:
    """Effective posted date within the preset ``window`` (a key of
    :data:`POSTED_WINDOWS`) relative to ``now``."""
    return effective_posted_expr() >= now - POSTED_WINDOWS[window]


def range_bounds(
    window: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime, datetime | None]:
    """``(start, prev_start, end)`` for a preset window or an explicit
    range — UTC aware. An explicit ``from`` overrides the preset; ``end``
    is ``None`` for open-ended presets. The prev window is the
    equal-length range before ``start`` (delta math)."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    if date_from is not None:
        start = as_utc(date_from)
        end = as_utc(date_to) if date_to is not None else moment
        span = max(end - start, timedelta(seconds=1))
        return start, start - span, end
    span = POSTED_WINDOWS[window or "24h"]
    return moment - span, moment - span * 2, None


def bucket_expr(dialect_name: str, column: Any, bucket: str) -> Any:
    """Dialect-aware date bucketing (``hour``/``day``/``week``/``month``).

    Both dialects yield the same canonical keys via :func:`bucket_key`:
    ``YYYY-MM-DDTHH:00:00``, ``YYYY-MM-DD`` (week: the bucket's Monday),
    ``YYYY-MM``."""
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket: {bucket}")
    if dialect_name == "postgresql":
        return func.date_trunc(bucket, column)
    if bucket == "hour":
        return func.strftime("%Y-%m-%dT%H:00:00", column)
    if bucket == "day":
        return func.strftime("%Y-%m-%d", column)
    if bucket == "month":
        return func.strftime("%Y-%m", column)
    days_back = (func.cast(func.strftime("%w", column), Integer) + 6) % 7
    return func.date(func.julianday(column) - days_back)


def bucket_key(value: Any, bucket: str) -> str:
    """Canonical text key for one bucket — a datetime (PostgreSQL
    ``date_trunc``) or text (SQLite ``strftime``) both normalize to the
    same form."""
    if isinstance(value, datetime):
        return _key_for(value, bucket)
    return str(value).split("+")[0]


def zero_filled(
    rows: dict[str, Any],
    start: datetime,
    stop: datetime,
    bucket: str,
    fill: dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge sparse bucket rows into one point per bucket across
    ``[start, stop]``, then append and sort any rows outside the walked
    range. Each point is ``{"bucket": key, **values}``; missing buckets
    carry a copy of ``fill``."""
    points: list[dict[str, Any]] = []
    cursor = _snap(start, bucket)
    step = _step_of(bucket)
    while cursor <= stop:
        key = _key_for(cursor, bucket)
        values = rows.pop(key, None)
        points.append({"bucket": key, **(dict(fill) if values is None else values)})
        cursor = _advance(cursor, bucket, step)
    for key in sorted(rows):
        points.append({"bucket": key, **rows[key]})
    points.sort(key=lambda point: point["bucket"])
    return points


def _key_for(moment: datetime, bucket: str) -> str:
    if bucket == "hour":
        return moment.strftime("%Y-%m-%dT%H:00:00")
    if bucket == "month":
        return moment.strftime("%Y-%m")
    return moment.strftime("%Y-%m-%d")


def _snap(start: datetime, bucket: str) -> datetime:
    cursor = start.replace(minute=0, second=0, microsecond=0)
    if bucket == "hour":
        return cursor
    cursor = cursor.replace(hour=0)
    if bucket == "day":
        return cursor
    if bucket == "week":
        return cursor - timedelta(days=(cursor.weekday()))
    return cursor.replace(day=1)


def _step_of(bucket: str) -> timedelta | None:
    return {"hour": timedelta(hours=1), "day": timedelta(days=1), "week": timedelta(days=7)}.get(
        bucket
    )


def _advance(cursor: datetime, bucket: str, step: timedelta | None) -> datetime:
    if step is not None:
        return cursor + step
    return (cursor.replace(day=1) + timedelta(days=32)).replace(day=1)
