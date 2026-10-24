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


class PostingLocationOut(BaseModel):
    city: str | None = None
    country: str | None = None
    remote: bool | None = None


class PostingExtractSkillOut(BaseModel):
    skill_key: str | None = None
    raw_label: str | None = None
    unresolved: bool | None = None
    required_level: int
    priority: str
    evidence_quote: str
    confidence: float


class PostingExtractResponsibilityOut(BaseModel):
    text: str
    time_pct: float | None = None
    optional: bool | None = None


class PostingExtractLocationOut(BaseModel):
    city: str | None = None
    country: str | None = None


class PostingExtractSalaryOut(BaseModel):
    min: float | None = None
    max: float | None = None
    currency: str | None = None
    period: str | None = None


class PostingExtractEducationOut(BaseModel):
    level: str | None = None
    field: str | None = None


class PostingExtractOut(BaseModel):
    """The posting's structured extraction payload (pipeline-written
    JSONB, envelope-typed since plan 123.4)."""

    model_config = {"extra": "allow"}

    title_norm: str | None = None
    seniority: str | None = None
    employment_type: str | None = None
    remote_policy: str | None = None
    location: PostingExtractLocationOut | None = None
    salary: PostingExtractSalaryOut | None = None
    education: PostingExtractEducationOut | None = None
    languages: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    responsibilities: list[PostingExtractResponsibilityOut] = Field(default_factory=list)
    skills: list[PostingExtractSkillOut] = Field(default_factory=list)
    field_confidence: dict[str, float] = Field(default_factory=dict)


class MatchBreakdownAspectOut(BaseModel):
    """One match-score dimension bar (score/weight envelope)."""

    score: float
    weight: float
    detail: str
    neutral: bool | None = None


class PostingMatchOut(BaseModel):
    """The deterministic posting match card (fit-style scoring)."""

    score: float
    breakdown: dict[str, MatchBreakdownAspectOut] = Field(default_factory=dict)
    extracted: bool = False
    estimate: bool = False
    gates: list[str] | None = None
    inputs_hash: str = ""


class PostingSimilarOut(BaseModel):
    ref: str
    title: str
    org: str
    score: float


class PostingOut(BaseModel):
    id: UUID
    ref: str = ""
    source_id: UUID
    external_id: str
    title: str
    org: str
    location: PostingLocationOut
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
    application_id: UUID | None = None
    stage: str | None = None
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

    extract: PostingExtractOut | None = None
    source_title: str = ""
    source_connector: str = ""
    source_synced_at: datetime | None = None
    match: PostingMatchOut | None = None
    similar: list[PostingSimilarOut] = Field(default_factory=list)


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
    facets: dict[str, dict[str, int]] = Field(default_factory=dict)


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
