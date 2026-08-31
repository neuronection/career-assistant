"""Schemas for the skill ontology user surface (Phase 21)."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import JobSkillImportance, UserSkillSource
from app.schemas.job import JobSkillOut


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


class GapOut(BaseModel):
    skill_id: UUID
    key: str
    label: str
    required_level: int
    importance: JobSkillImportance
    user_level: Optional[int] = None
    delta: Optional[int] = None
    suggestion: str = ""
    next_step: Optional[str] = None


class SkillGapReport(BaseModel):
    job_id: UUID
    job_code: str
    job_title: str
    gaps: list[GapOut] = Field(default_factory=list)


class SkillJobsOut(BaseModel):
    """A skill plus the published jobs asking for it."""

    id: UUID
    key: str
    label: str
    category: str
    description: str
    parent_id: Optional[UUID] = None
    level_anchors: list[dict] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    status: str
    children_keys: list[str] = Field(default_factory=list)
    jobs: list[JobSkillOut] = Field(default_factory=list)
