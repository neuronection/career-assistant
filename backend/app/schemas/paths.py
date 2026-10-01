"""Schemas for career paths (curated + computed graph)."""

from uuid import UUID

from pydantic import BaseModel, Field


class PathStepOut(BaseModel):
    position: int
    kind: str
    label: str = ""
    optional: bool = False
    family_key: str | None = None
    family_label: str | None = None
    skill_key: str | None = None
    skill_label: str | None = None
    education_level: str | None = None


class CareerPathOut(BaseModel):
    id: UUID
    job_id: UUID
    title: str
    description: str
    source: str
    status: str
    steps: list[PathStepOut] = Field(default_factory=list)


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
