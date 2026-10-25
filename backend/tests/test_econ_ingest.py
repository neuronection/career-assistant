"""Econ ingest (plan 127 §3.2): idempotent upserts, revision history,
vintage supersede, one region per place, and the license wall."""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.core.errors import ValidationError
from app.extensions.market_data import (
    ProviderGeo,
    ProviderObservation,
    ProviderResult,
    ProviderSeries,
)
from app.models.econ_model import EconObservation, EconPack, EconSeries, GeoRegion
from app.models.enums import CoverageLevel, LicenseClass
from app.services.econ.ingest import ingest_provider_result


def _result(
    *,
    version: str = "2024",
    values: tuple[float, float] = (50.4, 51.2),
    license_class: LicenseClass = LicenseClass.OPEN_DATA,
    pack_id: str = "wb-test",
) -> ProviderResult:
    return ProviderResult(
        provider="world_bank",
        pack_id=pack_id,
        version=version,
        dataset_vintage=version,
        license_class=license_class,
        coverage={"granularity": "country"},
        manifest={"pack_format": "econ-pack/v1", "publisher": "World Bank"},
        series=[
            ProviderSeries(
                series_key="DE.household_consumption_share",
                metric="household_consumption_share",
                unit="percent",
                geo=ProviderGeo(code="DE", country="DE", label="Germany"),
                coverage_level=CoverageLevel.COUNTRY,
                observations=[
                    ProviderObservation(period=date(2023, 1, 1), value=values[0]),
                    ProviderObservation(period=date(2024, 1, 1), value=values[1]),
                ],
            )
        ],
    )


async def test_ingest_is_idempotent(db):
    first = await ingest_provider_result(db, _result())
    assert first["series"] == 1
    assert first["observations"] == 2

    second = await ingest_provider_result(db, _result())
    assert second["series"] == 0
    assert second["observations"] == 0
    assert second["skipped"] == 2
    assert second["revisions"] == 0
    assert await db.scalar(select(func.count()).select_from(EconObservation)) == 2


async def test_changed_value_lands_as_a_new_revision_beside_the_old(db):
    await ingest_provider_result(db, _result(values=(50.4, 51.2)))
    updated = await ingest_provider_result(db, _result(values=(50.4, 52.0)))
    assert updated["revisions"] == 1

    rows = (
        (
            await db.execute(
                select(EconObservation)
                .where(EconObservation.period == date(2024, 1, 1))
                .order_by(EconObservation.revision)
            )
        )
        .scalars()
        .all()
    )
    assert [row.revision for row in rows] == [0, 1]
    assert [float(row.value) for row in rows] == [51.2, 52.0]
    assert {row.provenance_tier for row in rows} == {"official"}
    assert {row.publisher for row in rows} == {"World Bank"}


async def test_new_vintage_supersedes_the_previous_pack(db):
    await ingest_provider_result(db, _result(version="2024"))
    await ingest_provider_result(db, _result(version="2025"))

    packs = (await db.execute(select(EconPack).order_by(EconPack.version))).scalars().all()
    assert [(pack.version, pack.status) for pack in packs] == [
        ("2024", "superseded"),
        ("2025", "active"),
    ]
    assert await db.scalar(select(func.count()).select_from(EconSeries)) == 2


async def test_region_is_provisioned_once_per_place(db):
    await ingest_provider_result(db, _result())
    await ingest_provider_result(db, _result())

    regions = (await db.execute(select(GeoRegion))).scalars().all()
    assert len(regions) == 1
    assert (regions[0].kind, regions[0].code, regions[0].country) == ("country", "DE", "DE")
    assert regions[0].label == "Germany"


async def test_research_only_result_is_rejected_before_any_write(db):
    with pytest.raises(ValidationError, match="not ingestible"):
        await ingest_provider_result(db, _result(license_class=LicenseClass.RESEARCH_ONLY))
    assert await db.scalar(select(func.count()).select_from(EconPack)) == 0
