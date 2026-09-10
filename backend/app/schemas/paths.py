"""Schemas for career paths (curated + computed graph)."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PathStepOut(BaseModel):
    position: int
    kind: str
    label: str = ""
    optional: bool = False
    family_key: Optional[str] = None
    family_label: Optional[str] = None
    skill_key: Optional[str] = None
    skill_label: Optional[str] = None
    education_level: Optional[str] = None


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
    demand: Optional[str] = None
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
