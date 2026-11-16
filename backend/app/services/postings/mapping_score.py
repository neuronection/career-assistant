"""Pure scoring core for the posting↔job-type join (plan 210 AD1).

Every helper here is a deterministic function over loaded rows: no database,
no provider and no request state. The candidate loader and the calibration
harness call the same functions so a formula change cannot drift between the
production decision and the offline sweep.
"""

from __future__ import annotations

import uuid
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from app.core.job_titles import normalize_job_type_title
from app.services.postings.fit.dimensions import IMPORTANCE_WEIGHT, PRIORITY_WEIGHT
from app.services.postings.job_type_text import contains_title_tokens, trigram_similarity

#: The deterministic score model version recorded in the feature payload.
SCORE_MODEL = "two_way_coverage_v3"

#: Title evidence is additive and only orders already-gated candidates.
TITLE_LAMBDA = 0.10

#: A semantic mapping below this confidence is weak-review material (S2).
WEAK_SEMANTIC_CONFIDENCE = 0.65

#: Title signals: exact normalized, token containment, and the trigram floor.
TITLE_EXACT = 1.0
TITLE_CONTAINMENT = 0.8
TITLE_TRIGRAM_FLOOR = 0.6
TITLE_TRIGRAM_CAP = 0.6


class JobSkillLike(Protocol):
    """The ``JobSkill`` attributes the weight helper reads."""

    @property
    def skill_id(self) -> uuid.UUID: ...

    @property
    def importance(self) -> str | None: ...

    @property
    def required_level(self) -> int | None: ...


class PostingSkillLike(Protocol):
    """The ``PostingSkill`` attributes the weight helper reads."""

    @property
    def skill_id(self) -> uuid.UUID: ...

    @property
    def priority(self) -> str | None: ...

    @property
    def required_level(self) -> int | None: ...


def job_skill_weight(importance: str | None, level: int | None) -> float:
    """The job-side weight: importance x required-level factor."""
    base = IMPORTANCE_WEIGHT.get(str(importance or "core"), 1.0)
    return base * (min(int(level or 0), 10) / 10.0)


def job_skill_weights(links: Iterable[JobSkillLike]) -> dict[uuid.UUID, float]:
    """Build ``{skill_id: weight}`` from ``JobSkill``-shaped rows."""
    weights: dict[uuid.UUID, float] = {}
    for link in links:
        weight = job_skill_weight(link.importance, link.required_level)
        weights[link.skill_id] = weights.get(link.skill_id, 0.0) + weight
    return weights


def posting_skill_weight(priority: str | None, level: int | None) -> float:
    """The posting-side weight; unknown priority/level is neutral (1.0)."""
    base = PRIORITY_WEIGHT.get(str(priority or ""), 1.0)
    factor = min(int(level), 10) / 10.0 if level is not None else 1.0
    return base * factor


def posting_skill_weights(rows: Iterable[PostingSkillLike]) -> dict[uuid.UUID, float]:
    """Build ``{skill_id: weight}`` from ``PostingSkill``-shaped rows."""
    weights: dict[uuid.UUID, float] = {}
    for row in rows:
        weights[row.skill_id] = posting_skill_weight(row.priority, row.required_level)
    return weights


def score_breakdown[ScoreKey: Hashable](
    job_weights: Mapping[ScoreKey, float],
    posting_weights: Mapping[ScoreKey, float],
) -> SkillScore:
    """Two-way coverage: independent per-side normalization, harmonic mean.

    ``precision`` is the posting coverage (share of the posting's weights
    matched), ``recall`` the type coverage (share of the type's weights
    matched) and ``skill`` their harmonic mean. Each side is normalized
    independently, so a perfect two-way match is 1.0 at any absolute scale.
    """
    total_job = sum(job_weights.values())
    total_posting = sum(posting_weights.values())
    if total_job <= 0 or total_posting <= 0:
        return SkillScore(precision=0.0, recall=0.0, skill=0.0)
    shared = set(job_weights) & set(posting_weights)
    if not shared:
        return SkillScore(precision=0.0, recall=0.0, skill=0.0)
    precision = sum(posting_weights[key] for key in shared) / total_posting
    recall = sum(job_weights[key] for key in shared) / total_job
    if precision + recall <= 0:
        return SkillScore(precision=0.0, recall=0.0, skill=0.0)
    skill = 2.0 * precision * recall / (precision + recall)
    return SkillScore(precision=precision, recall=recall, skill=skill)


def title_signal(job_title: str | None, posting_title: str | None) -> float:
    """Deterministic title evidence between a type and a posting title.

    Exact normalized titles score 1.0; a type title whose tokens are fully
    contained in the posting title (at least two tokens) scores 0.8; a
    trigram similarity at or above the 0.6 floor scores at most 0.6. The
    0.72 near-duplicate bar is a catalog-dedupe threshold, not a mapping
    signal.
    """
    normalized_job = normalize_job_type_title(str(job_title or ""))
    normalized_posting = normalize_job_type_title(str(posting_title or ""))
    if not normalized_job or not normalized_posting:
        return 0.0
    if normalized_job == normalized_posting:
        return TITLE_EXACT
    if contains_title_tokens(str(job_title or ""), str(posting_title or "")):
        return TITLE_CONTAINMENT
    similarity = trigram_similarity(normalized_job, normalized_posting)
    if similarity >= TITLE_TRIGRAM_FLOOR:
        return min(similarity, TITLE_TRIGRAM_CAP)
    return 0.0


def candidate_order(skill: float, title: float, title_lambda: float = TITLE_LAMBDA) -> float:
    """The deterministic winner rail: ``clamp(skill + λ·title, 0, 1)``."""
    return min(max(skill + title_lambda * title, 0.0), 1.0)


@dataclass(frozen=True)
class SkillScore:
    """Two-way coverage and the resulting skill score."""

    precision: float
    recall: float
    skill: float


__all__ = [
    "SCORE_MODEL",
    "TITLE_LAMBDA",
    "WEAK_SEMANTIC_CONFIDENCE",
    "SkillScore",
    "candidate_order",
    "job_skill_weight",
    "job_skill_weights",
    "posting_skill_weight",
    "posting_skill_weights",
    "score_breakdown",
    "title_signal",
]
