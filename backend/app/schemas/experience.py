"""Experience profile API schemas (plan 40)."""

from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ExperienceSkillIn(BaseModel):
    skill_key: str = Field(min_length=1, max_length=80)
    role_in_item: Literal["primary", "secondary", "exposure"] = "primary"
    level_claim: Optional[int] = Field(default=None, ge=1, le=10)
    last_used: Optional[date] = None


class AchievementMetric(BaseModel):
    kind: Literal["time_saved", "scale", "revenue", "quality"]
    value: float
    unit: str = Field(default="", max_length=30)


class AchievementIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    metric: Optional[AchievementMetric] = None


class ExperienceItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    kind: Literal["job", "project", "internship", "volunteer", "freelance"] = "project"
    org_name: str = Field(default="", max_length=200)
    start: Optional[date] = None
    end: Optional[date] = None
    open_ended: bool = False
    hours_per_week: Optional[int] = Field(default=None, ge=1, le=80)
    onsite_policy: Optional[Literal["onsite", "hybrid", "remote"]] = None
    description: str = Field(default="", max_length=2000)
    links: list[dict] = Field(default_factory=list, max_length=10)
    source: Literal["self_report", "cv_parse", "assessment", "import"] = "self_report"
    status: Literal["draft", "active"] = "active"
    skills: list[ExperienceSkillIn] = Field(default_factory=list, max_length=15)
    achievements: list[AchievementIn] = Field(default_factory=list, max_length=15)

    @model_validator(mode="after")
    def _period_sane(self):
        if self.start is None:
            raise ValueError("start is required")
        if self.end is None and not self.open_ended:
            raise ValueError("end is required unless open_ended")
        if self.end is not None and self.end < self.start:
            raise ValueError("end cannot precede start")
        return self


class ExperienceItemUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    kind: Optional[
        Literal["job", "project", "internship", "volunteer", "freelance"]
    ] = None
    org_name: Optional[str] = Field(default=None, max_length=200)
    start: Optional[date] = None
    end: Optional[date] = None
    open_ended: Optional[bool] = None
    hours_per_week: Optional[int] = Field(default=None, ge=1, le=80)
    onsite_policy: Optional[Literal["onsite", "hybrid", "remote"]] = None
    description: Optional[str] = Field(default=None, max_length=2000)
    links: Optional[list[dict]] = Field(default=None, max_length=10)
    status: Optional[Literal["draft", "active"]] = None
    skills: Optional[list[ExperienceSkillIn]] = None
    achievements: Optional[list[AchievementIn]] = None


class ExperienceSkillOut(BaseModel):
    skill_id: UUID
    skill_key: str
    skill_label: str
    role_in_item: str
    level_claim: Optional[int] = None
    last_used: Optional[date] = None


class AchievementOut(BaseModel):
    id: UUID
    text: str
    metric: Optional[dict] = None


class ExperienceItemOut(BaseModel):
    id: UUID
    kind: str
    title: str
    org_name: str
    org_id: Optional[UUID] = None
    start: date
    end: Optional[date] = None
    open_ended: bool
    hours_per_week: Optional[int] = None
    onsite_policy: Optional[str] = None
    description: str
    links: list[dict]
    source: str
    status: str
    created_at: datetime
    skills: list[ExperienceSkillOut]
    achievements: list[AchievementOut]


class ExperienceOut(BaseModel):
    items: list[ExperienceItemOut]
    years_of_experience: float


class DerivedSkillOut(BaseModel):
    skill_id: UUID
    skill_label: str
    months: float
    level: float
    confidence: float
    supporting_items: list[str]


class DerivationOut(BaseModel):
    skills: list[DerivedSkillOut]
    years_of_experience: float


class DerivationApplyOut(BaseModel):
    applied: int
    conflicts: list[dict]
    derived: list[DerivedSkillOut]


class EvidenceItemOut(BaseModel):
    id: UUID
    source: str
    experience_item: Optional[dict] = None
    level_value: Optional[float] = None
    confidence: Optional[float] = None
    note: str
    claimed_at: datetime


class EvidenceOut(BaseModel):
    skill_id: UUID
    items: list[EvidenceItemOut]
