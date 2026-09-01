from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    CareerStage,
    EducationLevel,
    PhysicalActivity,
    PhysicalCondition,
    TagSource,
)
from app.services.stages_service import max_birth_year

WeightedTag = Field(ge=1, le=5)


class BasicSection(BaseModel):
    """Stage-aware basics: grade/years fields are student-only (plan 25).

    `timezone` is the IANA zone quiet hours (36), digests/check-ins (29)
    and misfire scheduling resolve against — never a UTC offset string.
    """

    birth_year: Optional[int] = Field(default=None, ge=1950, le=max_birth_year())
    education_level: EducationLevel = EducationLevel.HIGH_SCHOOL
    grade: Optional[str] = Field(default=None, max_length=30)
    career_stage: Optional[CareerStage] = None
    country: str = Field(default="", max_length=80)
    city: str = Field(default="", max_length=80)
    timezone: str = Field(default="UTC", max_length=60)

    @field_validator("timezone")
    @classmethod
    def _valid_iana_zone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"unknown IANA timezone: {value!r}") from exc
        return value


class FavoriteSubject(BaseModel):
    key: str = Field(max_length=80)
    weight: int = WeightedTag


class LanguageSkill(BaseModel):
    code: str = Field(max_length=10)
    level: Literal["basic", "intermediate", "advanced", "native"] = "intermediate"


class AcademicsSection(BaseModel):
    favorite_subjects: list[FavoriteSubject] = Field(
        default_factory=list, max_length=20
    )
    # Nullable (plan 25): only meaningful for the student stage.
    gpa_band: Optional[
        Literal["low", "below_average", "average", "good", "excellent", "unknown"]
    ] = None
    languages: list[LanguageSkill] = Field(default_factory=list, max_length=10)


class InterestItem(BaseModel):
    tag_key: str = Field(max_length=80)
    weight: int = WeightedTag
    source: TagSource = TagSource.SELF


class HobbyItem(BaseModel):
    key: Optional[str] = Field(default=None, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    weight: int = WeightedTag


class LikeDislikeItem(BaseModel):
    tag_key: Optional[str] = Field(default=None, max_length=80)
    label: str = Field(min_length=1, max_length=200)
    weight: int = WeightedTag


class AspirationItem(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    tag_keys: list[str] = Field(default_factory=list, max_length=10)
    notes: str = Field(default="", max_length=500)


class WorkPreferencesSection(BaseModel):
    teamwork: Literal[1, 2, 3, 4, 5] = 3
    environment: Literal[1, 2, 3, 4, 5] = 3
    structure: Literal[1, 2, 3, 4, 5] = 3
    pace: Literal[1, 2, 3, 4, 5] = 3
    leadership: Literal[1, 2, 3, 4, 5] = 3
    remote_ok: bool = True
    focus_areas: list[Literal["people", "things", "data", "ideas"]] = Field(
        default_factory=list, max_length=4
    )
    salary_priority: Literal[1, 2, 3, 4, 5] = 3
    stability_priority: Literal[1, 2, 3, 4, 5] = 3
    physical_activity: PhysicalActivity = PhysicalActivity.LIGHT
    creativity_priority: Literal[1, 2, 3, 4, 5] = 3


class ConstraintsSection(BaseModel):
    physical_conditions: list[PhysicalCondition] = Field(
        default_factory=list, max_length=6
    )
    max_education_years: Optional[int] = Field(default=None, ge=0, le=12)
    willing_to_relocate: bool = True
    hours_available_per_week: Optional[int] = Field(default=None, ge=0, le=100)


class ExperienceItem(BaseModel):
    """An experience evidence item (promoted to tables by plan 40)."""

    title: str = Field(min_length=1, max_length=160)
    org: str = Field(default="", max_length=160)
    kind: Literal["internship", "part_time", "volunteer", "project", "freelance"] = (
        "project"
    )
    start_year: int = Field(ge=1990, le=2030)
    end_year: Optional[int] = Field(default=None, ge=1990, le=2030)
    hours_per_week: Optional[int] = Field(default=None, ge=1, le=80)
    skill_keys: list[str] = Field(default_factory=list, max_length=15)
    description: str = Field(default="", max_length=1000)


class ScoringWeights(BaseModel):
    """Per-dimension importance sliders (1–5) for the fit engine (22)."""

    skills: int = Field(default=3, ge=1, le=5)
    location: int = Field(default=3, ge=1, le=5)
    experience: int = Field(default=3, ge=1, le=5)
    education: int = Field(default=3, ge=1, le=5)
    interests: int = Field(default=3, ge=1, le=5)


class PreferencesSection(BaseModel):
    """Fit-engine preferences; hard constraints stay in `constraints`."""

    scoring_weights: ScoringWeights = Field(default_factory=ScoringWeights)


class ProfileAISummary(BaseModel):
    summary: str
    strengths: list[str] = Field(default_factory=list, max_length=10)
    watchouts: list[str] = Field(default_factory=list, max_length=10)
    suggested_interest_keys: list[str] = Field(default_factory=list, max_length=15)
    suggested_skill_keys: list[str] = Field(default_factory=list, max_length=15)
    model: str = ""
    generated_at: Optional[datetime] = None


class ProfileSectionUpdate(BaseModel):
    """Partial profile update — each section is optional."""

    basics: Optional[BasicSection] = None
    academics: Optional[AcademicsSection] = None
    interests: Optional[list[InterestItem]] = Field(default=None, max_length=40)
    hobbies: Optional[list[HobbyItem]] = Field(default=None, max_length=30)
    likes: Optional[list[LikeDislikeItem]] = Field(default=None, max_length=30)
    dislikes: Optional[list[LikeDislikeItem]] = Field(default=None, max_length=30)
    aspirations: Optional[list[AspirationItem]] = Field(default=None, max_length=20)
    work_preferences: Optional[WorkPreferencesSection] = None
    experience: Optional[list[ExperienceItem]] = Field(default=None, max_length=30)
    preferences: Optional[PreferencesSection] = None
    constraints: Optional[ConstraintsSection] = None


DEFAULT_BASICS: dict = BasicSection().model_dump(mode="json")
DEFAULT_ACADEMICS: dict = AcademicsSection().model_dump(mode="json")
DEFAULT_WORK_PREFERENCES: dict = WorkPreferencesSection().model_dump(mode="json")
DEFAULT_CONSTRAINTS: dict = ConstraintsSection().model_dump(mode="json")
DEFAULT_PREFERENCES: dict = PreferencesSection().model_dump(mode="json")
