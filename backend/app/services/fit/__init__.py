"""Deterministic fit engine (Phase 22) — pure dimensions + storage service."""

from app.services.fit.dimensions import (
    DEFAULT_WEIGHTS,
    DIMENSIONS,
    FIT_VERSION,
    FitResult,
    compute_fit,
    evidence_years_from_experience,
    evaluate_gates,
)
from app.services.fit.service import FitService

__all__ = [
    "DEFAULT_WEIGHTS",
    "DIMENSIONS",
    "FIT_VERSION",
    "FitResult",
    "FitService",
    "compute_fit",
    "evidence_years_from_experience",
    "evaluate_gates",
]
