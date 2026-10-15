"""Shared wire-parameter fixture wall (ADR-0038) — career's side.

Loads the vendored fixture table (byte-identical across the family:
``dev/contracts/wire-params.fixtures.json`` → ``tests/fixtures/``). A row
change is a contract change — every repo must pass the same rows. Policy
rows hit the vendored ``app.ai.wire_params`` module directly; temperature
rows run through career's own factory (omit-unless-configured).
"""

import json
from pathlib import Path

import pytest

from app.ai.chat_models import build_chat_model
from app.ai.providers.resolution import ResolvedModel
from app.ai.wire_params import is_openai_endpoint, resolve_chat_transport, resolve_max_tokens_param

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "wire_params.fixtures.json").read_text()
)


def _temperature_model(row) -> object:
    resolved = ResolvedModel(
        provider_type="openai",
        base_url="https://api.openai.com/v1",
        api_key="sk-secret-123",
        model_name=FIXTURES["temperatureModelId"],
        temperature=row["temperature"],
        source="system:default",
    )
    return build_chat_model(resolved)


@pytest.mark.parametrize("row", FIXTURES["endpointDetection"], ids=lambda r: r["name"])
def test_endpoint_detection(row):
    assert is_openai_endpoint(row["apiBase"]) is row["expected"]


@pytest.mark.parametrize("row", FIXTURES["maxTokensParam"], ids=lambda r: r["name"])
def test_max_tokens_param_resolution(row):
    assert resolve_max_tokens_param(row["providerType"], row["apiBase"], row["override"]) == row["expected"]


@pytest.mark.parametrize("row", FIXTURES["chatTransport"], ids=lambda r: r["name"])
def test_chat_transport_resolution(row):
    assert resolve_chat_transport(row["providerType"], row["apiBase"], row["override"]) == row["expected"]


@pytest.mark.parametrize("row", FIXTURES["temperatureOmission"], ids=lambda r: r["name"])
def test_temperature_omission(row):
    model = _temperature_model(row)
    assert ("temperature" in model._default_params) is row["sent"]
