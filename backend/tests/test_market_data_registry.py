"""Market-data registry (plan 127 §3.2): built-in bundles, fail-closed
registration, and the license wall that keeps research-only sources out of
the store."""

import json

import pytest
from pydantic import BaseModel

from app.core.errors import ValidationError
from app.extensions import market_data
from app.extensions.market_data import MarketDataProvider, MarketDataRegistry, registry
from app.models.enums import LicenseClass


class _DummyConfig(BaseModel):
    pass


class _StubProvider(MarketDataProvider):
    def __init__(self, key: str, license_class: LicenseClass) -> None:
        self.key = key
        self.title = "Stub"
        self.license_class = license_class

    def config_model(self) -> type[BaseModel]:
        return _DummyConfig

    async def fetch(self, config, secrets, transport):  # pragma: no cover - registry tests
        raise NotImplementedError


def test_builtin_registry_carries_world_bank():
    built = registry()
    keys = built.keys()
    assert "world_bank" in keys
    manifest = built.get("world_bank").manifest()
    assert manifest["license_class"] == "open_data"
    assert manifest["network_scopes"] == ["api.worldbank.org"]


def test_unknown_provider_raises():
    with pytest.raises(ValidationError, match="unknown market-data provider"):
        registry().get("nope")


def test_research_only_provider_is_rejected_at_registration():
    registry_under_test = MarketDataRegistry()
    with pytest.raises(ValidationError, match="non-ingestable license"):
        registry_under_test.register(_StubProvider("scraped_scores", LicenseClass.RESEARCH_ONLY))
    assert registry_under_test.keys() == []


def test_duplicate_key_is_rejected():
    registry_under_test = MarketDataRegistry()
    registry_under_test.register(_StubProvider("stub", LicenseClass.OPEN_DATA))
    with pytest.raises(ValidationError, match="already registered"):
        registry_under_test.register(_StubProvider("stub", LicenseClass.OPEN_DATA))


def test_malformed_key_is_rejected():
    registry_under_test = MarketDataRegistry()
    with pytest.raises(ValidationError, match="not a slug"):
        registry_under_test.register(_StubProvider("not a slug!", LicenseClass.OPEN_DATA))


def test_real_bundles_match_their_manifests():
    providers = market_data._bundled_providers()
    assert [provider.key for provider in providers] == ["world_bank"]


def test_bundle_manifest_disagreement_fails_closed(monkeypatch, tmp_path):
    bundle = tmp_path / "world_bank"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"apiVersion": "extension/v1", "kind": "connector", "id": "career-broken"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(market_data, "_BUNDLE_ROOT", tmp_path)
    with pytest.raises(ValidationError):
        market_data._bundled_providers()
