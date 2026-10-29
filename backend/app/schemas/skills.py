"""Schemas for the skill ontology user surface (Phase 21)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import JobSkillImportance, UserSkillSource
from app.schemas.job import JobSkillOut
from app.schemas.posting import PostingOut


class UserSkillIn(BaseModel):
    skill_key: str = Field(min_length=1, max_length=80)
    level: int = Field(ge=1, le=10)
    source: UserSkillSource = UserSkillSource.SELF_REPORT
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class UserSkillsIn(BaseModel):
    """Bulk replace of the caller's self-reported skills.

    Rows from other sources (assessment/experience/ai_inferred/document) are
    never touched; self_report rows are replaced by this payload.
    """

    skills: list[UserSkillIn] = Field(default_factory=list, max_length=60)


class UserSkillOut(BaseModel):
    skill_id: UUID
    key: str
    label: str
    category: str
    level: int
    source: UserSkillSource
    confidence: float
    level_anchors: list[dict] = Field(default_factory=list)
    derive_enabled: bool = True
    hidden: bool = False


class UserSkillPatchIn(BaseModel):
    derive_enabled: bool


class GapOut(BaseModel):
    skill_id: UUID
    key: str
    label: str
    required_level: int
    importance: JobSkillImportance
    user_level: int | None = None
    delta: int | None = None
    suggestion: str = ""
    next_step: str | None = None


class SkillGapReport(BaseModel):
    job_id: UUID
    job_code: str
    job_title: str
    gaps: list[GapOut] = Field(default_factory=list)


class SkillStatsOut(BaseModel):
    """The skill page's aggregate block (plan 148) — one server-side
    aggregate pass, no per-row queries."""

    demand_count: int = 0
    level_histogram: list[dict] = Field(default_factory=list)
    avg_required_level: float | None = None
    user_count: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    corroboration: dict | None = None


class SkillJobsOut(BaseModel):
    """A skill plus the published jobs asking for it."""

    id: UUID
    key: str
    label: str
    category: str
    description: str
    parent_id: UUID | None = None
    level_anchors: list[dict] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    status: str
    children_keys: list[str] = Field(default_factory=list)
    jobs: list[JobSkillOut] = Field(default_factory=list)
    # Plan 148 additive page fields: the aggregate block and the merged
    # banner target (survivor key, None when the row was never merged).
    stats: SkillStatsOut | None = None
    merged_into: str | None = None


class SkillChangeOut(BaseModel):
    """One skill journal row (plan 148): event kind, actor role and the
    ids-only actor ref + capped detail."""

    id: UUID
    occurred_at: datetime
    event: str
    actor_kind: str
    actor_ref: dict = Field(default_factory=dict)
    detail: dict = Field(default_factory=dict)


class SkillHistoryOut(BaseModel):
    """The skill history read: newest-first journal page."""

    items: list[SkillChangeOut]
    total: int
    limit: int
    offset: int
    skill_id: UUID
    skill_key: str


class SkillGraphNodeOut(BaseModel):
    """One depth-1 subgraph vertex (plan 148) — ConceptGraphView-shaped."""

    id: UUID
    key: str
    label: str
    status: str


class SkillGraphEdgeOut(BaseModel):
    """One approved edge, stored direction (plan 138 semantics)."""

    id: UUID
    source: UUID
    target: UUID
    relation: str


class SkillRelationsOut(BaseModel):
    """The approved depth-1 neighborhood of one skill."""

    nodes: list[SkillGraphNodeOut] = Field(default_factory=list)
    edges: list[SkillGraphEdgeOut] = Field(default_factory=list)


class SkillPositionsOut(BaseModel):
    """The postings demanding one skill — the postings list projection
    shape, so the existing cards render identically."""

    items: list[PostingOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
