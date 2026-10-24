"""The SPA-shell bootstrap payload (plans 25/27/118; typed by plan 123.4)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import CareerStage, OnboardingPath
from app.schemas.ai_status import AiStatusOut
from app.schemas.profile import ScoringWeights


class BootstrapOut(BaseModel):
    """Stage, feature flags, weights and locale state for one caller.

    ``refit_*`` ride only the PUT /me/stage response (the in-flight
    refit window); the GET omits them."""

    career_stage: CareerStage
    stage_source: Literal["derived", "explicit"]
    onboarding_path: OnboardingPath | None = None
    features: dict[str, bool]
    suggested_scoring_weights: ScoringWeights
    effective_scoring_weights: ScoringWeights
    weights_overridden: bool
    fit_stale: bool = False
    refit_queued: bool | None = None
    refit_job_id: str | None = None
    refitted: int | None = None
    target_mode: bool = False
    target_families: list[str] = Field(default_factory=list)
    notification_channels: list[str] = Field(default_factory=list)
    ai: AiStatusOut | None = None
    locale: str | None = None
    locale_source: str | None = None
    instance_locale: str | None = None
    supported_locales: list[str] = Field(default_factory=list)
