"""ATS catalog import (plan 187): the catalog-document envelope plus the
import metadata one PUT carries.

The catalog is pure DATA (tenant presets + provider connection hints) —
strict pydantic is the untrusted-input law: unknown fields rejected,
``signature`` reserved (must be null until the operator edition verifies
detached ed25519 in phase B), ``logo`` dropped so a catalog-supplied URL
can never become an external-origin image surface. Caps bound a single
document; the stored-catalogs cap lives in the service.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CATALOG_SCHEMA_VERSION = 1
CATALOG_KIND = "career-ats-catalog"
CATALOG_TIERS = ("operator", "community", "user")
MAX_CATALOG_PRESETS = 300
MAX_CATALOG_PROVIDERS = 50
MAX_CATALOG_BYTES = 512 * 1024
MAX_CATALOGS = 8
CATALOG_SETTING_KEY = "posting.sources.catalogs"


class CatalogPresetIn(BaseModel):
    """One tenant preset — the existing JobSourcePreset shape (no logo)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slug: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    connectorKey: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=120)
    category: Literal["ats", "remote"]
    config: dict[str, str] = Field(default_factory=dict)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    openings: int | None = Field(default=None, ge=0)
    verifiedAt: str | None = Field(default=None, max_length=40)

    @model_validator(mode="before")
    @classmethod
    def _drop_logo(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data.pop("logo", None)
        return data

    @field_validator("config")
    @classmethod
    def _bounded_config(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("config carries at most 20 entries")
        return value


class CatalogProviderIn(BaseModel):
    """One provider connection hint (connector + URL template + countries)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80)
    connectorKey: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    urlTemplate: str | None = Field(default=None, max_length=300)
    countries: list[str] = Field(default_factory=list, max_length=100)
    docsUrl: str | None = Field(default=None, max_length=300)


class CatalogUpsertIn(BaseModel):
    """PUT body: the catalog envelope + the import metadata."""

    model_config = ConfigDict(extra="forbid")

    tier: Literal["operator", "community", "user"]
    url: str | None = Field(default=None, max_length=500)
    fetchedAt: datetime
    etag: str | None = Field(default=None, max_length=200)
    lastModified: str | None = Field(default=None, max_length=200)

    schemaVersion: Literal[1]
    kind: Literal["career-ats-catalog"]
    name: str = Field(min_length=1, max_length=200)
    license: str | None = Field(default=None, max_length=120)
    updatedAt: datetime
    revision: int = Field(ge=0, le=1_000_000)
    contentHash: str = Field(min_length=8, max_length=80)
    signature: None = None
    presets: list[CatalogPresetIn] = Field(default_factory=list, max_length=MAX_CATALOG_PRESETS)
    providers: list[CatalogProviderIn] = Field(
        default_factory=list, max_length=MAX_CATALOG_PROVIDERS
    )
