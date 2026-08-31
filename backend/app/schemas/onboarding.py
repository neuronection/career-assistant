"""Express onboarding + target mode schemas (Phase 27)."""

from typing import Optional

from pydantic import BaseModel, Field


class ArchetypeOut(BaseModel):
    code: str
    title: str
    family_key: str
    score: float


class ResolveOut(BaseModel):
    query: str
    resolved_by: str
    families: list[dict]
    skill_keys: list[str]
    archetypes: list[ArchetypeOut]


class ExpressIn(BaseModel):
    targets: list[str] = Field(min_length=1, max_length=3)
    location: Optional[str] = Field(default=None, max_length=80)
    remote: Optional[bool] = None
    stage: Optional[str] = Field(default=None, max_length=20)
    min_fit: float = Field(default=7.0, ge=0, le=10)
    max_per_day: int = Field(default=5, ge=1, le=50)


class ExpressOut(BaseModel):
    target_families: list[str]
    target_labels: list[str]
    interest_tags_written: int
    target_mode: bool


class CompletenessSegment(BaseModel):
    key: str
    label: str
    filled: bool
    hint: str
    href: str


class CompletenessOut(BaseModel):
    percent: int
    segments: list[CompletenessSegment]


class NudgeOut(BaseModel):
    type: str
    message: str


class TargetDashboardOut(BaseModel):
    families: list[str]
    open_postings: dict
    adjacent_targets: list[dict]
    nudges: list[NudgeOut]
    completeness: CompletenessOut
