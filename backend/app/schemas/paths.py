"""Schemas for career paths (curated + computed graph + user explorer)."""

from uuid import UUID

from pydantic import BaseModel, Field


class PathStepOut(BaseModel):
    id: UUID
    position: int
    kind: str
    label: str = ""
    optional: bool = False
    family_key: str | None = None
    family_label: str | None = None
    skill_key: str | None = None
    skill_label: str | None = None
    education_level: str | None = None
    parent_step_id: UUID | None = None
    edge_label: str = ""


class CareerPathOut(BaseModel):
    id: UUID
    job_id: UUID
    title: str
    description: str
    source: str
    status: str
    job_code: str | None = None
    job_title: str | None = None
    my_flag: str | None = None
    steps: list[PathStepOut] = Field(default_factory=list)


class PathStepFlagOut(BaseModel):
    step_id: UUID
    flag: str
    note: str = ""


class PathStepSkillOut(BaseModel):
    skill_id: UUID
    key: str
    label: str
    user_level: int | None = None
    required_level: int | None = None


class PathStepDetailOut(PathStepOut):
    my_flag: str | None = None
    my_note: str = ""
    skill: PathStepSkillOut | None = None


class PathDetailOut(BaseModel):
    """One path with the caller's marks, per-step skill gaps and the
    profile-completeness summary for the header."""

    id: UUID
    job_id: UUID
    title: str
    description: str
    source: str
    status: str
    job_code: str | None = None
    job_title: str | None = None
    my_flag: str | None = None
    my_note: str = ""
    skills_total: int = 0
    skills_met: int = 0
    steps: list[PathStepDetailOut] = Field(default_factory=list)


class PathFlagIn(BaseModel):
    """Set one mark on the path (step_id NULL) or one step; flag NULL
    clears the mark. Marks are preferences — nothing consumes them in
    scoring."""

    step_id: UUID | None = None
    flag: str | None = Field(default=None, pattern="^(interested|dismissed|pinned)$")
    note: str = Field(default="", max_length=2000)


class PathStepIn(BaseModel):
    """One step of a user path draft. `parent` is the 0-based index of the
    submitted steps list this step branches from (None = main chain)."""

    kind: str = Field(pattern="^(job|skill|education|certification|experience|milestone)$")
    label: str = Field(min_length=1, max_length=200)
    skill_key: str | None = Field(default=None, max_length=80)
    family_key: str | None = Field(default=None, max_length=80)
    education_level: str | None = Field(default=None, max_length=30)
    optional: bool = False
    parent: int | None = Field(default=None, ge=0)
    edge_label: str = Field(default="", max_length=120)


class PathCreateIn(BaseModel):
    """A review-first user path (chat save or manual create): draft
    status, owned by its creator's path flag, never auto-activated."""

    job_ref: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    steps: list[PathStepIn] = Field(default_factory=list, max_length=16)


class PathUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class PathStepUpdateIn(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = Field(
        default=None, pattern="^(job|skill|education|certification|experience|milestone)$"
    )
    optional: bool | None = None
    edge_label: str | None = Field(default=None, max_length=120)
    education_level: str | None = Field(default=None, max_length=30)
    skill_key: str | None = Field(default=None, max_length=80)
    family_key: str | None = Field(default=None, max_length=80)


class PathReorderIn(BaseModel):
    """Reorder one sibling set (a branch, or the main chain with
    parent_step_id NULL) — `ordered` lists every sibling in its new
    order."""

    parent_step_id: UUID | None = None
    ordered: list[UUID] = Field(min_length=1, max_length=32)


class GraphNodeOut(BaseModel):
    code: str
    title: str
    family_key: str
    demand: str | None = None
    depth: int = 0


class GraphEdgeOut(BaseModel):
    from_code: str
    to_code: str
    relation_type: str
    weight: float


class PathGraphOut(BaseModel):
    """BFS over `leads_to`/`prerequisite_of` edges pointing INTO the job."""

    root: str
    nodes: list[GraphNodeOut] = Field(default_factory=list)
    edges: list[GraphEdgeOut] = Field(default_factory=list)
    truncated: bool = False
