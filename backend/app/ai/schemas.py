"""Pydantic schemas for every structured AI output (validated before storage)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.enums import (
    DemandOutlook,
    EducationLevel,
    Environment,
    PhysicalActivity,
    PrerequisiteStatus,
    RelationType,
)
from app.schemas.job import Aspect, JobAttributes


class ProfileInsight(BaseModel):
    """Result of analyzing a student profile."""

    summary: str = Field(min_length=1, max_length=2000)
    strengths: list[str] = Field(default_factory=list, max_length=10)
    watchouts: list[str] = Field(default_factory=list, max_length=10)
    suggested_interest_keys: list[str] = Field(default_factory=list, max_length=15)
    suggested_skill_keys: list[str] = Field(default_factory=list, max_length=15)


class DraftSkillRequirement(BaseModel):
    """A skill requirement the AI attaches to a drafted job."""

    skill_key: str = Field(min_length=1, max_length=80)
    required_level: int = Field(default=5, ge=1, le=10)
    importance: Literal["core", "important", "bonus"] = "important"


class AssessmentOption(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=500)
    scores: dict = Field(default_factory=dict)


class AssessmentQuestionDraft(BaseModel):
    kind: Literal["scenario_mcq", "time_allocation", "ranking", "slider"] = (
        "scenario_mcq"
    )
    prompt: str = Field(min_length=1, max_length=800)
    help: str = Field(default="", max_length=500)
    options: list[AssessmentOption] = Field(default_factory=list, max_length=6)


class AssessmentQuestionSet(BaseModel):
    """AI-drafted question batch for phase 3 (validated onto taxonomy)."""

    questions: list[AssessmentQuestionDraft] = Field(
        default_factory=list, max_length=10
    )


class JobDraft(BaseModel):
    """A single AI-proposed job, aligned to the taxonomy."""

    code: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    title: str = Field(min_length=2, max_length=160)
    family_key: str = Field(min_length=2, max_length=80)
    short_description: str = Field(default="", max_length=2000)
    attributes: JobAttributes = Field(default_factory=JobAttributes)
    interest_keys: list[str] = Field(default_factory=list, max_length=12)
    skills: list[DraftSkillRequirement] = Field(default_factory=list, max_length=15)


class RelationSuggestion(BaseModel):
    """A proposed edge between two jobs (by code)."""

    from_code: str
    to_code: str
    relation_type: RelationType
    weight: float = Field(default=0.5, ge=0, le=1)
    rationale: str = Field(default="", max_length=500)
    confidence: float = Field(default=0.5, ge=0, le=1)


class JobDraftSet(BaseModel):
    """Generated jobs + relations among them."""

    drafts: list[JobDraft] = Field(default_factory=list, max_length=20)
    relation_suggestions: list[RelationSuggestion] = Field(
        default_factory=list, max_length=60
    )
    rationale_note: str = Field(default="", max_length=1000)


class ScoredAspectOut(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=800)
    weight: float = Field(default=0.5, ge=0, le=1)


class PrerequisiteCheckOut(BaseModel):
    requirement: str = Field(min_length=1, max_length=300)
    status: PrerequisiteStatus
    detail: str = Field(default="", max_length=500)


class MatchResult(BaseModel):
    """AI scoring of one job for one user."""

    score: float = Field(ge=0, le=10)
    confidence: float = Field(default=0.5, ge=0, le=1)
    summary: str = Field(default="", max_length=2000)
    positives: list[ScoredAspectOut] = Field(default_factory=list, max_length=8)
    negatives: list[ScoredAspectOut] = Field(default_factory=list, max_length=8)
    prerequisites: list[PrerequisiteCheckOut] = Field(
        default_factory=list, max_length=8
    )


class AdmissionRow(BaseModel):
    year: int = Field(ge=1990, le=2100)
    baseline_score: Optional[float] = None
    top_score: Optional[float] = None
    quota: Optional[int] = None
    units: str = Field(default="points", max_length=40)
    confidence: float = Field(default=0.8, ge=0, le=1)


class DepartmentExtraction(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    field_key: str = Field(default="", max_length=80)
    degree: Literal["vocational", "bachelor", "master", "phd"] = "bachelor"
    duration_years: int = Field(default=4, ge=1, le=10)
    language: str = Field(default="", max_length=30)
    application_deadline: Optional[str] = Field(default=None, max_length=10)
    admissions: list[AdmissionRow] = Field(default_factory=list, max_length=10)


class UniversityExtractionItem(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str = Field(default="", max_length=80)
    city: str = Field(default="", max_length=80)
    university_type: Literal["public", "private", "other"] = "public"
    departments: list[DepartmentExtraction] = Field(default_factory=list, max_length=60)


class UniversityExtraction(BaseModel):
    """Structured result of parsing a university/admissions document."""

    universities: list[UniversityExtractionItem] = Field(
        default_factory=list, max_length=30
    )


class ChatReply(BaseModel):
    """Chatbot answer with optional deep-links into the catalog + postings."""

    answer: str = Field(min_length=1, max_length=8000)
    referenced_job_codes: list[str] = Field(default_factory=list, max_length=20)
    referenced_posting_refs: list[str] = Field(default_factory=list, max_length=20)


class DraftPathStep(BaseModel):
    """One step of an AI-drafted path; typed refs are resolved server-side."""

    kind: Literal["education", "job", "experience", "certification"]
    family_key: Optional[str] = Field(default=None, max_length=80)
    skill_key: Optional[str] = Field(default=None, max_length=80)
    education_level: Optional[str] = Field(default=None, max_length=30)
    label: str = Field(default="", max_length=200)
    optional: bool = False


class DraftPath(BaseModel):
    """An AI-proposed route to a destination job."""

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    steps: list[DraftPathStep] = Field(default_factory=list, max_length=8)


class PathDraftSet(BaseModel):
    """AI-drafted career paths for one job."""

    paths: list[DraftPath] = Field(default_factory=list, max_length=3)


__all__ = [
    "ProfileInsight",
    "JobDraft",
    "RelationSuggestion",
    "JobDraftSet",
    "MatchResult",
    "UniversityExtraction",
    "ChatReply",
    "PathDraftSet",
    "Aspect",
    "DemandOutlook",
    "EducationLevel",
    "Environment",
    "PhysicalActivity",
]
