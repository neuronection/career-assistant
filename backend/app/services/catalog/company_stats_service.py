"""Company-side market statistics (plan 170 slice 1).

The `/companies/stats/*` shapes over organizations joined to their
postings — derived at read time on the same window and status-basis rules
as the postings stats (the ``company_service`` derived-hiring
precedent). Unresolved (org-less) postings never form a company row.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company_model import CompanyProfile
from app.models.experience_model import Organization
from app.models.posting_model import JobPosting
from app.schemas.stats import (
    CompanyHiringOut,
    CompanyStatsOverview,
    CompanyStatsSummary,
    IndustryMixOut,
    OpeningsBucketOut,
    StatusBasis,
)
from app.services.analytics.deltas import delta
from app.services.analytics.time_buckets import effective_posted_expr
from app.services.postings.stats_service import (
    WindowContext,
    basis_conditions,
    current_conditions,
    prev_conditions,
    window_context,
)

COMPANY_LIMIT_MAX = 50
INDUSTRY_LIMIT = 12
OPENINGS_BUCKETS = (("1", 1, 1), ("2-5", 2, 5), ("6-20", 6, 20), ("20+", 21, None))


def _org_conditions(status_basis: str) -> list:
    conditions = basis_conditions(status_basis)
    conditions.append(JobPosting.org_id.is_not(None))
    return conditions


def _first_in_range(ctx: WindowContext, stamp: datetime) -> bool:
    if ctx.start is None:
        return False
    if ctx.window == "custom":
        return ctx.start <= stamp < ctx.end
    return stamp >= ctx.start


async def summary(
    db: AsyncSession,
    *,
    window: str = "30d",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status_basis: str = "open",
    now: datetime | None = None,
) -> CompanyStatsSummary:
    """The companies pulse: hiring companies over the basis population
    and companies whose first posting landed in the window (with its
    equal-length predecessor delta)."""
    ctx = window_context(window, date_from, date_to, now)
    hiring = int(
        (
            await db.execute(
                select(func.count(func.distinct(JobPosting.org_id))).where(
                    *_org_conditions(status_basis)
                )
            )
        ).scalar_one()
    )
    firsts = (
        await db.execute(
            select(JobPosting.org_id, func.min(effective_posted_expr()))
            .where(*_org_conditions(status_basis))
            .group_by(JobPosting.org_id)
        )
    ).all()
    count = 0
    prev = 0
    for _org_id, stamp in firsts:
        if stamp is None:
            continue
        if _first_in_range(ctx, stamp):
            count += 1
        elif (
            ctx.prev_start is not None
            and ctx.start is not None
            and ctx.prev_start <= stamp < ctx.start
        ):
            prev += 1
    return CompanyStatsSummary(
        as_of=ctx.as_of,
        window=ctx.window,
        status_basis=cast(StatusBasis, status_basis),
        start=ctx.start,
        end=ctx.end,
        companies_hiring=hiring,
        new_companies=delta(count, prev),
    )


async def overview(
    db: AsyncSession,
    *,
    window: str = "30d",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status_basis: str = "open",
    limit: int = 10,
    now: datetime | None = None,
) -> CompanyStatsOverview:
    """Top hiring companies (volume + in-window delta), the industry mix
    over active postings and the openings-per-company histogram."""
    ctx = window_context(window, date_from, date_to, now)
    limit = max(1, min(limit, COMPANY_LIMIT_MAX))

    total_rows = (
        await db.execute(
            select(JobPosting.org_id, func.count(JobPosting.id))
            .where(*_org_conditions(status_basis))
            .group_by(JobPosting.org_id)
        )
    ).all()
    open_counts = {org_id: int(count) for org_id, count in total_rows}

    new_counts = await _window_counts(db, status_basis, current_conditions(ctx, status_basis))
    prev_counts = (
        await _window_counts(db, status_basis, prev_conditions(ctx, status_basis))
        if ctx.prev_start is not None
        else {}
    )

    names = await _org_names(db, list(open_counts))
    ranked = sorted(open_counts.items(), key=lambda kv: (-kv[1], names.get(kv[0], ("", ""))[1]))
    top_hiring = [
        CompanyHiringOut(
            key=names.get(org_id, (str(org_id), str(org_id)))[0],
            name=names.get(org_id, (str(org_id), str(org_id)))[1],
            open_postings=count,
            new_in_range=delta(new_counts.get(org_id, 0), prev_counts.get(org_id, 0)),
        )
        for org_id, count in ranked[:limit]
    ]

    total_companies = len(open_counts)
    industry_mix = [
        IndustryMixOut(
            key=tag,
            count=count,
            share=round(count / total_companies, 4) if total_companies else 0.0,
        )
        for tag, count in await _industry_mix(db, list(open_counts))
    ]

    histogram = [
        OpeningsBucketOut(
            bucket=bucket,
            count=sum(
                1
                for count in open_counts.values()
                if count >= low and (high is None or count <= high)
            ),
        )
        for bucket, low, high in OPENINGS_BUCKETS
    ]

    return CompanyStatsOverview(
        as_of=ctx.as_of,
        window=ctx.window,
        status_basis=cast(StatusBasis, status_basis),
        start=ctx.start,
        end=ctx.end,
        top_hiring=top_hiring,
        industry_mix=industry_mix,
        openings_histogram=histogram,
    )


async def _window_counts(db: AsyncSession, status_basis: str, extra: list) -> dict:
    rows = (
        await db.execute(
            select(JobPosting.org_id, func.count(JobPosting.id))
            .where(*_org_conditions(status_basis), *extra)
            .group_by(JobPosting.org_id)
        )
    ).all()
    return {org_id: int(count) for org_id, count in rows}


async def _org_names(db: AsyncSession, org_ids: list) -> dict:
    if not org_ids:
        return {}
    rows = (
        await db.execute(
            select(Organization.id, Organization.key, Organization.name).where(
                Organization.id.in_(org_ids)
            )
        )
    ).all()
    return {org_id: (key, name) for org_id, key, name in rows}


async def _industry_mix(db: AsyncSession, org_ids: list) -> list[tuple[str, int]]:
    if not org_ids:
        return []
    rows = (
        await db.execute(
            select(CompanyProfile.organization_id, CompanyProfile.industry_tags).where(
                CompanyProfile.organization_id.in_(org_ids)
            )
        )
    ).all()
    counts: dict[str, set] = {}
    for org_id, tags in rows:
        for tag in tags or []:
            counts.setdefault(str(tag), set()).add(org_id)
    ranked = sorted(counts.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:INDUSTRY_LIMIT]
    return [(tag, len(orgs)) for tag, orgs in ranked]
