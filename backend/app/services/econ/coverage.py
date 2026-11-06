"""Coverage levels for a scope (plan 127 §3.1).

Derived from the series a scope can actually reach: the most specific
coverage any active pack declares wins (``full > regional > country >
modelled_estimate``). ``level is None`` means no data at all — the caller
renders "no data", never a silent estimate. Inactive packs (``proposed``,
``superseded``) never count.

Exact-region and exact-dimension only: a metro scope is not satisfied by
country-level series (hierarchy roll-up is a later slice), and a
sector/occupation miss is "no data", never an aggregate fallback.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.econ_model import EconPack, EconSeries
from app.models.enums import CoverageLevel, EconPackStatus
from app.schemas.econ import CoverageSummary

_COVERAGE_RANK = {
    CoverageLevel.FULL: 3,
    CoverageLevel.REGIONAL: 2,
    CoverageLevel.COUNTRY: 1,
    CoverageLevel.MODELLED_ESTIMATE: 0,
}


async def resolve_coverage(
    db: AsyncSession,
    *,
    geo_region_id: UUID,
    sector_code: str | None = None,
    occ_code: str | None = None,
) -> CoverageSummary:
    """The honest coverage summary for one place (optionally one sector/occupation)."""
    stmt = (
        select(
            EconSeries.coverage_level,
            EconSeries.license_class,
            EconPack.provider,
            EconPack.dataset_vintage,
        )
        .join(EconPack, EconPack.id == EconSeries.econ_pack_id)
        .where(
            EconPack.status == EconPackStatus.ACTIVE.value,
            EconSeries.geo_region_id == geo_region_id,
        )
    )
    if sector_code is not None:
        stmt = stmt.where(EconSeries.sector_code == sector_code)
    if occ_code is not None:
        stmt = stmt.where(EconSeries.occ_code == occ_code)
    rows = (await db.execute(stmt)).all()
    if not rows:
        return CoverageSummary(level=None, series_count=0)

    best = max(rows, key=lambda row: _COVERAGE_RANK[CoverageLevel(row.coverage_level)])
    return CoverageSummary(
        level=CoverageLevel(best.coverage_level),
        series_count=len(rows),
        providers=sorted({row.provider for row in rows}),
        vintages=sorted({row.dataset_vintage for row in rows if row.dataset_vintage}),
        license_classes=sorted({row.license_class for row in rows}),
    )
