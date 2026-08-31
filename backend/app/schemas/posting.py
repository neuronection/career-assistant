"""Posting API schemas (Phase 26)."""

from datetime import datetime
from typing import Optional
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
    config: Optional[dict] = None
    enabled: Optional[bool] = None


class SourceOut(BaseModel):
    id: UUID
    key: str
    connector_key: str
    config: dict
    enabled: bool
    last_run_at: Optional[datetime] = None
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
    seniority: Optional[str] = None
    employment_type: Optional[str] = None
    onsite_policy: Optional[str] = None
    salary_currency: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_period: Optional[str] = None
    posted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    status: str
    catalog_job_id: Optional[UUID] = None
    mapping_method: Optional[str] = None
    mapping_confidence: Optional[float] = None
    mapping_reason: str
    fit: Optional[float] = None
    seen: bool = False
    saved: bool = False
    applied_at: Optional[datetime] = None
    notes: str = ""
    # Deep extraction provenance (plan 31): raw → fast-mapped → extracted.
    extract_version: Optional[int] = None
    needs_review: bool = False
    # Deterministic skills coverage (match-profile ranking only).
    coverage: Optional[float] = None
    # Display-only source badge fields (filter key is authoritative).
    source_key: str = ""
    catalog_job: Optional[JobOut] = None


class PostingDetailOut(PostingOut):
    """Detail view (plan 32): full extract, source attribution, the
    match-score card and the similar-postings rail."""

    extract: Optional[dict] = None
    source_title: str = ""
    source_connector: str = ""
    source_synced_at: Optional[datetime] = None
    match: Optional[dict] = None
    similar: list[dict] = Field(default_factory=list)


class PostingSearchOut(BaseModel):
    """Search response: items carry matched-skill coverage metadata."""

    items: list[PostingOut]
    total: int
    unseen: int


class SkillEntryIn(BaseModel):
    """One search skill entry: `sql:4` style, validated server-side."""

    key: str = Field(min_length=1, max_length=80)
    level: Optional[int] = Field(default=None, ge=1, le=10)


class PostingsOut(BaseModel):
    items: list[PostingOut]
    total: int
    unseen: int


class ExploreOut(BaseModel):
    """Explore response (plan 32): cursor-paginated items + facets."""

    items: list[PostingOut]
    total: int
    next_cursor: Optional[str] = None
    facets: dict = Field(default_factory=dict)


class SeenIn(BaseModel):
    posting_ids: list[UUID] = Field(min_length=1, max_length=200)


class SaveIn(BaseModel):
    posting_id: UUID
    saved: bool = True


class AppliedIn(BaseModel):
    posting_id: UUID
    applied_via_url: str = Field(default="", max_length=1000)
    stage: Optional[ApplicationStage] = None


class MapIn(BaseModel):
    catalog_job_id: UUID
