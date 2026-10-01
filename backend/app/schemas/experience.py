"""Experience profile API schemas."""

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.rich_text import validate_rich_text


class ExperienceSkillIn(BaseModel):
    skill_key: str = Field(min_length=1, max_length=80)
    role_in_item: Literal["primary", "secondary", "exposure"] = "primary"
    level_claim: int | None = Field(default=None, ge=1, le=10)
    last_used: date | None = None


class ExperienceLinkIn(BaseModel):
    """One attachable URL on an experience item (repo, demo, article…).

    Scheme-allowlisted like the renderer's `_safe_href` so nothing
    javascript:-shaped can enter through any path."""

    label: str = Field(default="", max_length=80)
    url: str = Field(min_length=1, max_length=500)
    kind: Literal["github", "linkedin", "demo", "web"] = "web"

    @field_validator("url")
    @classmethod
    def _scheme_allowlist(cls, value: str) -> str:
        url = value.strip()
        if not re.match(r"^(https?://|mailto:)", url, re.IGNORECASE):
            raise ValueError("link url must be http(s) or mailto")
        return url


class AchievementMetric(BaseModel):
    kind: Literal["time_saved", "scale", "revenue", "quality"]
    value: float
    unit: str = Field(default="", max_length=30)


class AchievementIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    metric: AchievementMetric | None = None

    @field_validator("text")
    @classmethod
    def _rich(cls, value: str) -> str:
        return validate_rich_text(value, 500)


class ExperienceItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    kind: Literal["job", "project", "internship", "volunteer", "freelance"] = "project"
    org_name: str = Field(default="", max_length=200)
    start: date | None = None
    end: date | None = None
    open_ended: bool = False
    hours_per_week: int | None = Field(default=None, ge=1, le=80)
    onsite_policy: Literal["onsite", "hybrid", "remote"] | None = None
    description: str = Field(default="", max_length=2000)
    links: list[ExperienceLinkIn] = Field(default_factory=list, max_length=10)
    source: Literal["self_report", "cv_parse", "assessment", "import"] = "self_report"
    status: Literal["draft", "active"] = "active"
    skills: list[ExperienceSkillIn] = Field(default_factory=list, max_length=15)
    achievements: list[AchievementIn] = Field(default_factory=list, max_length=15)

    @field_validator("description")
    @classmethod
    def _rich(cls, value: str) -> str:
        return validate_rich_text(value, 2000)

    @model_validator(mode="after")
    def _period_sane(self):
        if self.start is None and self.kind != "project":
            raise ValueError("start is required")
        if self.end is None and not self.open_ended:
            raise ValueError("end is required unless open_ended")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("end cannot precede start")
        return self


class ExperienceItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    kind: Literal["job", "project", "internship", "volunteer", "freelance"] | None = None
    org_name: str | None = Field(default=None, max_length=200)
    start: date | None = None
    end: date | None = None
    open_ended: bool | None = None
    hours_per_week: int | None = Field(default=None, ge=1, le=80)
    onsite_policy: Literal["onsite", "hybrid", "remote"] | None = None
    description: str | None = Field(default=None, max_length=2000)
    links: list[ExperienceLinkIn] | None = Field(default=None, max_length=10)
    status: Literal["draft", "active"] | None = None
    skills: list[ExperienceSkillIn] | None = None
    achievements: list[AchievementIn] | None = None

    @field_validator("description")
    @classmethod
    def _rich(cls, value: str | None) -> str | None:
        return None if value is None else validate_rich_text(value, 2000)


class ExperienceSkillOut(BaseModel):
    skill_id: UUID
    skill_key: str
    skill_label: str
    role_in_item: str
    level_claim: int | None = None
    last_used: date | None = None


class AchievementOut(BaseModel):
    id: UUID
    text: str
    metric: dict | None = None


class ExperienceItemOut(BaseModel):
    id: UUID
    kind: str
    title: str
    org_name: str
    org_id: UUID | None = None
    start: date | None = None
    end: date | None = None
    open_ended: bool
    hours_per_week: int | None = None
    onsite_policy: str | None = None
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
    claimed_level: int | None = None
    claim_status: str | None = None


class DerivationOut(BaseModel):
    skills: list[DerivedSkillOut]
    years_of_experience: float


class DerivationApplyOut(BaseModel):
    applied: int
    conflicts: list[dict]
    skipped_disabled: int = 0
    derived: list[DerivedSkillOut]


class EvidenceItemOut(BaseModel):
    id: UUID
    source: str
    experience_item: dict | None = None
    level_value: float | None = None
    confidence: float | None = None
    note: str
    claimed_at: datetime


class EvidenceOut(BaseModel):
    skill_id: UUID
    items: list[EvidenceItemOut]
