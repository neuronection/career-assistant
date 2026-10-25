"""Builtin market-data providers, wave 1 (plan 127 §3.2).

World Bank WDI is the no-instance-empty layer: country-level series for
the whole world, open license, no API key. The BLS OEWS/EP and OECD
adapters (3.2b) take this same shape.

Parsing is pure (fixtures drive the tests); fetching goes through the
guarded transport passed by the caller — no module ever opens a socket
directly.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from urllib.parse import urlencode

from pydantic import BaseModel, Field, field_validator

from app.extensions.market_data import (
    MarketDataError,
    MarketDataProvider,
    ProviderGeo,
    ProviderObservation,
    ProviderResult,
    ProviderSeries,
)
from app.models.enums import CoverageLevel, GeoRegionKind, LicenseClass

WORLD_BANK_URL = "https://api.worldbank.org/v2/country/{countries}/indicator/{indicator}"


class WorldBankIndicator(BaseModel):
    """One indicator selection: the external code plus its display metric."""

    code: str = Field(min_length=1, max_length=40)
    metric: str = Field(default="", max_length=80)
    unit: str = Field(default="", max_length=40)
    coverage_level: CoverageLevel = CoverageLevel.COUNTRY

    @field_validator("metric", mode="after")
    @classmethod
    def _metric_defaults_to_code(cls, value: str, info) -> str:
        return value or info.data.get("code", "")


class WorldBankConfig(BaseModel):
    """A WDI pull: countries x indicators over a year window."""

    countries: list[str] = Field(default_factory=lambda: ["DE"], min_length=1, max_length=50)
    indicators: list[WorldBankIndicator] = Field(
        default_factory=lambda: [
            WorldBankIndicator(
                code="NE.CON.PRVT.ZS",
                metric="household_consumption_share",
                unit="percent",
            )
        ],
        min_length=1,
        max_length=20,
    )
    start_year: int | None = Field(default=None, ge=1960, le=2100)
    end_year: int | None = Field(default=None, ge=1960, le=2100)

    @field_validator("countries", mode="after")
    @classmethod
    def _normalize_countries(cls, values: list[str]) -> list[str]:
        return [value.strip().upper() for value in values if value.strip()]


def parse_world_bank_payload(body: str, indicator: WorldBankIndicator) -> list[ProviderSeries]:
    """WDI ``[metadata, rows]``; rows without a value are skipped, never zero-filled."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"World Bank payload is not JSON: {exc}") from exc
    if not isinstance(data, list) or len(data) < 2 or not isinstance(data[1], list):
        raise ValueError("World Bank payload is not [metadata, rows]")

    series: dict[tuple[str, str], ProviderSeries] = {}
    for row in data[1]:
        if not isinstance(row, dict):
            continue
        country = row.get("country") if isinstance(row.get("country"), dict) else {}
        country_code = str(country.get("id") or row.get("countryiso3code") or "").upper()[:2]
        raw_year = str(row.get("date") or "")
        raw_value = row.get("value")
        if not country_code or not raw_year.isdigit() or raw_value is None:
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        key = (country_code, indicator.metric)
        if key not in series:
            series[key] = ProviderSeries(
                series_key=f"{country_code}.{indicator.metric}",
                metric=indicator.metric,
                unit=indicator.unit,
                freq="annual",
                geo=ProviderGeo(
                    kind=GeoRegionKind.COUNTRY,
                    code=country_code,
                    country=country_code,
                    label=str(country.get("value") or country_code)[:200],
                ),
                coverage_level=indicator.coverage_level,
                source_url=WORLD_BANK_URL.format(countries=country_code, indicator=indicator.code),
            )
        series[key].observations.append(
            ProviderObservation(period=date(int(raw_year), 1, 1), value=value)
        )

    for spec in series.values():
        spec.observations.sort(key=lambda observation: observation.period)
    return sorted(series.values(), key=lambda spec: spec.series_key)


class WorldBankWdiProvider(MarketDataProvider):
    """World Bank World Development Indicators (country level, annual)."""

    key = "world_bank"
    title = "World Bank — World Development Indicators"
    license_class = LicenseClass.OPEN_DATA
    network_scopes = frozenset({"api.worldbank.org"})

    def config_model(self) -> type[BaseModel]:
        return WorldBankConfig

    def _request_url(self, config: WorldBankConfig, indicator: WorldBankIndicator) -> str:
        countries = ";".join(config.countries)
        params: dict[str, str] = {"format": "json", "per_page": "1000"}
        start = config.start_year
        end = config.end_year or datetime.now(UTC).year
        params["date"] = f"{start or 1960}:{end}"
        base = WORLD_BANK_URL.format(countries=countries, indicator=indicator.code)
        return f"{base}?{urlencode(params)}"

    async def fetch(self, config: BaseModel, secrets: dict[str, str], transport) -> ProviderResult:
        assert isinstance(config, WorldBankConfig)

        series: list[ProviderSeries] = []
        for indicator in config.indicators:
            url = self._request_url(config, indicator)
            try:
                response = await transport("GET", url, {"Accept": "application/json"}, None)
            except Exception as exc:
                raise MarketDataError(
                    code="network", detail=f"World Bank request failed: {exc}", retryable="yes"
                ) from exc
            if response.status != 200:
                raise MarketDataError(
                    code="provider",
                    detail=f"World Bank returned status {response.status}",
                    retryable="yes",
                )
            try:
                series.extend(parse_world_bank_payload(response.body, indicator))
            except ValueError as exc:
                raise MarketDataError(
                    code="protocol",
                    detail=f"World Bank parse: {exc}",
                    retryable="after-config-change",
                ) from exc

        latest_year = max(
            (observation.period.year for spec in series for observation in spec.observations),
            default=0,
        )
        if not series or latest_year == 0:
            raise MarketDataError(
                code="provider",
                detail="World Bank returned no observations for the configured selection",
                retryable="after-config-change",
            )
        vintage = str(latest_year)
        return ProviderResult(
            provider=self.key,
            pack_id="world-bank-wdi",
            version=vintage,
            dataset_vintage=vintage,
            license_class=self.license_class,
            coverage={
                "granularity": "country",
                "countries": config.countries,
                "indicators": [indicator.code for indicator in config.indicators],
            },
            manifest={
                "pack_format": "econ-pack/v1",
                "provider": self.key,
                "publisher": "World Bank",
                "source": "World Development Indicators",
            },
            source_url="https://data.worldbank.org",
            series=series,
        )


BUILTINS: list[MarketDataProvider] = [WorldBankWdiProvider()]
