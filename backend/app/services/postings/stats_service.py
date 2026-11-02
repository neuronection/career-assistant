"""Market statistics over postings (plan 170 slice 1).

Live aggregation on read — the audit-dashboard precedent, no cache
layer. One time axis (the effective posted date,
``coalesce(posted_at, created_at)``) and one explicit status basis per
metric (``open`` = the explore feed's ``mapped``/``new`` set, ``all`` =
every status); a single metric never mixes bases. Every aggregation is
bounded: capped lists, ≤400 timeseries points, a bounded salary sample.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.experience_model import Organization
from app.models.job_model import Job, JobFamily
from app.models.posting_model import (
    JobPosting,
    JobSource,
    PostingSkill,
    SourceRun,
)
from app.models.taxonomy_model import Skill
from app.schemas.stats import (
    BreakdownRowOut,
    BucketName,
    ClockCellOut,
    ClockPeakOut,
    ClockworkOut,
    CoverageOut,
    DeltaOut,
    FreshnessOut,
    FreshnessSourceOut,
    FreshnessState,
    InsightOut,
    PostingStatsBreakdown,
    PostingStatsOverview,
    PostingStatsSalary,
    PostingStatsSkills,
    PostingStatsSummary,
    PostingStatsTimeseries,
    SalaryBucketOut,
    SalaryCurrencyOut,
    SalarySeniorityOut,
    SkillCategoryOut,
    SkillLevelOut,
    SkillStatOut,
    SparkPointOut,
    StatusBasis,
    TimeseriesPointOut,
)
from app.services.analytics.deltas import delta
from app.services.analytics.time_buckets import (
    POSTED_WINDOWS,
    bucket_expr,
    bucket_key,
    clock_hour_expr,
    clock_weekday_expr,
    effective_posted_expr,
    zero_filled,
)
from app.services.postings.explore_service import OPEN_STATUSES, SKILL_FACET_SIZE

WINDOWS = ("24h", "7d", "30d", "90d", "all")
BASES = ("open", "all")

TIMESERIES_MAX_POINTS = 400
TIMESERIES_BUCKETS = ("hour", "day", "week", "month")
TIMESERIES_STEP = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(days=7),
    "month": timedelta(days=28),
}
BREAKDOWN_LIMIT_MAX = 50
BREAKDOWN_OTHER = "other"
UNMAPPED = "unmapped"
SALARY_SAMPLE_LIMIT = 5_000
SALARY_THIN_FLOOR = 10
SALARY_HISTOGRAM_BUCKETS = 10
SKILL_TREND_LIMIT = 5
SKILL_TREND_FLOOR = 3
CATEGORY_LIMIT = 12
INSIGHT_TRAILING_WINDOWS = 8
INSIGHT_Z = 2.0
INSIGHT_MIN_COUNT = 3
INSIGHT_LIMIT = 5
FRESHNESS_STALE_AFTER = timedelta(hours=48)
DELIVERED_RUN_STATUSES = ("ok", "degraded")


@dataclass(frozen=True)
class WindowContext:
    """One resolved metric window: the range, its equal-length
    predecessor and the resolved ``as_of``."""

    as_of: datetime
    window: str
    start: datetime | None
    end: datetime
    prev_start: datetime | None
    span: timedelta | None


def window_context(
    window: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    now: datetime | None = None,
) -> WindowContext:
    """Resolve a preset window or explicit range to UTC bounds.

    An explicit ``from`` wins over the preset (the audit ``RangeFilter``
    convention); tz-naive query params are normalized here. ``window``
    resolves to ``"custom"`` when an explicit range wins, and ``"all"``
    carries no lower bound."""
    as_of = (now or datetime.now(UTC)).astimezone(UTC)
    if window not in WINDOWS:
        raise ValidationError("window must be one of: " + ", ".join(WINDOWS))
    if date_from is not None:
        start = _utc(date_from)
        end = _utc(date_to) if date_to is not None else as_of
        span = max(end - start, timedelta(seconds=1))
        return WindowContext(as_of, "custom", start, end, start - span, span)
    if window == "all":
        return WindowContext(as_of, "all", None, as_of, None, None)
    span = POSTED_WINDOWS[window]
    return WindowContext(as_of, window, as_of - span, as_of, as_of - span * 2, span)


def basis_conditions(status_basis: str) -> list:
    """The status-basis population (all time): the open set for ``open``,
    everything for ``all``."""
    _check_basis(status_basis)
    if status_basis == "open":
        return [JobPosting.status.in_(OPEN_STATUSES)]
    return []


def current_conditions(ctx: WindowContext, status_basis: str) -> list:
    """The metric population for the current window.

    Preset windows bound below only — the exact explore ``posted_within``
    predicate, so a rail chip counts the list it opens (rows dated in the
    future belong to no closed window but to the open one). Explicit
    ranges bound ``[from, to)``."""
    return _conditions(status_basis, ctx.start, ctx.end, bounded=ctx.window == "custom")


def prev_conditions(ctx: WindowContext, status_basis: str) -> list:
    """The equal-length predecessor population, ``[prev_start, start)``."""
    if ctx.prev_start is None or ctx.start is None:
        return []
    return _conditions(status_basis, ctx.prev_start, ctx.start, bounded=True)


def _conditions(status_basis: str, start: datetime | None, end: datetime, *, bounded: bool) -> list:
    conditions = list(basis_conditions(status_basis))
    if start is not None:
        conditions.append(effective_posted_expr() >= start)
        if bounded:
            conditions.append(effective_posted_expr() < end)
    return conditions


def _check_basis(status_basis: str) -> None:
    if status_basis not in BASES:
        raise ValidationError("status_basis must be one of: " + ", ".join(BASES))


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


async def _count(db: AsyncSession, conditions: list) -> int:
    stmt = select(func.count(JobPosting.id))
    if conditions:
        stmt = stmt.where(*conditions)
    return int((await db.execute(stmt)).scalar_one())


# ----------------------------------------------------------------- summary


async def summary(db: AsyncSession, *, status_basis: str = "open", now: datetime | None = None):
    """The pulse: fixed-window counts with deltas, the 14-day sparkline
    and source freshness. Rail chips use the ``open`` basis by default —
    the basis explore's totals use."""
    _check_basis(status_basis)
    as_of = (now or datetime.now(UTC)).astimezone(UTC)
    windows: dict[str, DeltaOut] = {}
    for key in ("24h", "7d", "30d"):
        span = POSTED_WINDOWS[key]
        count = await _count(db, _conditions(status_basis, as_of - span, as_of, bounded=False))
        prev = await _count(
            db, _conditions(status_basis, as_of - span * 2, as_of - span, bounded=True)
        )
        windows[f"new_{key}"] = delta(count, prev)

    open_total = await _count(db, _conditions("open", None, as_of, bounded=False))

    spark_start = as_of - timedelta(days=13)
    spark_start = spark_start.replace(hour=0, minute=0, second=0, microsecond=0)
    spark_rows = await _bucket_counts(db, status_basis, spark_start, as_of, "day", bounded=False)
    as_of_day = as_of.strftime("%Y-%m-%d")
    sparkline = [
        SparkPointOut(bucket=point["bucket"], count=point["count"])
        for point in zero_filled(spark_rows, spark_start, as_of, "day", {"count": 0})
        if point["bucket"] <= as_of_day
    ]

    return PostingStatsSummary(
        as_of=as_of,
        status_basis=cast(StatusBasis, status_basis),
        new_24h=windows["new_24h"],
        new_7d=windows["new_7d"],
        new_30d=windows["new_30d"],
        open_total=open_total,
        sparkline=sparkline,
        freshness=await freshness(db, now=as_of),
    )


async def freshness(db: AsyncSession, *, now: datetime | None = None) -> FreshnessOut:
    """Source ingestion freshness from the ``source_runs`` ledger — the
    market-health footer names every source whose data may be missing or
    aging (stale = no delivery within :data:`FRESHNESS_STALE_AFTER`)."""
    as_of = (now or datetime.now(UTC)).astimezone(UTC)
    sources = (await db.execute(select(JobSource))).scalars().all()
    last_rows = (
        await db.execute(
            select(SourceRun.source_id, func.max(SourceRun.finished_at))
            .where(SourceRun.status.in_(DELIVERED_RUN_STATUSES))
            .group_by(SourceRun.source_id)
        )
    ).all()
    last_success = dict(last_rows)
    stale: list[FreshnessSourceOut] = []
    for source in sources:
        delivered = last_success.get(source.id)
        status: FreshnessState
        if source.paused_at is not None:
            status = "paused"
        elif delivered is None:
            status = "never"
        elif delivered < as_of - FRESHNESS_STALE_AFTER:
            status = "stale"
        else:
            status = "ok"
        if status != "ok":
            stale.append(
                FreshnessSourceOut(source_key=source.key, status=status, last_success=delivered)
            )
    stale.sort(key=lambda item: item.source_key)
    return FreshnessOut(as_of=as_of, stale_sources=stale)


# ---------------------------------------------------------------- overview


async def overview(
    db: AsyncSession,
    *,
    window: str = "30d",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status_basis: str = "all",
    now: datetime | None = None,
) -> PostingStatsOverview:
    """Page narrative payload: in-range KPIs, the status mix, coverage
    chips and the deterministic insights strip (H2)."""
    _check_basis(status_basis)
    ctx = window_context(window, date_from, date_to, now)
    conditions = current_conditions(ctx, status_basis)
    count = await _count(db, conditions)
    prev = await _count(db, prev_conditions(ctx, status_basis)) if ctx.prev_start is not None else 0
    open_total = await _count(db, _conditions("open", None, ctx.end, bounded=False))

    mix_rows = (
        await db.execute(
            select(JobPosting.status, func.count(JobPosting.id))
            .where(*conditions)
            .group_by(JobPosting.status)
        )
    ).all()
    status_mix = {status: int(total) for status, total in mix_rows}

    return PostingStatsOverview(
        as_of=ctx.as_of,
        window=ctx.window,
        status_basis=cast(StatusBasis, status_basis),
        start=ctx.start,
        end=ctx.end,
        new_in_range=delta(count, prev),
        open_total=open_total,
        status_mix=status_mix,
        coverage=await _coverage(db, conditions, count),
        insights=await _insights(db, ctx, status_basis),
    )


async def _coverage(db: AsyncSession, conditions: list, total: int) -> CoverageOut:
    if total == 0:
        return CoverageOut(salary=0.0, location=0.0, org_linked=0.0, skill_tagged=0.0)
    location_ok = or_(
        JobPosting.location["city"].as_string().is_not(None),
        JobPosting.location["country"].as_string().is_not(None),
    )
    skill_exists = select(PostingSkill.id).where(PostingSkill.posting_id == JobPosting.id).exists()
    row = (
        await db.execute(
            select(
                func.sum(
                    case(
                        (
                            or_(
                                JobPosting.salary_normalized_min.is_not(None),
                                JobPosting.salary_normalized_max.is_not(None),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                func.sum(case((location_ok, 1), else_=0)),
                func.sum(case((JobPosting.org_match_state == "linked", 1), else_=0)),
                func.sum(case((skill_exists, 1), else_=0)),
            ).where(*conditions)
        )
    ).one()

    def share(value: Any) -> float:
        return round(int(value or 0) / total, 4)

    return CoverageOut(
        salary=share(row[0]),
        location=share(row[1]),
        org_linked=share(row[2]),
        skill_tagged=share(row[3]),
    )


# --------------------------------------------------------------- timeseries


async def timeseries(
    db: AsyncSession,
    *,
    window: str = "30d",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    bucket: str | None = None,
    split: str | None = None,
    status_basis: str = "all",
    now: datetime | None = None,
) -> PostingStatsTimeseries:
    """Volume over time (zero-filled buckets) with the equal-length
    previous-period ghost, ingestion-date counts and an optional split
    series. Buckets auto-select by span (hour ≤48h, day ≤90d, week
    ≤400d, else month); an explicit bucket must stay within the
    400-point bound."""
    _check_basis(status_basis)
    if split is not None and split not in SPLITS:
        raise ValidationError("split must be one of: " + ", ".join(SPLITS))
    ctx = window_context(window, date_from, date_to, now)
    start, end = ctx.start, ctx.end
    if start is None:
        start = await _earliest(db, current_conditions(ctx, status_basis), ctx.end)
    chosen = bucket or _auto_bucket(end - start)
    _check_bucket_span(chosen, end - start)

    conditions = current_conditions(ctx, status_basis)
    rows = await _bucket_counts(
        db, status_basis, start, end, chosen, bounded=ctx.window == "custom"
    )
    prev_rows = (
        await _bucket_counts(db, status_basis, ctx.prev_start, ctx.start, chosen, bounded=True)
        if (ctx.prev_start is not None and ctx.start is not None)
        else {}
    )
    ingestion_rows = await _bucket_counts(
        db,
        status_basis,
        start,
        end,
        chosen,
        bounded=ctx.window == "custom",
        column=JobPosting.created_at,
    )

    current_points = zero_filled(rows, start, end, chosen, {"count": 0})
    prev_points = (
        zero_filled(prev_rows, ctx.prev_start, ctx.start, chosen, {"count": 0})
        if ctx.prev_start is not None and ctx.start is not None
        else []
    )
    series_map = await _split_series(db, conditions, split, start, end, chosen) if split else {}

    points: list[TimeseriesPointOut] = []
    for index, point in enumerate(current_points):
        prev_count = int(prev_points[index]["count"]) if index < len(prev_points) else 0
        points.append(
            TimeseriesPointOut(
                bucket=point["bucket"],
                count=int(point["count"]),
                prev=prev_count,
                ingestion=int(ingestion_rows.get(point["bucket"], {}).get("count", 0)),
                series=series_map.get(point["bucket"], {}),
            )
        )
    return PostingStatsTimeseries(
        as_of=ctx.as_of,
        window=ctx.window,
        status_basis=cast(StatusBasis, status_basis),
        start=start,
        end=ctx.end,
        bucket=cast(BucketName, chosen),
        split=split,
        points=points,
    )


async def _earliest(db: AsyncSession, conditions: list, end: datetime) -> datetime:
    stmt = select(func.min(effective_posted_expr()))
    if conditions:
        stmt = stmt.where(*conditions)
    stamp = (await db.execute(stmt)).scalar_one_or_none()
    if stamp is None:
        return end - timedelta(days=90)
    return _utc(stamp)


def _auto_bucket(span: timedelta) -> BucketName:
    limits: tuple[tuple[BucketName, timedelta], ...] = (
        ("hour", timedelta(hours=48)),
        ("day", timedelta(days=90)),
        ("week", timedelta(days=400)),
    )
    for bucket, limit in limits:
        if span <= limit:
            return bucket
    return "month"


def _check_bucket_span(bucket: str, span: timedelta) -> None:
    if bucket not in TIMESERIES_BUCKETS:
        raise ValidationError("bucket must be one of: " + ", ".join(TIMESERIES_BUCKETS))
    if span / TIMESERIES_STEP[bucket] + 2 > TIMESERIES_MAX_POINTS:
        raise ValidationError(
            f"range too long for bucket {bucket!r} (max {TIMESERIES_MAX_POINTS} points)"
        )


async def _bucket_counts(
    db: AsyncSession,
    status_basis: str,
    start: datetime | None,
    end: datetime | None,
    bucket: str,
    *,
    bounded: bool,
    column=None,
) -> dict[str, dict[str, int]]:
    if start is None or end is None:
        return {}
    conditions = _conditions(status_basis, start, end, bounded=bounded)
    grouped = bucket_expr(db.get_bind().dialect.name, column or effective_posted_expr(), bucket)
    rows = (
        await db.execute(
            select(grouped, func.count(JobPosting.id))
            .where(*conditions)
            .group_by(grouped)
            .order_by(grouped)
        )
    ).all()
    return {bucket_key(key, bucket): {"count": int(count)} for key, count in rows}


SPLITS = ("status", "source", "work_mode", "seniority", "employment")
SPLIT_LIMIT = 8


async def _split_series(
    db: AsyncSession,
    conditions: list,
    split: str,
    start: datetime,
    end: datetime,
    bucket: str,
) -> dict[str, dict[str, int]]:
    column = {
        "status": JobPosting.status,
        "source": JobPosting.source_id,
        "work_mode": JobPosting.onsite_policy,
        "seniority": JobPosting.seniority,
        "employment": JobPosting.employment_type,
    }[split]
    grouped = bucket_expr(db.get_bind().dialect.name, effective_posted_expr(), bucket)
    rows = (
        await db.execute(
            select(grouped, column, func.count(JobPosting.id))
            .where(*conditions)
            .group_by(grouped, column)
            .order_by(grouped)
        )
    ).all()
    totals: dict[str, int] = {}
    per_bucket: dict[str, dict[str, int]] = {}
    for key, value, count in rows:
        label = str(value) if value is not None else UNMAPPED
        if split == "source":
            label = await _source_key(db, value, label)
        bucket_label = bucket_key(key, bucket)
        slot = per_bucket.setdefault(bucket_label, {})
        slot[label] = slot.get(label, 0) + int(count)
        totals[label] = totals.get(label, 0) + int(count)
    top = {
        label for label, _ in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:SPLIT_LIMIT]
    }
    for slot in per_bucket.values():
        folded = {label: count for label, count in slot.items() if label in top}
        rest = sum(count for label, count in slot.items() if label not in top)
        if rest:
            folded[BREAKDOWN_OTHER] = folded.get(BREAKDOWN_OTHER, 0) + rest
        slot.clear()
        slot.update(folded)
    return per_bucket


async def _source_key(db: AsyncSession, value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    row = (
        await db.execute(select(JobSource.key).where(JobSource.id == value))
    ).scalar_one_or_none()
    return row or fallback


# ------------------------------------------------------------------- clockwork


async def clockwork(
    db: AsyncSession,
    *,
    window: str = "30d",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status_basis: str = "all",
    now: datetime | None = None,
) -> ClockworkOut:
    """The weekday x hour posting clock (plan 171 H7): a complete,
    zero-filled 7x24 matrix over the window population on the shared
    effective-posted predicate, with the equal-length predecessor per
    cell and a deterministic peak (ties break weekday-then-hour
    ascending). Always UTC — the wire carries ``time_zone``."""
    _check_basis(status_basis)
    as_of = (now or datetime.now(UTC)).astimezone(UTC)
    ctx = window_context(window, date_from, date_to, as_of)
    if ctx.start is None:  # window="all": the clock needs a real start
        ctx = WindowContext(
            ctx.as_of,
            ctx.window,
            await _earliest(db, basis_conditions(status_basis), ctx.end),
            ctx.end,
            None,
            None,
        )
    dialect = db.get_bind().dialect.name
    column = effective_posted_expr()
    weekday = clock_weekday_expr(dialect, column)
    hour = clock_hour_expr(dialect, column)

    async def _grid(conditions: list) -> dict[tuple[int, int], int]:
        rows = (
            await db.execute(
                select(weekday, hour, func.count(JobPosting.id))
                .where(*conditions)
                .group_by(weekday, hour)
            )
        ).all()
        return {(int(w), int(h)): int(n) for w, h, n in rows}

    grid = await _grid(current_conditions(ctx, status_basis))
    prev_grid = (
        await _grid(prev_conditions(ctx, status_basis)) if ctx.prev_start is not None else {}
    )

    cells: list[ClockCellOut] = []
    by_weekday = [0] * 7
    by_hour = [0] * 24
    for day in range(1, 8):
        for slot in range(24):
            count = grid.get((day, slot), 0)
            prev = prev_grid.get((day, slot), 0)
            pct = delta(count, prev).delta_pct
            cells.append(
                ClockCellOut(weekday=day, hour=slot, count=count, prev=prev, delta_pct=pct)
            )
            by_weekday[day - 1] += count
            by_hour[slot] += count

    peak: ClockPeakOut | None = None
    best = max(cells, key=lambda cell: (cell.count, -cell.weekday, -cell.hour))
    if best.count > 0:
        peak = ClockPeakOut(weekday=best.weekday, hour=best.hour, count=best.count)

    return ClockworkOut(
        as_of=as_of,
        window=ctx.window,
        status_basis=cast(StatusBasis, status_basis),
        start=ctx.start,
        end=ctx.end,
        cells=cells,
        peak=peak,
        by_weekday=by_weekday,
        by_hour=by_hour,
    )


# ------------------------------------------------------------------- skills


async def skills(
    db: AsyncSession,
    *,
    window: str = "30d",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status_basis: str = "all",
    limit: int = SKILL_FACET_SIZE,
    now: datetime | None = None,
) -> PostingStatsSkills:
    """Skills demand in the window: top asked (count/share/delta), the
    rising/cooling trend lists (delta floor :data:`SKILL_TREND_FLOOR`),
    category mix, level histogram and priority mix."""
    _check_basis(status_basis)
    ctx = window_context(window, date_from, date_to, now)
    limit = max(1, min(limit, SKILL_FACET_SIZE))
    population = select(JobPosting.id).where(*current_conditions(ctx, status_basis))
    prev_population = select(JobPosting.id).where(*prev_conditions(ctx, status_basis))
    total = await _count(db, current_conditions(ctx, status_basis))

    counts = await _skill_counts(db, population)
    prev_counts = await _skill_counts(db, prev_population) if ctx.prev_start is not None else {}
    labels = await _skill_labels(db, list(counts))

    top: list[SkillStatOut] = []
    for key, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
        top.append(_skill_stat(key, labels.get(key, key), count, total, prev_counts.get(key, 0)))

    trend_pool = [
        stat for stat in top if stat.count >= SKILL_TREND_FLOOR and stat.delta_pct is not None
    ]
    momentum = {stat.key: stat.delta_pct or 0.0 for stat in trend_pool}
    rising = sorted(
        (stat for stat in trend_pool if momentum[stat.key] > 0),
        key=lambda stat: (-momentum[stat.key], stat.key),
    )[:SKILL_TREND_LIMIT]
    falling = sorted(
        (stat for stat in trend_pool if momentum[stat.key] < 0),
        key=lambda stat: (momentum[stat.key], stat.key),
    )[:SKILL_TREND_LIMIT]

    categories = await _skill_categories(db, population, total)
    levels, avg_level = await _skill_levels(db, population)
    priority = await _skill_priority(db, population)
    tagged, rows_total = await _skill_density(db, population)

    return PostingStatsSkills(
        as_of=ctx.as_of,
        window=ctx.window,
        status_basis=cast(StatusBasis, status_basis),
        start=ctx.start,
        end=ctx.end,
        top=top,
        rising=rising,
        falling=falling,
        categories=categories,
        levels=levels,
        avg_level=avg_level,
        priority=priority,
        avg_skills_per_posting=round(rows_total / tagged, 2) if tagged else 0.0,
    )


def _skill_stat(key: str, label: str, count: int, total: int, prev: int) -> SkillStatOut:
    this_delta = delta(count, prev)
    return SkillStatOut(
        key=key,
        label=label,
        count=count,
        share=round(count / total, 4) if total else 0.0,
        delta_pct=this_delta.delta_pct,
        trend=this_delta.trend,
    )


async def _skill_counts(db: AsyncSession, population) -> dict[str, int]:
    rows = (
        await db.execute(
            select(Skill.key, func.count(PostingSkill.posting_id))
            .join(PostingSkill, PostingSkill.skill_id == Skill.id)
            .where(PostingSkill.posting_id.in_(population))
            .group_by(Skill.key)
            .order_by(func.count(PostingSkill.posting_id).desc())
            .limit(SKILL_FACET_SIZE * 3)
        )
    ).all()
    return {key: int(count) for key, count in rows}


async def _skill_labels(db: AsyncSession, keys: list[str]) -> dict[str, str]:
    if not keys:
        return {}
    rows = (await db.execute(select(Skill.key, Skill.label).where(Skill.key.in_(keys)))).all()
    return dict(rows)


async def _skill_categories(db: AsyncSession, population, total: int) -> list[SkillCategoryOut]:
    rows = (
        await db.execute(
            select(Skill.category, func.count(func.distinct(PostingSkill.posting_id)))
            .join(PostingSkill, PostingSkill.skill_id == Skill.id)
            .where(PostingSkill.posting_id.in_(population))
            .group_by(Skill.category)
            .order_by(func.count(func.distinct(PostingSkill.posting_id)).desc())
            .limit(CATEGORY_LIMIT)
        )
    ).all()
    return [
        SkillCategoryOut(
            key=key,
            count=int(count),
            share=round(int(count) / total, 4) if total else 0.0,
        )
        for key, count in rows
    ]


async def _skill_levels(db: AsyncSession, population) -> tuple[list[SkillLevelOut], float | None]:
    rows = (
        await db.execute(
            select(PostingSkill.required_level, func.count(PostingSkill.id))
            .where(
                PostingSkill.posting_id.in_(population),
                PostingSkill.required_level.is_not(None),
            )
            .group_by(PostingSkill.required_level)
        )
    ).all()
    by_level = {int(level): int(count) for level, count in rows if level is not None}
    levels = [SkillLevelOut(level=level, count=by_level.get(level, 0)) for level in range(1, 11)]
    weighted = sum(level * count for level, count in by_level.items() if 1 <= level <= 10)
    total = sum(count for level, count in by_level.items() if 1 <= level <= 10)
    avg = round(weighted / total, 2) if total else None
    return levels, avg


async def _skill_priority(db: AsyncSession, population) -> dict[str, int]:
    rows = (
        await db.execute(
            select(PostingSkill.priority, func.count(PostingSkill.id))
            .where(PostingSkill.posting_id.in_(population))
            .group_by(PostingSkill.priority)
        )
    ).all()
    return {
        str(priority) if priority is not None else "unspecified": int(count)
        for priority, count in rows
    }


async def _skill_density(db: AsyncSession, population) -> tuple[int, int]:
    row = (
        await db.execute(
            select(
                func.count(func.distinct(PostingSkill.posting_id)),
                func.count(PostingSkill.id),
            ).where(PostingSkill.posting_id.in_(population))
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


# --------------------------------------------------------------- breakdown


DIMENSIONS = (
    "seniority",
    "work_mode",
    "employment",
    "contract",
    "education",
    "source",
    "location",
    "org",
    "family",
)


async def breakdown(
    db: AsyncSession,
    *,
    dimension: str,
    window: str = "30d",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status_basis: str = "all",
    limit: int = 20,
    now: datetime | None = None,
) -> PostingStatsBreakdown:
    """One dimension of market structure: grouped counts with share and
    delta. ``location`` groups on the JSON country, ``org`` collapses
    ``org_id`` with the raw-label fallback and ``family`` rolls
    ``catalog_job_id`` up to the family path (``unmapped`` bucket)."""
    _check_basis(status_basis)
    if dimension not in DIMENSIONS:
        raise ValidationError("dimension must be one of: " + ", ".join(DIMENSIONS))
    ctx = window_context(window, date_from, date_to, now)
    limit = max(1, min(limit, BREAKDOWN_LIMIT_MAX))
    total = await _count(db, current_conditions(ctx, status_basis))
    counts = await _breakdown_counts(db, dimension, current_conditions(ctx, status_basis))
    prev_counts = (
        await _breakdown_counts(db, dimension, prev_conditions(ctx, status_basis))
        if ctx.prev_start is not None
        else {}
    )

    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    kept = ordered[:limit]
    rest = ordered[limit:]
    rows = [_breakdown_row(key, count, total, prev_counts.get(key, 0)) for key, count in kept]
    if rest:
        rows.append(
            _breakdown_row(
                BREAKDOWN_OTHER,
                sum(count for _key, count in rest),
                total,
                sum(prev_counts.get(key, 0) for key, _count in rest),
            )
        )
    return PostingStatsBreakdown(
        as_of=ctx.as_of,
        window=ctx.window,
        status_basis=cast(StatusBasis, status_basis),
        start=ctx.start,
        end=ctx.end,
        dimension=dimension,
        total=total,
        rows=rows,
    )


def _breakdown_row(key: str, count: int, total: int, prev: int) -> BreakdownRowOut:
    this_delta = delta(count, prev)
    return BreakdownRowOut(
        key=key,
        count=count,
        share=round(count / total, 4) if total else 0.0,
        prev=prev,
        delta_pct=this_delta.delta_pct,
        trend=this_delta.trend,
    )


async def _breakdown_counts(db: AsyncSession, dimension: str, conditions: list) -> dict[str, int]:
    query = select(JobPosting)
    column: Any
    if dimension == "location":
        column = func.coalesce(JobPosting.location["country"].as_string(), UNMAPPED)
    elif dimension == "org":
        query = query.outerjoin(Organization, Organization.id == JobPosting.org_id)
        column = func.coalesce(Organization.name, JobPosting.org, UNMAPPED)
    elif dimension == "family":
        query = query.outerjoin(Job, Job.id == JobPosting.catalog_job_id).outerjoin(
            JobFamily, JobFamily.id == Job.family_id
        )
        column = func.coalesce(JobFamily.path, UNMAPPED)
    elif dimension == "source":
        query = query.outerjoin(JobSource, JobSource.id == JobPosting.source_id)
        column = func.coalesce(JobSource.key, UNMAPPED)
    else:
        column = {
            "seniority": JobPosting.seniority,
            "work_mode": JobPosting.onsite_policy,
            "employment": JobPosting.employment_type,
            "contract": JobPosting.contract_type,
            "education": JobPosting.education_level,
        }[dimension]
        column = func.coalesce(column, UNMAPPED)
    rows = (
        await db.execute(
            query.with_only_columns(column, func.count(JobPosting.id))
            .where(*conditions)
            .group_by(column)
        )
    ).all()
    counts: dict[str, int] = {}
    for key, count in rows:
        label = str(key) if key is not None and str(key).strip() else UNMAPPED
        counts[label] = counts.get(label, 0) + int(count)
    return counts


# ------------------------------------------------------------------ salary


async def salary(
    db: AsyncSession,
    *,
    window: str = "30d",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status_basis: str = "all",
    now: datetime | None = None,
) -> PostingStatsSalary:
    """Per-currency salary statistics on the annualized normalized basis
    (no FX conversion, no gross/net mixing). One representative value
    per posting (the midpoint of its normalized range); bands are
    suppressed below :data:`SALARY_THIN_FLOOR` disclosed samples."""
    _check_basis(status_basis)
    ctx = window_context(window, date_from, date_to, now)
    conditions = current_conditions(ctx, status_basis)
    total = await _count(db, conditions)
    rows = (
        await db.execute(
            select(
                JobPosting.salary_currency,
                JobPosting.salary_normalized_min,
                JobPosting.salary_normalized_max,
                JobPosting.salary_period,
                JobPosting.seniority,
            )
            .where(
                *conditions,
                or_(
                    JobPosting.salary_normalized_min.is_not(None),
                    JobPosting.salary_normalized_max.is_not(None),
                ),
            )
            .limit(SALARY_SAMPLE_LIMIT)
        )
    ).all()

    by_currency: dict[str, list[tuple[float, str | None, str | None]]] = {}
    for currency, norm_min, norm_max, period, seniority_value in rows:
        values = [float(v) for v in (norm_min, norm_max) if v is not None]
        representative = sum(values) / len(values)
        key = currency.upper() if currency else "unspecified"
        by_currency.setdefault(key, []).append((representative, period, seniority_value))

    currencies = [
        _salary_currency(currency, entries, total)
        for currency, entries in sorted(by_currency.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    primary = currencies[0].currency if currencies else None
    return PostingStatsSalary(
        as_of=ctx.as_of,
        window=ctx.window,
        status_basis=cast(StatusBasis, status_basis),
        start=ctx.start,
        end=ctx.end,
        primary_currency=primary,
        currencies=currencies,
    )


def _salary_currency(
    currency: str, entries: list[tuple[float, str | None, str | None]], total: int
) -> SalaryCurrencyOut:
    values = sorted(entry[0] for entry in entries)
    disclosed = len(values)
    thin = disclosed < SALARY_THIN_FLOOR
    periods: dict[str, int] = {}
    for _value, period, _seniority in entries:
        key = period or "unspecified"
        periods[key] = periods.get(key, 0) + 1
    per_seniority: dict[str, list[float]] = {}
    for value, _period, seniority_value in entries:
        per_seniority.setdefault(seniority_value or "unspecified", []).append(value)
    by_seniority = [
        SalarySeniorityOut(
            seniority=key,
            count=len(group),
            median=None if len(group) < SALARY_THIN_FLOOR else round(_percentile(group, 0.5), 2),
        )
        for key, group in sorted(per_seniority.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    return SalaryCurrencyOut(
        currency=currency,
        disclosed=disclosed,
        coverage=round(disclosed / total, 4) if total else 0.0,
        thin_sample=thin,
        p25=None if thin else round(_percentile(values, 0.25), 2),
        p50=None if thin else round(_percentile(values, 0.5), 2),
        p75=None if thin else round(_percentile(values, 0.75), 2),
        histogram=_histogram(values),
        by_seniority=by_seniority,
        period_basis=periods,
    )


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _histogram(values: list[float]) -> list[SalaryBucketOut]:
    if not values:
        return []
    low, high = min(values), max(values)
    if low == high:
        return [SalaryBucketOut(floor=round(low, 2), ceiling=round(high, 2), count=len(values))]
    width = (high - low) / SALARY_HISTOGRAM_BUCKETS
    buckets = [
        SalaryBucketOut(
            floor=round(low + index * width, 2),
            ceiling=round(low + (index + 1) * width, 2),
            count=0,
        )
        for index in range(SALARY_HISTOGRAM_BUCKETS)
    ]
    for value in values:
        index = min(int((value - low) / width), SALARY_HISTOGRAM_BUCKETS - 1)
        buckets[index].count += 1
    return buckets


# ---------------------------------------------------------------- insights


async def _insights(db: AsyncSession, ctx: WindowContext, status_basis: str) -> list[InsightOut]:
    """Deterministic anomaly cards (H2): trailing-baseline z-scores over
    the same aggregates — volume, per-slice shares and the leading skill
    — capped at :data:`INSIGHT_LIMIT`. No AI, no free text."""
    if ctx.start is None or ctx.span is None or ctx.span <= timedelta(0):
        return []
    span = ctx.span
    interval = case(
        *[
            (effective_posted_expr() >= ctx.start - span * index, index)
            for index in range(INSIGHT_TRAILING_WINDOWS + 1)
        ],
        else_=INSIGHT_TRAILING_WINDOWS + 1,
    )
    base_conditions = _conditions(
        status_basis,
        ctx.start - span * INSIGHT_TRAILING_WINDOWS,
        ctx.end,
        bounded=ctx.window == "custom",
    )

    totals_rows = (
        await db.execute(
            select(interval, func.count(JobPosting.id)).where(*base_conditions).group_by(interval)
        )
    ).all()
    totals = {int(idx): int(count) for idx, count in totals_rows}
    series = [totals.get(index, 0) for index in range(INSIGHT_TRAILING_WINDOWS + 1)]
    current, trailing = series[0], series[1:]
    cards: list[tuple[float, InsightOut]] = []
    z = _zscore(current, trailing)
    if abs(z) >= INSIGHT_Z and max(current, sum(trailing) / len(trailing)) >= INSIGHT_MIN_COUNT:
        mean = sum(trailing) / len(trailing)
        cards.append(
            (
                abs(z),
                InsightOut(
                    kind="volume",
                    subject="postings",
                    delta_pct=round((current - mean) / mean * 100, 1) if mean else None,
                    baseline=round(mean, 2),
                    text_key="insights.volume_high" if current >= mean else "insights.volume_low",
                ),
            )
        )

    for _dimension, column in (
        ("work_mode", JobPosting.onsite_policy),
        ("seniority", JobPosting.seniority),
        ("employment", JobPosting.employment_type),
    ):
        rows = (
            await db.execute(
                select(interval, column, func.count(JobPosting.id))
                .where(*base_conditions)
                .group_by(interval, column)
            )
        ).all()
        per_slice: dict[str, list[int]] = {}
        for idx, value, count in rows:
            per_slice.setdefault(
                str(value) if value is not None else UNMAPPED, [0] * (INSIGHT_TRAILING_WINDOWS + 1)
            )[int(idx)] += int(count)
        for subject, counts in per_slice.items():
            shares = [
                counts[index] / totals[index] if totals.get(index) else 0.0
                for index in range(INSIGHT_TRAILING_WINDOWS + 1)
            ]
            share_z = _zscore(shares[0], shares[1:])
            if abs(share_z) < INSIGHT_Z or counts[0] < INSIGHT_MIN_COUNT:
                continue
            if totals.get(0, 0) < INSIGHT_MIN_COUNT:
                continue
            mean_share = sum(shares[1:]) / len(shares[1:])
            cards.append(
                (
                    abs(share_z),
                    InsightOut(
                        kind="share",
                        subject=subject,
                        delta_pct=round((shares[0] - mean_share) / mean_share * 100, 1)
                        if mean_share
                        else None,
                        baseline=round(mean_share, 4),
                        text_key="insights.share_high"
                        if shares[0] >= mean_share
                        else "insights.share_low",
                    ),
                )
            )

    skill_rows = (
        await db.execute(
            select(interval, Skill.key, func.count(func.distinct(PostingSkill.posting_id)))
            .select_from(JobPosting)
            .join(PostingSkill, PostingSkill.posting_id == JobPosting.id)
            .join(Skill, Skill.id == PostingSkill.skill_id)
            .where(*base_conditions)
            .group_by(interval, Skill.key)
            .limit(500)
        )
    ).all()
    skill_series: dict[str, list[int]] = {}
    for idx, key, count in skill_rows:
        skill_series.setdefault(key, [0] * (INSIGHT_TRAILING_WINDOWS + 1))[int(idx)] += int(count)
    leader_now = _leader(skill_series, 0)
    leader_prev = _leader(skill_series, 1)
    if leader_now and leader_prev and leader_now != leader_prev:
        counts = skill_series[leader_now]
        lead_z = _zscore(counts[0], counts[1:])
        mean = sum(counts[1:]) / len(counts[1:])
        if abs(lead_z) >= INSIGHT_Z and max(counts[0], mean) >= INSIGHT_MIN_COUNT:
            cards.append(
                (
                    abs(lead_z),
                    InsightOut(
                        kind="skill_lead",
                        subject=leader_now,
                        delta_pct=round((counts[0] - mean) / mean * 100, 1) if mean else None,
                        baseline=round(mean, 2),
                        text_key="insights.skill_lead",
                    ),
                )
            )

    cards.sort(key=lambda item: (-item[0], item[1].kind, item[1].subject))
    return [card for _score, card in cards[:INSIGHT_LIMIT]]


def _leader(skill_series: dict[str, list[int]], index: int) -> str | None:
    ranked = sorted(
        (
            (key, counts[index])
            for key, counts in skill_series.items()
            if counts[index] >= SKILL_TREND_FLOOR
        ),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return ranked[0][0] if ranked else None


def _zscore(current: float, trailing: Sequence[float]) -> float:
    mean = sum(trailing) / len(trailing)
    variance = sum((value - mean) ** 2 for value in trailing) / len(trailing)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0 if current == mean else float("inf")
    return (current - mean) / std
