"""Coverage levels (plan 127 §3.1): the most specific active series wins,
no data is ``None`` (never a silent estimate), and EU vs US profiles
degrade honestly."""

import uuid

from app.models.econ_model import EconPack, EconSeries, GeoRegion
from app.models.enums import CoverageLevel
from app.services.econ.coverage import resolve_coverage
from app.services.econ.regions import resolve_region


async def _region(db, *, kind="country", code="ZZ", country="ZZ", label="Zetland"):
    region = GeoRegion(kind=kind, code=code, country=country, label=label)
    db.add(region)
    await db.flush()
    return region


async def _pack(db, *, status="active", provider="world_bank", vintage="2025", pack_id=None):
    pack = EconPack(
        provider=provider,
        kind="live",
        pack_id=pack_id or f"{provider}-{uuid.uuid4().hex[:8]}",
        version="1.0",
        dataset_vintage=vintage,
        license_class="open_data",
        coverage={},
        manifest={"pack_format": "econ-pack/v1"},
        status=status,
    )
    db.add(pack)
    await db.flush()
    return pack


async def _series(
    db,
    *,
    pack,
    region,
    coverage,
    sector=None,
    occ=None,
    license_class="open_data",
):
    series = EconSeries(
        econ_pack_id=pack.id,
        series_key=f"{pack.pack_id}.{uuid.uuid4().hex[:8]}",
        metric="value",
        unit="index",
        freq="annual",
        geo_region_id=region.id,
        sector_code=sector,
        occ_code=occ,
        coverage_level=coverage,
        license_class=license_class,
    )
    db.add(series)
    await db.flush()
    return series


async def test_most_specific_level_wins_and_sources_are_collected(db):
    region = await _region(db)
    pack = await _pack(db, provider="world_bank", vintage="2025")
    await _series(db, pack=pack, region=region, coverage="country")
    await _series(db, pack=pack, region=region, coverage="regional")
    await _series(db, pack=pack, region=region, coverage="full", license_class="public_domain")

    summary = await resolve_coverage(db, geo_region_id=region.id)
    assert summary.level == CoverageLevel.FULL
    assert summary.series_count == 3
    assert summary.providers == ["world_bank"]
    assert summary.vintages == ["2025"]
    assert summary.license_classes == ["open_data", "public_domain"]


async def test_no_series_means_none_not_an_estimate(db):
    region = await _region(db)
    summary = await resolve_coverage(db, geo_region_id=region.id)
    assert summary.level is None
    assert summary.series_count == 0
    assert summary.providers == []
    assert summary.vintages == []
    assert summary.license_classes == []


async def test_inactive_packs_do_not_count(db):
    region = await _region(db)
    proposed = await _pack(db, status="proposed")
    await _series(db, pack=proposed, region=region, coverage="full")
    superseded = await _pack(db, status="superseded")
    await _series(db, pack=superseded, region=region, coverage="full")

    summary = await resolve_coverage(db, geo_region_id=region.id)
    assert summary.level is None
    assert summary.series_count == 0


async def test_sector_filter_narrows_coverage(db):
    region = await _region(db)
    pack = await _pack(db)
    await _series(db, pack=pack, region=region, coverage="full", sector="C")
    await _series(db, pack=pack, region=region, coverage="country", sector="M")
    await _series(db, pack=pack, region=region, coverage="full")

    unfiltered = await resolve_coverage(db, geo_region_id=region.id)
    assert unfiltered.level == CoverageLevel.FULL
    assert unfiltered.series_count == 3

    manufacturing = await resolve_coverage(db, geo_region_id=region.id, sector_code="M")
    assert manufacturing.level == CoverageLevel.COUNTRY
    assert manufacturing.series_count == 1

    missing = await resolve_coverage(db, geo_region_id=region.id, sector_code="X")
    assert missing.level is None


async def test_occ_filter_is_exact(db):
    region = await _region(db)
    pack = await _pack(db)
    await _series(db, pack=pack, region=region, coverage="regional", occ="2510")
    await _series(db, pack=pack, region=region, coverage="country", occ="5220")

    software = await resolve_coverage(db, geo_region_id=region.id, occ_code="2510")
    assert software.level == CoverageLevel.REGIONAL
    assert software.series_count == 1

    assert (await resolve_coverage(db, geo_region_id=region.id, occ_code="9999")).level is None


def test_rank_maps_cover_every_enum_member():
    from app.models.enums import CoverageLevel, GeoRegionKind
    from app.services.econ.coverage import _COVERAGE_RANK
    from app.services.econ.regions import _KIND_SPECIFICITY

    assert set(_COVERAGE_RANK) == set(CoverageLevel)
    assert set(_KIND_SPECIFICITY) == set(GeoRegionKind)


async def test_eu_and_us_profiles_degrade_honestly(db):
    await _region(db, kind="country", code="US", country="US", label="United States")
    boston = await _region(
        db, kind="metro", code="14460", country="US", label="Boston-Cambridge-Newton"
    )
    await _region(db, kind="country", code="DE", country="DE", label="Germany")
    stuttgart = await _region(db, kind="nuts2", code="DE11", country="DE", label="Stuttgart")

    us_pack = await _pack(db, provider="bls", vintage="2025", pack_id="bls-oews")
    await _series(db, pack=us_pack, region=boston, coverage="full")
    de_pack = await _pack(db, provider="eurostat", vintage="2024", pack_id="eurostat-ses")
    await _series(db, pack=de_pack, region=stuttgart, coverage="country")

    us_profile = await resolve_region(db, country="United States", city="Boston-Cambridge-Newton")
    assert us_profile.status == "resolved"
    assert us_profile.region is not None
    us_summary = await resolve_coverage(db, geo_region_id=us_profile.region.id)
    assert us_summary.level == CoverageLevel.FULL
    assert us_summary.providers == ["bls"]

    de_profile = await resolve_region(db, country="Germany", city="Stuttgart")
    assert de_profile.status == "resolved"
    assert de_profile.region is not None
    de_summary = await resolve_coverage(db, geo_region_id=de_profile.region.id)
    assert de_summary.level == CoverageLevel.COUNTRY
    assert de_summary.providers == ["eurostat"]
