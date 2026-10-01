from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import MatchStatus, PrerequisiteStatus
from app.schemas.job import JobOut


class PrerequisiteCheck(BaseModel):
    requirement: str = Field(min_length=1, max_length=300)
    status: PrerequisiteStatus
    detail: str = Field(default="", max_length=500)


class ScoredAspect(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=800)
    weight: float = Field(default=0.5, ge=0, le=1)


class FitDimension(BaseModel):
    score: float
    weight: int
    detail: str = ""


class FitBreakdownOut(BaseModel):
    dimensions: dict[str, FitDimension] = Field(default_factory=dict)
    gates: list[str] = Field(default_factory=list)
    specialist_dimension: str | None = None


class MatchInsightOut(BaseModel):
    id: UUID
    job_id: UUID
    ai_score: float | None = None
    ai_confidence: float | None = None
    ai_summary: str
    ai_positives: list[ScoredAspect]
    ai_negatives: list[ScoredAspect]
    prerequisites: list[PrerequisiteCheck]
    ai_model: str
    ai_generated_at: datetime | None = None
    fit_score: float | None = None
    fit_breakdown: FitBreakdownOut | None = None
    fit_version: int = 0
    user_score: int | None = None
    status: MatchStatus | None = None
    user_notes: str
    seen_at: datetime | None = None
    saved_at: datetime | None = None
    hidden_at: datetime | None = None

    model_config = {"from_attributes": True}


class ScoreIn(BaseModel):
    job_id: UUID | None = None
    family_key: str | None = None
    all_candidates: bool = False
    limit: int = Field(default=10, ge=1, le=50)
    force: bool = False


class FitRefitIn(BaseModel):
    """Deterministic refit: one job sync, `all` via the queue."""

    job_id: UUID | None = None
    all: bool = False


class ScoringWeightsIn(BaseModel):
    skills: int = Field(ge=1, le=5)
    location: int = Field(ge=1, le=5)
    experience: int = Field(ge=1, le=5)
    education: int = Field(ge=1, le=5)
    interests: int = Field(ge=1, le=5)


class RateIn(BaseModel):
    job_id: UUID
    user_score: int | None = Field(default=None, ge=0, le=10)
    status: MatchStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)


class RankedJob(BaseModel):
    job: JobOut
    score: float
    fit_score: float
    ai_score: float | None = None
    user_score: int | None = None
    status: MatchStatus | None = None
    breakdown: FitBreakdownOut | None = None
    specialist_dimension: str | None = None
    gated: bool = False
    gate_reasons: list[str] = Field(default_factory=list)
    insight: MatchInsightOut | None = None


class RankingsOut(BaseModel):
    items: list[RankedJob]
    total: int


class CandidateOut(BaseModel):
    job: JobOut
    fit_score: float
    breakdown: FitBreakdownOut | None = None
