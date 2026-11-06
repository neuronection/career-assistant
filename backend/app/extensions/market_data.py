"""Market-data provider registry (plan 127 §3.2): sources are extensions.

Sources are self-contained bundles under ``builtin/market_data/<key>/``,
each with its own ``extension/v1`` manifest (the charter's item-schema
contract for external data sources, ``ObservationCreate``) plus its
provider class. The loader validates every bundle manifest against the
vendored envelope schema and cross-checks it with the provider (key dir,
kind, network scopes, capabilities) — a bundle that disagrees with its
manifest fails closed. Third-party providers arrive via the
``career_assistant.market_data`` entry-point group, admin-opt-in through
``market_data_plugins_allowlist`` (code shipped in the deployment image,
reviewed).

Registration fails closed: duplicate keys, malformed keys and
non-ingestable license classes (``research_only``) are rejected before any
fetch happens.

Providers carry numbers; they never compute them. Each returns typed
series and observations with provenance, license class and a pack
version (vintage). Arithmetic and aggregation belong to the reducers in
``app/services/econ``.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import date
from importlib import metadata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.errors import ValidationError
from app.extensions import contract
from app.models.enums import CoverageLevel, GeoRegionKind, LicenseClass

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "career_assistant.market_data"
_BUNDLE_ROOT = Path(__file__).resolve().parent / "builtin" / "market_data"
_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "extension-manifest.schema.json"

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


def _envelope_schema() -> dict:
    try:
        return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"extension envelope schema unavailable at {_SCHEMA_PATH}: {exc} — "
            "market-data registration fails closed (vendored contract set incomplete)"
        ) from exc


def _bundle_manifest_problems(bundle: str, manifest: dict) -> list[str]:
    """The bundle's manifest must be a valid envelope and agree with its provider."""
    problems: list[str] = []
    schema = _envelope_schema()
    error = contract.validate(schema["$defs"]["bundledManifest"], manifest, schema)
    if error is not None:
        problems.append(f"{bundle}: {error}")
    if manifest.get("kind") != "connector":
        problems.append(
            f"{bundle}: manifest kind must be 'connector', got {manifest.get('kind')!r}"
        )
    if "net" not in (manifest.get("capabilities") or []):
        problems.append(f"{bundle}: manifest capabilities must include 'net'")
    if not isinstance(manifest.get("itemSchema"), dict):
        problems.append(f"{bundle}: manifest must declare the observation item schema")
    return problems


def _bundled_providers() -> list[MarketDataProvider]:
    """Scan bundle dirs, validate every manifest, and require a 1:1 provider match."""
    from app.extensions.builtin.market_data import BUILTINS

    by_key = {provider.key: provider for provider in BUILTINS}
    manifests: dict[str, dict] = {}
    problems: list[str] = []
    for path in sorted(_BUNDLE_ROOT.glob("*/manifest.json")):
        bundle = path.parent.name
        try:
            manifests[bundle] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{bundle}: manifest unreadable ({exc})")
            continue
        problems.extend(_bundle_manifest_problems(bundle, manifests[bundle]))

    for bundle, manifest in manifests.items():
        provider = by_key.get(bundle)
        if provider is None:
            problems.append(f"{bundle}: manifest without a provider in BUILTINS")
            continue
        if set(manifest.get("domains") or []) != set(provider.network_scopes):
            problems.append(
                f"{bundle}: manifest domains {sorted(manifest.get('domains') or [])} "
                f"do not match the provider network scopes {sorted(provider.network_scopes)}"
            )
    for key in by_key:
        if key not in manifests:
            problems.append(f"{key}: provider has no bundle manifest.json")

    if problems:
        raise ValidationError("; ".join(problems))
    return BUILTINS


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
    """The process registry: validated bundles first, then allowlisted entry points."""
    global _registry
    if _registry is None:
        built = MarketDataRegistry()
        for provider in _bundled_providers():
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
