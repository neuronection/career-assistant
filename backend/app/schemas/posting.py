"""Posting API schemas (Phase 26)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

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
    """One stored extract skill row (v5): the verbatim `raw_label` plus
    the `skill_key` the resolution stamped (null when the label stayed a
    proposal — the replay substrate carries both)."""

    skill_key: str | None = None
    raw_label: str | None = None
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
    basis: str | None = None


class PostingExtractEducationOut(BaseModel):
    level: str | None = None
    field: str | None = None


class PostingExtractPrerequisiteOut(BaseModel):
    """One stated requirement outside the skill/salary axes."""

    kind: str
    label: str
    evidence_quote: str = ""
    confidence: float | None = None


class PostingExtractBenefitOut(BaseModel):
    """Typed benefit: `kind` powers display grouping, `raw` keeps the
    original wording. Stored plain strings (pre-migration extract rows) coerce
    to `kind="other"` at read — the extractor's `ExtractBenefit.coerce`
    precedent."""

    kind: str
    raw: str
    confidence: float | None = None


class PostingExtractContractOut(BaseModel):
    contract_type: str
    evidence_quote: str = ""
    confidence: float | None = None


class PostingExtractHoursOut(BaseModel):
    pattern: str
    hours_per_week_min: int | None = None
    hours_per_week_max: int | None = None
    evidence_quote: str = ""
    confidence: float | None = None


class PostingExtractScheduleCueOut(BaseModel):
    cue: str
    evidence_quote: str = ""
    confidence: float | None = None


class PostingExtractTravelOut(BaseModel):
    level: str
    days_per_month: int | None = None
    evidence_quote: str = ""
    confidence: float | None = None


class PostingExtractOnsiteOut(BaseModel):
    policy: str
    office_days_per_week: int | None = None
    evidence_quote: str = ""
    confidence: float | None = None


class PostingExtractWorkAuthorizationOut(BaseModel):
    status: str
    evidence_quote: str = ""
    confidence: float | None = None


class PostingExtractLanguageOut(BaseModel):
    code: str
    level: str
    evidence_quote: str = ""
    confidence: float | None = None


class PostingExtractGradeOut(BaseModel):
    scale: str
    value: float
    evidence_quote: str = ""
    confidence: float | None = None


class GateOverrideIn(BaseModel):
    """One per-posting eligibility override ("apply anyway")."""

    gate: Literal["visa", "language", "grade"]
    allow: bool = True


class PostingExtractOut(BaseModel):
    """The posting's structured extraction payload (pipeline-written
    JSONB, envelope-typed since plan 123.4).

    Read coercion is part of the contract: ``apply_extract`` suppresses
    low-confidence fields to ``null`` (``_suppressed_fields`` names
    them) and pre-migration rows stored plain-string benefits, so lists
    normalize to ``[]`` and benefit strings to ``kind="other"`` instead
    of failing whole postings on read."""

    model_config = {"extra": "allow"}

    title_norm: str | None = None
    description_clean: str | None = None
    seniority: str | None = None
    employment_type: str | None = None
    remote_policy: str | None = None
    location: PostingExtractLocationOut | None = None
    salary: PostingExtractSalaryOut | None = None
    education: PostingExtractEducationOut | None = None
    language_requirements: list[PostingExtractLanguageOut] = Field(default_factory=list)
    prerequisites: list[PostingExtractPrerequisiteOut] = Field(default_factory=list)
    benefits: list[PostingExtractBenefitOut] = Field(default_factory=list)
    responsibilities: list[PostingExtractResponsibilityOut] = Field(default_factory=list)
    skills: list[PostingExtractSkillOut] = Field(default_factory=list)
    contract_type: PostingExtractContractOut | None = None
    work_hours: PostingExtractHoursOut | None = None
    schedule_cues: list[PostingExtractScheduleCueOut] = Field(default_factory=list)
    travel_required: PostingExtractTravelOut | None = None
    onsite_policy: PostingExtractOnsiteOut | None = None
    work_authorization: PostingExtractWorkAuthorizationOut | None = None
    grade_requirement: PostingExtractGradeOut | None = None
    opportunity_type: str | None = None
    application_deadline: date | None = None
    values_cues: list[str] = Field(default_factory=list)
    field_confidence: dict[str, float] = Field(default_factory=dict)

    @field_validator(
        "language_requirements",
        "prerequisites",
        "responsibilities",
        "skills",
        "schedule_cues",
        "values_cues",
        mode="before",
    )
    @classmethod
    def _coerce_lists(cls, value):
        return [] if value is None else value

    @field_validator("benefits", mode="before")
    @classmethod
    def _coerce_benefits(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        coerced: list = []
        for item in value:
            if isinstance(item, str):
                coerced.append({"kind": "other", "raw": item, "confidence": 0.5})
            else:
                coerced.append(item)
        return coerced

    @field_validator("field_confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value):
        return {} if value is None else value


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


GapStatus = Literal["met", "partial", "missing"]


class PostingGapEvidenceOut(BaseModel):
    """One user-side evidence ref on a gap row (plan 212 S1.1).

    A display ref, not a lookup key: `source` names the evidence ledger
    kind (experience / assessment / cv_document), `label` the item's
    own title when it has one. The frontend localizes the source kind;
    the label is the user's own data."""

    source: str = Field(min_length=1, max_length=30)
    label: str = Field(default="", max_length=120)


class PostingGapRowOut(BaseModel):
    """One requirement row of the evidence-first gap report.

    `raw_label` is the posting's verbatim wording — a label that never
    resolved to a taxonomy key keeps its row (`skill_key`/`label` null)
    but carries no quote: the quote joins on the resolved key. There is
    deliberately no score field on this surface."""

    raw_label: str = Field(max_length=200)
    skill_key: str | None = None
    label: str | None = None
    required_level: int | None = Field(default=None, ge=0, le=10)
    user_level: int | None = Field(default=None, ge=0, le=10)
    status: GapStatus
    priority: str = Field(default="bonus", max_length=20)
    kind: str = Field(default="skill", max_length=20)
    evidence_quote: str = Field(default="", max_length=400)
    user_evidence: list[PostingGapEvidenceOut] = Field(default_factory=list, max_length=4)


class PostingGapOut(BaseModel):
    """The posting gap report (plan 212 S1.1): requirements grouped by
    the extractor's closed priority vocabulary, each row evidence-backed
    or explicitly bare. NOT a match score — the match card lives on its
    own and is never duplicated here."""

    must_have: list[PostingGapRowOut] = Field(default_factory=list, max_length=40)
    nice_to_have: list[PostingGapRowOut] = Field(default_factory=list, max_length=40)
    bonus: list[PostingGapRowOut] = Field(default_factory=list, max_length=40)


class PostingSimilarOut(BaseModel):
    ref: str
    title: str
    org: str
    score: float


class PostingSkillRefOut(BaseModel):
    """One required skill as cards render it (plan 140): the posting's
    skill edge resolved to the taxonomy label, ordered by requirement."""

    key: str
    label: str
    required_level: int | None = None
    priority: str | None = None


class PostingOut(BaseModel):
    id: UUID
    ref: str = ""
    source_id: UUID
    external_id: str
    title: str
    org: str
    org_key: str = ""
    org_match_state: str | None = None
    location: PostingLocationOut
    url: str
    seniority: str | None = None
    employment_type: str | None = None
    work_authorization: str | None = None
    opportunity_type: str | None = None
    application_deadline: date | None = None
    contract_type: str | None = None
    work_hours: str | None = None
    hours_per_week_min: float | None = None
    hours_per_week_max: float | None = None
    travel_class: str | None = None
    education_level: str | None = None
    onsite_policy: str | None = None
    salary_currency: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_period: str | None = None
    salary_basis: str | None = None
    salary_normalized_min: float | None = None
    salary_normalized_max: float | None = None
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    status: str
    repost_count: int = 0
    last_verified_at: datetime | None = None
    duplicate_of_id: UUID | None = None
    trust_flags: dict = Field(default_factory=dict)
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
    # Card skill strip (plan 140): requirement-ordered, bounded projection.
    skills: list[PostingSkillRefOut] = Field(default_factory=list)


class PostingSafetyFlagOut(BaseModel):
    key: str
    label: str
    evidence: str = ""


class PostingDetailOut(PostingOut):
    """Detail view: full extract, source attribution, the
    match-score card, the evidence-first gap report and the
    similar-postings rail."""

    description: str = ""
    extract: PostingExtractOut | None = None
    source_title: str = ""
    source_connector: str = ""
    source_synced_at: datetime | None = None
    match: PostingMatchOut | None = None
    gap: PostingGapOut | None = None
    similar: list[PostingSimilarOut] = Field(default_factory=list)
    gate_overrides: dict[str, bool] = Field(default_factory=dict)
    safety_flags: list[PostingSafetyFlagOut] = Field(default_factory=list)


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
    job_titles: dict[str, str] = Field(default_factory=dict)


class SeenIn(BaseModel):
    posting_ids: list[UUID] = Field(min_length=1, max_length=200)


class SmartSearchIn(BaseModel):
    """One free-text search sentence (plan 179)."""

    query: str = Field(min_length=1, max_length=300)


class SmartSearchOut(BaseModel):
    """The mapped spec, its honest echo, cache state and the resolved
    explore-filter params the client applies into the URL state."""

    spec: dict
    interpreted: str
    cached: bool
    filters: dict


class SaveIn(BaseModel):
    posting_id: UUID
    saved: bool = True


class AppliedIn(BaseModel):
    posting_id: UUID
    applied_via_url: str = Field(default="", max_length=1000)
    stage: ApplicationStage | None = None


class MapIn(BaseModel):
    catalog_job_id: UUID


class PostingChangeOut(BaseModel):
    """One journal row (plan 142): actor kind + links (ids and knobs
    only), the operation's parameters, duration and the capped diff."""

    id: UUID
    occurred_at: datetime
    actor_kind: str
    actor_ref: dict = Field(default_factory=dict)
    operation: dict = Field(default_factory=dict)
    duration_ms: int | None = None
    diff: dict = Field(default_factory=dict)
    outcome: str = "ok"


class PostingsHistoryOut(BaseModel):
    """The posting history read: newest-first journal page."""

    items: list[PostingChangeOut]
    total: int
    limit: int
    offset: int
    posting_id: UUID
