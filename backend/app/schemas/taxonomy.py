from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class InterestTagOut(BaseModel):
    id: UUID
    key: str
    label: str
    category: str
    description: str
    deprecated: bool = False
    kind: Literal["topic", "industry"] = "topic"

    model_config = {"from_attributes": True}


class SkillOut(BaseModel):
    id: UUID
    key: str
    label: str
    category: str
    description: str
    parent_id: UUID | None = None
    parent_source: Literal["curated", "learned"] | None = None
    level_anchors: list[dict] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    status: str
    origin: str

    model_config = {"from_attributes": True}


class TaxonomySkillStats(BaseModel):
    total: int
    active: int
    proposed: int
    deprecated: int
    auto_promoted: int
    promoted_7d: int


class TaxonomyQueueStats(BaseModel):
    relations: int
    enrichment: int
    paths: int
    translations: int
    total: int


class TaxonomyStatsOut(BaseModel):
    """Backlog counts behind the taxonomy work-queue bar (plan 161)."""

    skills: TaxonomySkillStats
    queue: TaxonomyQueueStats


class TagCreateIn(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=500)
    kind: Literal["topic", "industry"] = "topic"


class TagUpdateIn(BaseModel):
    # extra="forbid" makes key-change attempts fail loudly (keys are immutable)
    model_config = {"extra": "forbid"}

    label: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=500)
    deprecated: bool | None = None
    kind: Literal["topic", "industry"] | None = None


class SkillUpdateIn(BaseModel):
    """Admin edits for a skill; keys stay immutable, lifecycle via status."""

    model_config = {"extra": "forbid"}

    label: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=500)
    status: str | None = None
    parent_id: UUID | None = None
    aliases: list[str] | None = Field(default=None, max_length=20)
    level_anchors: list[dict] | None = None


class SkillBulkIn(BaseModel):
    """Body of POST /admin/skills/bulk — one lifecycle action over many skills.

    Merge is many-to-one: every id merges into `target_id` (an active skill).
    """

    model_config = {"extra": "forbid"}

    ids: list[UUID] = Field(min_length=1, max_length=200)
    action: Literal["promote", "deprecate", "restore", "delete", "merge"]
    target_id: UUID | None = None

    @model_validator(mode="after")
    def _merge_requires_target(self) -> "SkillBulkIn":
        if self.action == "merge" and self.target_id is None:
            raise ValueError("target_id is required for merge")
        if self.action != "merge" and self.target_id is not None:
            raise ValueError("target_id is only valid for merge")
        return self


class SkillBulkFailure(BaseModel):
    """One id the bulk call could not act on, and why (verbatim reason)."""

    id: UUID
    key: str = ""
    reason: str
    job_refs: int | None = None
    profile_refs: int | None = None


class SkillBulkOut(BaseModel):
    """Outcome of one bulk call — acted-on ids plus per-item failures."""

    affected: list[UUID] = Field(default_factory=list)
    failed: list[SkillBulkFailure] = Field(default_factory=list)


class ResolutionThresholdsIn(BaseModel):
    """Admin overrides for `posting_resolve.thresholds` (clamped)."""

    model_config = {"extra": "forbid"}

    candidate_trigram_floor: float = Field(ge=0.0, le=1.0)
    candidate_cosine_floor: float = Field(ge=0.0, le=1.0)
    candidate_top_k: int = Field(ge=1, le=5)
    dedup_trigram_bar: float = Field(ge=0.0, le=1.0)
    dedup_cosine_bar: float = Field(ge=0.0, le=1.0)
    corroboration_min_postings: int = Field(ge=1)
    corroboration_cap: int = Field(ge=1)


class ResolutionThresholdsOut(BaseModel):
    """Effective resolution thresholds (constant fallbacks included)."""

    candidate_trigram_floor: float
    candidate_cosine_floor: float
    candidate_top_k: int
    dedup_trigram_bar: float
    dedup_cosine_bar: float
    corroboration_min_postings: int
    corroboration_cap: int


class ResolutionLastRunOut(BaseModel):
    """The newest succeeded POSTING_EXTRACT result summary (missing or
    mistyped counters on an old run read as defaults)."""

    job_id: str | None
    status: str | None
    created_at: datetime | None
    finished_at: datetime | None
    labels: int = 0
    exact_hits: int = 0
    pass2_matches: int = 0
    new_proposals: int = 0
    gate_blocks: int = 0
    degraded: bool = False
    replay: bool = False


class ResolutionRollingOut(BaseModel):
    """Rolling sums + derived rates over the window's extract jobs."""

    window: str
    runs: int
    replay_runs: int
    degraded_runs: int
    labels: int
    exact_hits: int
    pass2_matches: int
    new_proposals: int
    gate_blocks: int
    match_rate: float
    new_rate: float
    block_rate: float
    replay_rate: float
    degrade_rate: float


class ResolutionStatsOut(BaseModel):
    """The Resolution section's KPI payload (plan 153 slice 4)."""

    last_run: ResolutionLastRunOut
    rolling: ResolutionRollingOut
    failing_schedules: int
