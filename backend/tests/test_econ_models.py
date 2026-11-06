"""Economic-context models (plan 127 §3.0): pack → series → observation
roundtrip, evidence JSONB, revision history, and the scenario/claim
registries."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Claim,
    ClaimEvent,
    EconObservation,
    EconPack,
    EconSeries,
    GeoRegion,
    Scenario,
    ScenarioPoint,
)


async def _stack(db):
    region = GeoRegion(kind="country", code="DE", country="DE", label="Germany")
    db.add(region)
    await db.flush()
    pack = EconPack(
        provider="world_bank",
        kind="live",
        pack_id="world-bank-wdi",
        version="2026.10",
        dataset_vintage="2025",
        license_class="open_data",
        coverage={"granularity": "country"},
        manifest={"pack_format": "econ-pack/v1"},
        status="active",
    )
    db.add(pack)
    await db.flush()
    series = EconSeries(
        econ_pack_id=pack.id,
        series_key="de.household_consumption",
        dataset_code="NE.CON.PRVT.ZS",
        metric="household_consumption_share",
        unit="percent",
        freq="annual",
        geo_region_id=region.id,
        coverage_level="country",
        license_class="open_data",
        provider_dims={"indicator": "NE.CON.PRVT.ZS"},
    )
    db.add(series)
    await db.flush()
    return region, pack, series


def _observation(series_id, *, revision=0):
    return EconObservation(
        series_id=series_id,
        period=date(2024, 1, 1),
        value=Decimal("52.4000"),
        vintage="2025",
        revision=revision,
        observed_at=datetime(2026, 10, 25, tzinfo=UTC),
        provenance_tier="extracted",
        publisher="World Bank",
        evidence={"span": "Household consumption 52.4%", "locator": "table 2.1"},
        source_hash="a" * 64,
        verified_at=datetime(2026, 10, 25, tzinfo=UTC),
    )


async def test_pack_series_observation_roundtrip(db):
    _, pack, series = await _stack(db)
    observation = _observation(series.id)
    db.add(observation)
    await db.commit()

    loaded = await db.get(EconObservation, observation.id)
    assert loaded is not None
    assert loaded.series_id == series.id
    assert loaded.provenance_tier == "extracted"
    assert loaded.value == Decimal("52.4000")
    assert loaded.evidence["span"] == "Household consumption 52.4%"
    assert loaded.verified_at is not None
    assert pack.status == "active"


async def test_observation_revision_uniqueness_keeps_history(db):
    _, _, series = await _stack(db)
    db.add(_observation(series.id, revision=0))
    await db.flush()

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(_observation(series.id, revision=0))
            await db.flush()

    db.add(_observation(series.id, revision=1))
    await db.commit()


async def test_pack_delete_cascades_series_and_observations(db):
    _, pack, series = await _stack(db)
    db.add(_observation(series.id))
    await db.commit()

    await db.delete(pack)
    await db.commit()

    assert await db.scalar(select(func.count()).select_from(EconSeries)) == 0
    assert await db.scalar(select(func.count()).select_from(EconObservation)) == 0


async def test_scenario_and_claim_registries_roundtrip(db):
    scenario = Scenario(
        key="capital_ownership_shift",
        title="Capital-ownership shift",
        thesis="If the price of human time falls, ownership captures the residual.",
        scope_kind="global",
        status="proposed",
        assumptions={"substitution_pace": "fast"},
        indicators={"wage_share": {"threshold": 0.5}},
        falsifiers="Wage share of GDP rises for three consecutive years.",
    )
    claim = Claim(
        key="salaries-irrelevant-by-2035",
        text="Salaries will become irrelevant by 2035.",
        testable_form="Real compensation falls while employment holds.",
        status="open",
        evidence_refs={"series": ["wage_share"]},
    )
    db.add_all([scenario, claim])
    await db.flush()

    point = ScenarioPoint(
        scenario_id=scenario.id,
        metric="demand_index",
        horizon=date(2035, 1, 1),
        p10=Decimal("0.80"),
        p50=Decimal("1.10"),
        p90=Decimal("1.50"),
    )
    event = ClaimEvent(claim_id=claim.id, action="accept", note="Checked against OEWS.")
    db.add_all([point, event])
    await db.commit()

    loaded = await db.get(Scenario, scenario.id)
    assert loaded is not None
    assert loaded.assumptions["substitution_pace"] == "fast"
    assert loaded.status == "proposed"
    assert await db.get(ClaimEvent, event.id) is not None
