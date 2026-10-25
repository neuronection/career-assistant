"""Market-data provider registry (plan 127 §3.2): sources are data.

One contract for every external series source. Built-ins register at
import; third-party providers arrive via the
``career_assistant.market_data`` entry-point group, admin-opt-in through
``market_data_plugins_allowlist`` (code shipped in the deployment image,
reviewed). Registration fails closed: duplicate keys, malformed keys and
non-ingestable license classes (``research_only``) are rejected before any
fetch happens.

Providers carry numbers; they never compute them. Each returns typed
series and observations with provenance, license class and a pack
version (vintage). Arithmetic and aggregation belong to the reducers in
``app/services/econ``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date
from importlib import metadata
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.errors import ValidationError
from app.models.enums import CoverageLevel, GeoRegionKind, LicenseClass

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "career_assistant.market_data"

_INGESTIBLE_LICENSES = {
    LicenseClass.PUBLIC_DOMAIN,
    LicenseClass.OPEN_DATA,
    LicenseClass.ATTRIBUTION,
}


class MarketDataError(Exception):
    """Typed fetch failure — the charter error shape, raised instead of returned."""

    def __init__(self, *, code: str, detail: str, retryable: str = "yes") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.retryable = retryable


class ProviderGeo(BaseModel):
    """The geo target of a provider series; ingest provisions the region row."""

    kind: GeoRegionKind = GeoRegionKind.COUNTRY
    code: str = Field(min_length=1, max_length=32)
    country: str = Field(min_length=2, max_length=2)
    label: str = Field(default="", max_length=200)


class ProviderObservation(BaseModel):
    """One value at a period; estimates are flagged, never smoothed over."""

    period: date
    value: float
    is_estimate: bool = False


class ProviderSeries(BaseModel):
    """One dimensional series as the provider normalized it."""

    series_key: str = Field(min_length=1, max_length=200)
    metric: str = Field(min_length=1, max_length=80)
    unit: str = Field(default="", max_length=40)
    freq: str = Field(default="annual", max_length=20)
    geo: ProviderGeo
    sector_code: str | None = Field(default=None, max_length=32)
    occ_code: str | None = Field(default=None, max_length=32)
    coverage_level: CoverageLevel = CoverageLevel.COUNTRY
    source_url: str = Field(default="", max_length=500)
    observations: list[ProviderObservation] = Field(default_factory=list)


class ProviderResult(BaseModel):
    """One provider run: a versioned snapshot ready for ingest."""

    provider: str
    pack_id: str
    version: str
    dataset_vintage: str = ""
    license_class: LicenseClass
    coverage: dict = Field(default_factory=dict)
    manifest: dict = Field(default_factory=dict)
    source_url: str = Field(default="", max_length=500)
    series: list[ProviderSeries] = Field(default_factory=list)


class MarketDataProvider(ABC):
    """Contract every market-data source implements."""

    key: str
    title: str
    license_class: LicenseClass
    network_scopes: frozenset[str] = frozenset()
    secret_slots: tuple[str, ...] = ()
    kind: Literal["series"] = "series"

    @abstractmethod
    def config_model(self) -> type[BaseModel]:
        """Pydantic model validating this provider's stored config."""

    @abstractmethod
    async def fetch(self, config: BaseModel, secrets: dict[str, str], transport) -> ProviderResult:
        """Fetch and normalize one snapshot; raises ``ConnectorError`` on failure."""

    def manifest(self) -> dict:
        """The registration payload (data, not an extension code envelope)."""
        return {
            "key": self.key,
            "title": self.title,
            "kind": self.kind,
            "license_class": self.license_class.value,
            "network_scopes": sorted(self.network_scopes),
            "secret_slots": list(self.secret_slots),
        }


class MarketDataRegistry:
    """Keyed provider set; registration validates and fails closed."""

    def __init__(self) -> None:
        self._providers: dict[str, MarketDataProvider] = {}

    def register(self, provider: MarketDataProvider) -> None:
        key = (provider.key or "").strip()
        if not key or not key.replace("_", "").isalnum():
            raise ValidationError(f"market-data provider key {provider.key!r} is not a slug")
        if provider.license_class not in _INGESTIBLE_LICENSES:
            raise ValidationError(
                f"market-data provider {key!r} declares a non-ingestable license "
                f"({provider.license_class.value}) — research-only sources are cited, never stored"
            )
        if key in self._providers:
            raise ValidationError(f"market-data provider {key!r} is already registered")
        self._providers[key] = provider

    def get(self, key: str) -> MarketDataProvider:
        provider = self._providers.get(key)
        if provider is None:
            raise ValidationError(f"unknown market-data provider {key!r}")
        return provider

    def keys(self) -> list[str]:
        return sorted(self._providers)


def _load_entry_points(registry: MarketDataRegistry) -> None:
    """Admit third-party providers named in the admin allowlist (built-ins need no opt-in)."""
    allowlist = set(settings.market_data_plugins_allowlist)
    if not allowlist:
        return
    for entry_point in metadata.entry_points(group=ENTRY_POINT_GROUP):
        if entry_point.name not in allowlist:
            continue
        try:
            loaded = entry_point.load()
            provider = loaded() if isinstance(loaded, type) else loaded
            if not isinstance(provider, MarketDataProvider):
                raise TypeError(
                    f"entry point {entry_point.name!r} did not produce a MarketDataProvider"
                )
            registry.register(provider)
        except Exception:
            logger.warning("market-data plugin %s failed to load", entry_point.name, exc_info=True)


_registry: MarketDataRegistry | None = None


def registry() -> MarketDataRegistry:
    """The process registry: built-ins first, then allowlisted entry points."""
    global _registry
    if _registry is None:
        from app.extensions.market_data_providers import BUILTINS

        built = MarketDataRegistry()
        for provider in BUILTINS:
            built.register(provider)
        _load_entry_points(built)
        _registry = built
    return _registry


__all__ = [
    "ENTRY_POINT_GROUP",
    "MarketDataError",
    "MarketDataProvider",
    "MarketDataRegistry",
    "ProviderGeo",
    "ProviderObservation",
    "ProviderResult",
    "ProviderSeries",
    "registry",
]
