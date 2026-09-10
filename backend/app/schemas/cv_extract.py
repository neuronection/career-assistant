"""CV extraction contract: `CvExtract` — the structured AI
output of the CV-parse task.

Every field carries provenance: `confidence` 0–1, an `evidence_quote`
verbatim from the source text, and a page reference. Unset ≠ empty
: nothing is guessed, optional-with-threshold only.
The `cv_field_map` (services/cv_field_map.py) binds these fields to
profile targets and generates the extraction prompt — schema and prompts
cannot drift.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.enums import AchievementMetricKind, ExperienceKind


class FieldEvidence(BaseModel):
    quote: str = Field(default="", max_length=1000)
    page: Optional[int] = Field(default=None, ge=0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ExtractedLink(BaseModel):
    kind: Literal["linkedin", "github", "portfolio", "other"] = "other"
    url: str = Field(min_length=1, max_length=500)
    label: str = Field(default="", max_length=120)
    evidence: FieldEvidence = Field(default_factory=FieldEvidence)


class ExtractedBasics(BaseModel):
    full_name: str = Field(default="", max_length=200)
    headline: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=40)
    location: str = Field(default="", max_length=200)
    links: list[ExtractedLink] = Field(default_factory=list, max_length=8)
    evidence: FieldEvidence = Field(default_factory=FieldEvidence)


class ExtractedMetric(BaseModel):
    kind: AchievementMetricKind = AchievementMetricKind.QUALITY
    value: float = Field(gt=0)
    unit: str = Field(default="", max_length=40)


class ExtractedSkill(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    level_claim: Optional[int] = Field(default=None, ge=1, le=10)
    evidence: FieldEvidence = Field(default_factory=FieldEvidence)


class ExtractedAchievement(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    metric: Optional[ExtractedMetric] = None
    evidence: FieldEvidence = Field(default_factory=FieldEvidence)


class ExtractedExperience(BaseModel):
    kind: ExperienceKind = ExperienceKind.JOB
    title: str = Field(min_length=1, max_length=200)
    org: str = Field(default="", max_length=200)
    start: str = Field(default="", max_length=10)
    end: str = Field(default="", max_length=10)
    description: str = Field(default="", max_length=4000)
    skills: list[ExtractedSkill] = Field(default_factory=list, max_length=15)
    achievements: list[ExtractedAchievement] = Field(
        default_factory=list, max_length=10
    )
    evidence: FieldEvidence = Field(default_factory=FieldEvidence)


class ExtractedEducation(BaseModel):
    institution: str = Field(min_length=1, max_length=200)
    program: str = Field(default="", max_length=200)
    level: str = Field(default="", max_length=30)
    start: str = Field(default="", max_length=10)
    end: str = Field(default="", max_length=10)
    grade_band: Optional[
        Literal["low", "below_average", "average", "good", "excellent", "unknown"]
    ] = None
    evidence: FieldEvidence = Field(default_factory=FieldEvidence)


class ExtractedLanguage(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    level: Literal["basic", "intermediate", "advanced", "native"] = "intermediate"
    evidence: FieldEvidence = Field(default_factory=FieldEvidence)


class ExtractedCertification(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    issuer: str = Field(default="", max_length=200)
    issued: str = Field(default="", max_length=10)
    credential_id: str = Field(default="", max_length=120)
    evidence: FieldEvidence = Field(default_factory=FieldEvidence)


class ExtractedAward(BaseModel):
    kind: Literal["award", "honor", "publication", "extracurricular"] = "award"
    title: str = Field(min_length=1, max_length=200)
    issuer: str = Field(default="", max_length=200)
    date: str = Field(default="", max_length=10)
    evidence: FieldEvidence = Field(default_factory=FieldEvidence)


class ExtractedInterest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    evidence: FieldEvidence = Field(default_factory=FieldEvidence)


class CvExtract(BaseModel):
    """The full structured CV extraction (one AI pass over the text)."""

    basics: ExtractedBasics = Field(default_factory=ExtractedBasics)
    summary: str = Field(default="", max_length=2000)
    education: list[ExtractedEducation] = Field(default_factory=list, max_length=10)
    experience: list[ExtractedExperience] = Field(default_factory=list, max_length=15)
    skills: list[ExtractedSkill] = Field(default_factory=list, max_length=30)
    languages: list[ExtractedLanguage] = Field(default_factory=list, max_length=10)
    certifications: list[ExtractedCertification] = Field(
        default_factory=list, max_length=10
    )
    awards: list[ExtractedAward] = Field(default_factory=list, max_length=10)
    interests: list[ExtractedInterest] = Field(default_factory=list, max_length=10)
