from datetime import datetime
from typing import Optional
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
    specialist_dimension: Optional[str] = None


class MatchInsightOut(BaseModel):
    id: UUID
    job_id: UUID
    ai_score: Optional[float] = None
    ai_confidence: Optional[float] = None
    ai_summary: str
    ai_positives: list[ScoredAspect]
    ai_negatives: list[ScoredAspect]
    prerequisites: list[PrerequisiteCheck]
    ai_model: str
    ai_generated_at: Optional[datetime] = None
    fit_score: Optional[float] = None
    fit_breakdown: Optional[FitBreakdownOut] = None
    fit_version: int = 0
    user_score: Optional[int] = None
    status: Optional[MatchStatus] = None
    user_notes: str
    seen_at: Optional[datetime] = None
    saved_at: Optional[datetime] = None
    hidden_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ScoreIn(BaseModel):
    job_id: Optional[UUID] = None
    family_key: Optional[str] = None
    all_candidates: bool = False
    limit: int = Field(default=10, ge=1, le=50)
    force: bool = False


class FitRefitIn(BaseModel):
    """Deterministic refit (plan 22): one job sync, `all` via the queue."""

    job_id: Optional[UUID] = None
    all: bool = False


class ScoringWeightsIn(BaseModel):
    skills: int = Field(ge=1, le=5)
    location: int = Field(ge=1, le=5)
    experience: int = Field(ge=1, le=5)
    education: int = Field(ge=1, le=5)
    interests: int = Field(ge=1, le=5)


class RateIn(BaseModel):
    job_id: UUID
    user_score: Optional[int] = Field(default=None, ge=0, le=10)
    status: Optional[MatchStatus] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


class RankedJob(BaseModel):
    job: JobOut
    score: float
    fit_score: float
    ai_score: Optional[float] = None
    user_score: Optional[int] = None
    status: Optional[MatchStatus] = None
    breakdown: Optional[FitBreakdownOut] = None
    specialist_dimension: Optional[str] = None
    gated: bool = False
    gate_reasons: list[str] = Field(default_factory=list)
    insight: Optional[MatchInsightOut] = None


class RankingsOut(BaseModel):
    items: list[RankedJob]
    total: int


class CandidateOut(BaseModel):
    job: JobOut
    fit_score: float
    breakdown: Optional[FitBreakdownOut] = None
