"""World Bank WDI provider (plan 127 §3.2): fixture-driven parsing and a
guarded-transport fetch — no live calls."""

import json

import pytest

from app.extensions.market_data import MarketDataError
from app.extensions.market_data_providers import (
    WorldBankConfig,
    WorldBankIndicator,
    WorldBankWdiProvider,
    parse_world_bank_payload,
)

PAYLOAD = json.dumps(
    [
        {
            "page": 1,
            "pages": 1,
            "per_page": 100,
            "total": 4,
            "sourceid": "2",
            "lastupdated": "2026-10-01",
        },
        [
            {
                "indicator": {"id": "NE.CON.PRVT.ZS", "value": "Household consumption"},
                "country": {"id": "DE", "value": "Germany"},
                "countryiso3code": "DEU",
                "date": "2024",
                "value": 51.2,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
            {
                "indicator": {"id": "NE.CON.PRVT.ZS", "value": "Household consumption"},
                "country": {"id": "DE", "value": "Germany"},
                "countryiso3code": "DEU",
                "date": "2023",
                "value": 50.4,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
            {
                "indicator": {"id": "NE.CON.PRVT.ZS", "value": "Household consumption"},
                "country": {"id": "FR", "value": "France"},
                "countryiso3code": "FRA",
                "date": "2024",
                "value": 53.1,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
            {
                "indicator": {"id": "NE.CON.PRVT.ZS", "value": "Household consumption"},
                "country": {"id": "FR", "value": "France"},
                "countryiso3code": "FRA",
                "date": "2025",
                "value": None,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
        ],
    ]
)


def _indicator() -> WorldBankIndicator:
    return WorldBankIndicator(
        code="NE.CON.PRVT.ZS", metric="household_consumption_share", unit="percent"
    )


class _Response:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body


def test_parse_groups_by_country_and_skips_empty_values():
    series = parse_world_bank_payload(PAYLOAD, _indicator())
    assert [spec.series_key for spec in series] == [
        "DE.household_consumption_share",
        "FR.household_consumption_share",
    ]
    de, fr = series
    assert de.geo.label == "Germany"
    assert de.geo.country == "DE"
    assert de.unit == "percent"
    assert [observation.period.year for observation in de.observations] == [2023, 2024]
    assert [observation.value for observation in de.observations] == [50.4, 51.2]
    assert [observation.period.year for observation in fr.observations] == [2024]


def test_parse_rejects_malformed_payload():
    with pytest.raises(ValueError, match="not \\[metadata, rows\\]"):
        parse_world_bank_payload(json.dumps({"error": "nope"}), _indicator())


async def test_fetch_normalizes_provenance_and_vintage():
    calls: list[tuple[str, str]] = []

    async def transport(method, url, headers, body):
        calls.append((method, url))
        return _Response(200, PAYLOAD)

    provider = WorldBankWdiProvider()
    result = await provider.fetch(WorldBankConfig(countries=["DE", "FR"]), {}, transport)

    assert result.provider == "world_bank"
    assert result.pack_id == "world-bank-wdi"
    assert result.version == "2024"
    assert result.dataset_vintage == "2024"
    assert result.license_class.value == "open_data"
    assert result.manifest["pack_format"] == "econ-pack/v1"
    assert len(result.series) == 2
    assert calls[0][0] == "GET"
    assert "country/DE;FR/indicator/NE.CON.PRVT.ZS" in calls[0][1]
    assert "date=1960%3A" in calls[0][1]


async def test_fetch_raises_typed_errors():
    async def transport(method, url, headers, body):
        return _Response(503, "unavailable")

    with pytest.raises(MarketDataError) as failure:
        await WorldBankWdiProvider().fetch(WorldBankConfig(), {}, transport)
    assert failure.value.code == "provider"

    async def bad_body(method, url, headers, body):
        return _Response(200, "not json")

    with pytest.raises(MarketDataError) as failure:
        await WorldBankWdiProvider().fetch(WorldBankConfig(), {}, bad_body)
    assert failure.value.code == "protocol"
