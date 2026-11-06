"""Market statistics surface (plan 170 slice 1).

`/postings/stats/*` and `/companies/stats/*` — user-scope reads (no
admin) over the live aggregates. Query params follow the audit
``RangeFilter`` convention: a preset ``window`` (``from``/``to`` win when
given) and an explicit ``status_basis``; datetimes normalize to UTC at
the service boundary.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ValidationError
from app.schemas.stats import (
    BucketName,
    CompanyStatsOverview,
    CompanyStatsSummary,
    DashboardOut,
    DashboardQuery,
    PostingStatsBreakdown,
    PostingStatsSkills,
    PostingStatsSummary,
    StatusBasis,
)
from app.services.catalog import company_stats_service
from app.services.deps import get_current_user
from app.services.postings import stats_dashboard_service, stats_service

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


@router.get("/postings/stats/dashboard", response_model=DashboardOut)
async def postings_stats_dashboard(
    request: Request,
    response: Response,
    window: str = WINDOW_QUERY,
    date_from: datetime | None = FROM_QUERY,
    date_to: datetime | None = TO_QUERY,
    basis: StatusBasis = Query(default="all"),
    bucket: BucketName | None = Query(default=None),
    split: str | None = Query(
        default=None, pattern="^(status|source|work_mode|seniority|employment)$"
    ),
    dimension: str = Query(
        default="source",
        pattern="^(seniority|work_mode|employment|contract|education|source|location|org|family)$",
    ),
    cards: str | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    org: list[str] | None = Query(default=None),
    mapped_family: list[str] | None = Query(default=None),
    seniority: list[str] | None = Query(default=None),
    remote_policy: list[str] | None = Query(default=None),
    employment_type: list[str] | None = Query(default=None),
    contract: list[str] | None = Query(default=None),
    education_min: str | None = Query(default=None),
    city: str | None = Query(default=None),
    country: str | None = Query(default=None),
    skills: str | None = Query(default=None),
    skill_mode: str | None = Query(default=None),
    salary_min: float | None = Query(default=None),
    q: str | None = Query(default=None),
    hidden_include: bool = Query(default=False),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardOut:
    """The composite market tab: every requested card on one window, one
    basis and one compiled Explore filter set.

    The response carries a single ``as_of`` but that is one timestamp, not
    a snapshot: the cards run in one request under READ COMMITTED, so a
    source sync landing between two card queries is visible to the later
    one. Partial failures return 200 with a typed entry in ``errors`` —
    a null card is never silent. No caching: ``private, no-store`` (the
    payload is profile-scoped through the user's hidden postings).

    ``posted_within``/``posted_after`` are rejected — the dashboard window
    owns time; the frontend derives the list drill's ``posted_within``.
    ``hidden_include`` is an admin/debug escape hatch: for everyone else
    it is ignored so aggregates never count the caller's hidden rows.
    """
    for owned in ("posted_within", "posted_after"):
        if owned in request.query_params:
            raise ValidationError(f"{owned} is owned by the dashboard window")
    response.headers["Cache-Control"] = "private, no-store"

    raw: dict = {}
    for field_key, field_value in (
        ("source", source),
        ("org", org),
        ("mapped_family", mapped_family),
        ("seniority", seniority),
        ("remote_policy", remote_policy),
        ("employment_type", employment_type),
        ("contract", contract),
    ):
        if field_value:
            raw[field_key] = field_value
    for text_key, text_value in (
        ("education_min", education_min),
        ("city", city),
        ("country", country),
        ("skills", skills),
        ("skill_mode", skill_mode),
        ("q", q),
    ):
        if text_value:
            raw[text_key] = text_value
    if salary_min is not None:
        raw["salary_min"] = salary_min
    if hidden_include and user.is_admin:
        raw["hidden_include"] = True

    query = DashboardQuery(
        window=window,
        date_from=date_from,
        date_to=date_to,
        basis=basis,
        bucket=bucket,
        split=split,
        dimension=dimension,
        cards=cards.split(",") if cards else None,
    )
    return await stats_dashboard_service.dashboard(db, user.id, query, raw)


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
