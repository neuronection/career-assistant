"""Posting API schemas (Phase 26)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import ApplicationStage
from app.schemas.job import JobOut


class ConnectorOut(BaseModel):
    key: str
    title: str
    docs_url: str
    capabilities: dict
    builtin: bool
    config_schema: dict


class SourceCreateIn(BaseModel):
    key: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    connector_key: str = Field(min_length=1, max_length=80)
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class SourceUpdateIn(BaseModel):
    config: dict | None = None
    enabled: bool | None = None


class SourceOut(BaseModel):
    id: UUID
    key: str
    connector_key: str
    config: dict
    enabled: bool
    last_run_at: datetime | None = None
    sync_state: dict
    error: str

    model_config = {"from_attributes": True}


class PostingOut(BaseModel):
    id: UUID
    ref: str = ""
    source_id: UUID
    external_id: str
    title: str
    org: str
    location: dict
    url: str
    seniority: str | None = None
    employment_type: str | None = None
    onsite_policy: str | None = None
    salary_currency: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_period: str | None = None
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    status: str
    catalog_job_id: UUID | None = None
    mapping_method: str | None = None
    mapping_confidence: float | None = None
    mapping_reason: str
    fit: float | None = None
    seen: bool = False
    saved: bool = False
    applied_at: datetime | None = None
    notes: str = ""
    # Deep extraction provenance: raw → fast-mapped → extracted.
    extract_version: int | None = None
    needs_review: bool = False
    # Deterministic skills coverage (match-profile ranking only).
    coverage: float | None = None
    # Display-only source badge fields (filter key is authoritative).
    source_key: str = ""
    catalog_job: JobOut | None = None


class PostingDetailOut(PostingOut):
    """Detail view: full extract, source attribution, the
    match-score card and the similar-postings rail."""

    extract: dict | None = None
    source_title: str = ""
    source_connector: str = ""
    source_synced_at: datetime | None = None
    match: dict | None = None
    similar: list[dict] = Field(default_factory=list)


class PostingSearchOut(BaseModel):
    """Search response: items carry matched-skill coverage metadata."""

    items: list[PostingOut]
    total: int
    unseen: int


class SkillEntryIn(BaseModel):
    """One search skill entry: `sql:4` style, validated server-side."""

    key: str = Field(min_length=1, max_length=80)
    level: int | None = Field(default=None, ge=1, le=10)


class PostingsOut(BaseModel):
    items: list[PostingOut]
    total: int
    unseen: int


class ExploreOut(BaseModel):
    """Explore response: cursor-paginated items + facets."""

    items: list[PostingOut]
    total: int
    next_cursor: str | None = None
    facets: dict = Field(default_factory=dict)


class SeenIn(BaseModel):
    posting_ids: list[UUID] = Field(min_length=1, max_length=200)


class SaveIn(BaseModel):
    posting_id: UUID
    saved: bool = True


class AppliedIn(BaseModel):
    posting_id: UUID
    applied_via_url: str = Field(default="", max_length=1000)
    stage: ApplicationStage | None = None


class MapIn(BaseModel):
    catalog_job_id: UUID
