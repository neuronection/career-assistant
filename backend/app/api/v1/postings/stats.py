"""Market statistics surface (plan 170 slice 1).

`/postings/stats/*` and `/companies/stats/*` — user-scope reads (no
admin) over the live aggregates. Query params follow the audit
``RangeFilter`` convention: a preset ``window`` (``from``/``to`` win when
given) and an explicit ``status_basis``; datetimes normalize to UTC at
the service boundary.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.stats import (
    ClockworkOut,
    CompanyStatsOverview,
    CompanyStatsSummary,
    PostingStatsBreakdown,
    PostingStatsOverview,
    PostingStatsSalary,
    PostingStatsSkills,
    PostingStatsSummary,
    PostingStatsTimeseries,
)
from app.services.catalog import company_stats_service
from app.services.deps import get_current_user
from app.services.postings import stats_service

router = APIRouter(tags=["postings-stats"], dependencies=[Depends(get_current_user)])

WINDOW_QUERY = Query(default="30d", pattern="^(24h|7d|30d|90d|all)$")
BASIS_QUERY = Query(default="all", pattern="^(open|all)$")
SUMMARY_BASIS_QUERY = Query(default="open", pattern="^(open|all)$")
FROM_QUERY = Query(default=None, alias="from")
TO_QUERY = Query(default=None, alias="to")


@router.get("/postings/stats/summary", response_model=PostingStatsSummary)
async def postings_stats_summary(
    status_basis: str = SUMMARY_BASIS_QUERY,
    db: AsyncSession = Depends(get_db),
) -> PostingStatsSummary:
    """The pulse: fixed-window counts with deltas, sparkline and source
    freshness. Defaults to the open basis — the explore totals' basis."""
    return await stats_service.summary(db, status_basis=status_basis)


@router.get("/postings/stats/overview", response_model=PostingStatsOverview)
async def postings_stats_overview(
    window: str = WINDOW_QUERY,
    date_from: datetime | None = FROM_QUERY,
    date_to: datetime | None = TO_QUERY,
    status_basis: str = BASIS_QUERY,
    db: AsyncSession = Depends(get_db),
) -> PostingStatsOverview:
    """In-range KPIs, the status mix, coverage chips and the
    deterministic insights strip."""
    return await stats_service.overview(
        db, window=window, date_from=date_from, date_to=date_to, status_basis=status_basis
    )


@router.get("/postings/stats/timeseries", response_model=PostingStatsTimeseries)
async def postings_stats_timeseries(
    window: str = WINDOW_QUERY,
    date_from: datetime | None = FROM_QUERY,
    date_to: datetime | None = TO_QUERY,
    bucket: str | None = Query(default=None, pattern="^(hour|day|week|month)$"),
    split: str | None = Query(
        default=None, pattern="^(status|source|work_mode|seniority|employment)$"
    ),
    status_basis: str = BASIS_QUERY,
    db: AsyncSession = Depends(get_db),
) -> PostingStatsTimeseries:
    """Volume over time with the previous-period ghost, ingestion counts
    and an optional split series."""
    return await stats_service.timeseries(
        db,
        window=window,
        date_from=date_from,
        date_to=date_to,
        bucket=bucket,
        split=split,
        status_basis=status_basis,
    )


@router.get("/postings/stats/skills", response_model=PostingStatsSkills)
async def postings_stats_skills(
    window: str = WINDOW_QUERY,
    date_from: datetime | None = FROM_QUERY,
    date_to: datetime | None = TO_QUERY,
    status_basis: str = BASIS_QUERY,
    limit: int = Query(default=15, ge=1, le=15),
    db: AsyncSession = Depends(get_db),
) -> PostingStatsSkills:
    """Top asked skills with trends, category mix, level histogram and
    priority mix."""
    return await stats_service.skills(
        db,
        window=window,
        date_from=date_from,
        date_to=date_to,
        status_basis=status_basis,
        limit=limit,
    )


@router.get("/postings/stats/breakdown", response_model=PostingStatsBreakdown)
async def postings_stats_breakdown(
    dimension: str = Query(
        pattern="^(seniority|work_mode|employment|contract|education|source|location|org|family)$"
    ),
    window: str = WINDOW_QUERY,
    date_from: datetime | None = FROM_QUERY,
    date_to: datetime | None = TO_QUERY,
    status_basis: str = BASIS_QUERY,
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> PostingStatsBreakdown:
    """One dimension of market structure — grouped counts with share and
    delta."""
    return await stats_service.breakdown(
        db,
        dimension=dimension,
        window=window,
        date_from=date_from,
        date_to=date_to,
        status_basis=status_basis,
        limit=limit,
    )


@router.get("/postings/stats/clockwork", response_model=ClockworkOut)
async def postings_stats_clockwork(
    window: str = WINDOW_QUERY,
    date_from: datetime | None = FROM_QUERY,
    date_to: datetime | None = TO_QUERY,
    status_basis: str = BASIS_QUERY,
    db: AsyncSession = Depends(get_db),
) -> ClockworkOut:
    """The weekday x hour posting clock over the window population —
    always UTC."""
    return await stats_service.clockwork(
        db, window=window, date_from=date_from, date_to=date_to, status_basis=status_basis
    )


@router.get("/postings/stats/salary", response_model=PostingStatsSalary)
async def postings_stats_salary(
    window: str = WINDOW_QUERY,
    date_from: datetime | None = FROM_QUERY,
    date_to: datetime | None = TO_QUERY,
    status_basis: str = BASIS_QUERY,
    db: AsyncSession = Depends(get_db),
) -> PostingStatsSalary:
    """Per-currency salary bands, histograms and per-seniority medians on
    the annualized normalized basis."""
    return await stats_service.salary(
        db, window=window, date_from=date_from, date_to=date_to, status_basis=status_basis
    )


@router.get("/companies/stats/summary", response_model=CompanyStatsSummary)
async def companies_stats_summary(
    window: str = WINDOW_QUERY,
    date_from: datetime | None = FROM_QUERY,
    date_to: datetime | None = TO_QUERY,
    status_basis: str = SUMMARY_BASIS_QUERY,
    db: AsyncSession = Depends(get_db),
) -> CompanyStatsSummary:
    """Companies hiring and companies new in the window."""
    return await company_stats_service.summary(
        db, window=window, date_from=date_from, date_to=date_to, status_basis=status_basis
    )


@router.get("/companies/stats/overview", response_model=CompanyStatsOverview)
async def companies_stats_overview(
    window: str = WINDOW_QUERY,
    date_from: datetime | None = FROM_QUERY,
    date_to: datetime | None = TO_QUERY,
    status_basis: str = SUMMARY_BASIS_QUERY,
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> CompanyStatsOverview:
    """Top hiring companies, the industry mix and the openings-per-company
    histogram."""
    return await company_stats_service.overview(
        db,
        window=window,
        date_from=date_from,
        date_to=date_to,
        status_basis=status_basis,
        limit=limit,
    )
