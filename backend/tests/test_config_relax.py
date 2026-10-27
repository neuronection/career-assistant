"""Radar-mode config relaxation: the host's query overlay supplies the
query fields per sync, so a stored fallback is not required. Both config
validators take ``relax_keys`` — the manifest-schema one (sandbox) and
the model one (SDK base) — and the x-secret law survives relaxation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from app.core.errors import ValidationError
from app.extensions.runtime.sandbox.connector import SandboxConnector
from app.extensions.sdk import ConnectorCapabilities, PostingConnector

MANIFEST = {
    "id": "kw-test",
    "version": "1.0.0",
    "configSchema": {
        "type": "object",
        "required": ["keywords"],
        "properties": {
            "keywords": {"type": "string", "minLength": 1, "maxLength": 300},
            "location": {"type": "string", "maxLength": 120},
            "api_token": {"type": "string", "x-secret": True},
        },
    },
    "secrets": [{"id": "api_token", "purpose": "auth"}],
}


class KeywordsConfig(BaseModel):
    keywords: str = Field(min_length=1)
    location: str = ""


class _ModelConnector(PostingConnector):
    key = "kw-model"
    title = "KW model"
    manifest_file = Path(__file__).resolve().parent / "fixtures" / "synthetic-connector.json"
    capabilities = ConnectorCapabilities()

    def config_model(self):
        return KeywordsConfig


def _sandbox() -> SandboxConnector:
    install = SimpleNamespace(manifest=MANIFEST, extension_id="kw-test")
    return SandboxConnector(None, install)


def test_sandbox_required_survives_without_relax():
    connector = _sandbox()
    with pytest.raises(ValidationError):
        connector.validate_config({"keywords": ""})


def test_sandbox_relax_drops_required_and_min_length():
    connector = _sandbox()
    validated = connector.validate_config({"keywords": ""}, relax_keys=("keywords", "location"))
    assert validated == {"keywords": ""}


def test_sandbox_relax_keeps_the_secret_law():
    connector = _sandbox()
    with pytest.raises(ValidationError, match="never lives in config"):
        connector.validate_config(
            {"keywords": "", "api_token": "plain"}, relax_keys=("keywords",)
        )


def test_model_relax_makes_fields_optional():
    connector = _ModelConnector()
    with pytest.raises(ValidationError):
        connector.validate_config({"keywords": ""})
    validated = connector.validate_config({"keywords": ""}, relax_keys=("keywords", "location"))
    assert validated["keywords"] == ""
