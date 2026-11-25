"""Provider (seed publisher) request/response shapes (plan 218 §3.8).

Admin and user serializers are separate on purpose: the user view never
carries a provider URI, last error, policy document or version ledger. The
storage vocabulary stays ``seed_*``; the product vocabulary is "provider"
(AI providers keep their own routes).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProviderKind = Literal["bundled", "file", "registry", "git"]
SourceKindIn = Literal["git", "registry", "file"]
TrustTier = Literal["official", "operator", "community", "local"]
VersionStatus = Literal["pending", "approved", "rejected", "revoked"]
ItemState = Literal["active", "retired", "overridden"]


class ProviderCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: SourceKindIn
    name: str = Field(min_length=1, max_length=120)
    uri: str = Field(default="", max_length=600)
    ref: str = Field(default="", max_length=200)
    subpath: str = Field(default="", max_length=255)
    priority: int = Field(default=100, ge=0, le=999)
    trust_tier: TrustTier = "community"
    refresh_minutes: int = Field(default=360, ge=0, le=10080)
    enabled: bool = False

    @model_validator(mode="after")
    def _kind_shape(self) -> ProviderCreateIn:
        if self.kind in ("git", "registry") and not self.uri:
            raise ValueError(f"a {self.kind} provider requires a URI")
        if self.kind == "file" and self.uri:
            raise ValueError("a file provider takes its content from upload, not a URI")
        return self


class ProviderUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    priority: int | None = Field(default=None, ge=0, le=999)
    trust_tier: TrustTier | None = None
    refresh_minutes: int | None = Field(default=None, ge=0, le=10080)
    enabled: bool | None = None
    ref: str | None = Field(default=None, max_length=200)
    subpath: str | None = Field(default=None, max_length=255)


class DiscoverIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["git", "registry"]
    uri: str = Field(min_length=1, max_length=600)
    ref: str = Field(default="", max_length=200)


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=2000)


class AdoptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    seed_keys: list[str] | None = None


class VersionSummaryOut(BaseModel):
    id: str
    pack_version: str
    status: VersionStatus
    digest: str
    commit_sha: str = ""
    created_at: datetime | None = None
    approved_at: datetime | None = None


class VersionOut(VersionSummaryOut):
    source_id: str
    etag: str = ""
    schema_version: str = ""
    reason: str = ""
    contract_version: str = "1.0"


class SyncRunOut(BaseModel):
    id: str
    trigger: str
    status: str
    http_status: int | None = None
    etag: str = ""
    bytes: int | None = None
    commit_sha: str = ""
    version_id: str | None = None
    error: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ProviderAdminOut(BaseModel):
    id: str
    name: str
    kind: ProviderKind
    uri: str
    ref: str = ""
    subpath: str = ""
    priority: int
    scope: str
    trust_tier: TrustTier
    refresh_minutes: int
    enabled: bool
    current_version: VersionSummaryOut | None = None
    latest_version: VersionSummaryOut | None = None
    pending_count: int = 0
    item_counts: dict[str, int] = Field(default_factory=dict)
    last_check_at: datetime | None = None
    last_error: str = ""
    policy: dict[str, Any] = Field(default_factory=dict)


class PresetAdminOut(BaseModel):
    seed_key: str
    slug: str
    name: str
    connector_key: str
    platform: str = ""
    category: str
    country: str | None = None
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    worldwide: bool = False
    languages: list[str] = Field(default_factory=list)
    work_modes: list[str] = Field(default_factory=list)
    homepage: str | None = None
    openings: int | None = None
    verified_at: date | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool
    state: ItemState
    seed_source_version_id: str | None = None
    updated_at: datetime | None = None


class EndpointAdminOut(BaseModel):
    seed_key: str
    label: str
    connector_key: str
    platform: str = ""
    server: str
    method: str
    path: str
    auth: str
    params: list[dict[str, Any]] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    worldwide: bool = False
    languages: list[str] = Field(default_factory=list)
    docs_url: str | None = None
    state: ItemState
    seed_source_version_id: str | None = None
    updated_at: datetime | None = None


class ProviderAdminDetailOut(ProviderAdminOut):
    versions: list[VersionSummaryOut] = Field(default_factory=list)
    presets: list[PresetAdminOut] = Field(default_factory=list)
    endpoints: list[EndpointAdminOut] = Field(default_factory=list)


class UserProviderOut(BaseModel):
    id: str
    name: str
    kind: ProviderKind
    trust_tier: TrustTier
    priority: int
    pack_version: str = ""
    item_count: int = 0
    last_check_at: datetime | None = None


class UserPresetOut(BaseModel):
    seed_key: str
    slug: str
    name: str
    connector_key: str
    platform: str = ""
    category: str
    country: str | None = None
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    worldwide: bool = False
    languages: list[str] = Field(default_factory=list)
    work_modes: list[str] = Field(default_factory=list)
    homepage: str | None = None
    openings: int | None = None
    verified_at: date | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class UserEndpointOut(BaseModel):
    seed_key: str
    label: str
    connector_key: str
    platform: str = ""
    server: str
    method: str
    path: str
    auth: str
    params: list[dict[str, Any]] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    worldwide: bool = False
    languages: list[str] = Field(default_factory=list)
    docs_url: str | None = None


class UserProviderDetailOut(UserProviderOut):
    presets: list[UserPresetOut] = Field(default_factory=list)
    endpoints: list[UserEndpointOut] = Field(default_factory=list)


class PlanItemOut(BaseModel):
    entity_type: str
    seed_key: str
    action: str
    content_hash: str = ""
    source_id: str | None = None
    version_id: str | None = None
    priority: int = 0
    current_id: str | None = None
    reason: str = ""


class PlanOut(BaseModel):
    status: str
    candidate_source_id: str | None = None
    candidate_version_id: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    items: list[PlanItemOut] = Field(default_factory=list)


class ApplyOut(BaseModel):
    status: str
    run_id: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    error: str = ""
    plan: PlanOut | None = None


class SyncReportOut(BaseModel):
    status: str
    code: str | None = None
    message: str = ""
    digest: str | None = None
    version_id: str | None = None
    http_status: int | None = None
    etag: str = ""
    commit_sha: str = ""
    bytes: int | None = None


class DiscoverPackOut(BaseModel):
    id: str
    path: str
    version: str
    digest: str
    itemTypes: list[str] = Field(default_factory=list)
    license: str


class DiscoverOut(BaseModel):
    kind: str
    publisher: dict[str, Any] = Field(default_factory=dict)
    packs: list[DiscoverPackOut] = Field(default_factory=list)


class RepositoryImportIn(BaseModel):
    """Add every pack of a repository as its own provider (one pack per row)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["git", "registry"] = "git"
    uri: str = Field(min_length=1, max_length=600)
    ref: str = Field(default="", max_length=200)
    priority: int = Field(default=100, ge=0, le=999)
    trust_tier: TrustTier = "community"
    refresh_minutes: int = Field(default=0, ge=0, le=10080)
    enabled: bool = False


class ImportedPackOut(BaseModel):
    source_id: str
    name: str
    subpath: str
    created: bool


class RepositoryImportOut(BaseModel):
    publisher: dict[str, Any] = Field(default_factory=dict)
    packs: list[ImportedPackOut] = Field(default_factory=list)


class ProbeOut(BaseModel):
    status: int
    elapsed_ms: int
    content_type: str = ""


__all__ = [
    "AdoptIn",
    "ApplyOut",
    "DiscoverIn",
    "DiscoverOut",
    "DiscoverPackOut",
    "EndpointAdminOut",
    "PlanItemOut",
    "PlanOut",
    "PresetAdminOut",
    "ProbeOut",
    "ProviderAdminDetailOut",
    "ProviderAdminOut",
    "ProviderCreateIn",
    "ProviderUpdateIn",
    "RejectIn",
    "SyncReportOut",
    "SyncRunOut",
    "UserEndpointOut",
    "UserPresetOut",
    "UserProviderDetailOut",
    "UserProviderOut",
    "VersionOut",
    "VersionSummaryOut",
]
