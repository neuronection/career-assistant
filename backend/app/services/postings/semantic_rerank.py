"""Bounded semantic rerank of the deterministic catalog candidates (plan 164 S4.4).

Plan 50 §7.2 keeps plan 164's deterministic skill-graph score as the **gate
and the only decision score**. Semantic enters exactly where 164 S4.4 puts
it: an ambiguous deterministic outcome (best below ``τ_job`` or a runner-up
margin under ``δ``) is reranked over the *stage-2 candidates only*, with the
pinned blend ``0.75·deterministic + 0.25·semantic``. A rerank is accepted
only when its top candidate still clears ``τ_job`` and the margin ``δ``.

This is deliberately different from the plan-185 rescue in
:mod:`app.services.postings.semantic_rescue`: the rescue may *introduce* a
candidate (gated by a shared resolved skill) where the overlap missed, while
this rerank may only *reorder* the deterministic candidate set. Semantic can
never resurrect a job the skill graph excluded.

The match itself spends no provider call: the posting is indexed through the
same sanctioned ingest writer the rescue uses (an unchanged posting costs
zero embeds) and the match reads the stored document vectors. Any failure —
no space, no provider, an embedding error, a dimension mismatch, an over-cap
scan — degrades to the deterministic-only outcome with a structured reason.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.postings.mapping_candidates import CatalogCandidate
from app.storage.vector_contract import MAXSIM_CANDIDATE_CAP, DegradedReason

logger = logging.getLogger(__name__)

#: The pinned plan-164 S4.4 blend and ambiguity constants (test-pinned).
RERANK_CANDIDATE_K = 25
RERANK_MARGIN = 0.08
RERANK_BLEND_DETERMINISTIC = 0.75
RERANK_BLEND_SEMANTIC = 0.25
#: How many matched job documents the bounded MaxSim reads before the
#: candidate set filters them. Bounded by the contract's candidate cap.
RERANK_SEMANTIC_LIMIT = MAXSIM_CANDIDATE_CAP


@dataclass(frozen=True)
class RerankCandidate:
    """One deterministic candidate with its semantic and blended scores."""

    job_id: str
    code: str
    deterministic: float
    semantic: float
    blend: float
    shared_skill_ids: tuple[uuid.UUID, ...] = ()
    per_view: Mapping[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_code": self.code,
            "deterministic": round(self.deterministic, 4),
            "semantic": round(self.semantic, 4),
            "blend": round(self.blend, 4),
            "shared_skills": len(self.shared_skill_ids),
            "per_view": {view: round(value, 4) for view, value in sorted(self.per_view.items())},
        }


@dataclass(frozen=True)
class RerankSignal:
    """The rerank half of the trace — what ``mapping_features`` records."""

    candidates: tuple[RerankCandidate, ...] = ()
    threshold: float | None = None
    margin: float = RERANK_MARGIN
    blend_deterministic: float = RERANK_BLEND_DETERMINISTIC
    blend_semantic: float = RERANK_BLEND_SEMANTIC
    space_key: str | None = None
    degraded: str | None = None
    ran: bool = False
    accepted: bool = False
    top_changed: bool = False

    @property
    def top_candidate(self) -> RerankCandidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def top(self) -> float | None:
        top = self.top_candidate
        return top.blend if top is not None else None

    @property
    def runner_up(self) -> float | None:
        return self.candidates[1].blend if len(self.candidates) > 1 else None

    @property
    def margin_value(self) -> float | None:
        top = self.top
        if top is None:
            return None
        return round(top - (self.runner_up or 0.0), 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "threshold": self.threshold,
            "margin": self.margin,
            "blend": {
                "deterministic": self.blend_deterministic,
                "semantic": self.blend_semantic,
            },
            "top": round(self.top, 4) if self.top is not None else None,
            "top_code": self.top_candidate.code if self.top_candidate is not None else None,
            "top_changed": self.top_changed,
            "accepted": self.accepted,
            "space_key": self.space_key,
            "degraded": self.degraded,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
        }


def not_run_rerank(*, threshold: float | None = None) -> RerankSignal:
    """The trace shape when the rerank never ran (unambiguous or no skills)."""
    return RerankSignal(threshold=threshold)


def _blend(deterministic: float, semantic: float) -> float:
    return round(
        RERANK_BLEND_DETERMINISTIC * deterministic + RERANK_BLEND_SEMANTIC * semantic,
        4,
    )


def _acceptance(
    candidates: Sequence[RerankCandidate],
    *,
    threshold: float,
    margin: float,
    deterministic_cleared: bool,
    deterministic_top: str | None,
) -> tuple[bool, bool]:
    """Return ``(accepted, top_changed)`` for the pinned policy."""
    if not candidates:
        return False, False
    top = candidates[0]
    top_changed = deterministic_top is None or top.job_id != deterministic_top
    runner_up = candidates[1].blend if len(candidates) > 1 else 0.0
    clears_threshold = top.blend >= threshold
    clears_margin = (top.blend - runner_up) >= margin
    # Below τ the rerank may *raise* the deterministic winner (that is the
    # point); at/above τ it may only change the top-1 (plan 164 S4.4).
    allowed = (not deterministic_cleared) or top_changed
    return bool(clears_threshold and clears_margin and allowed), top_changed


async def semantic_rerank_signal(
    db: AsyncSession,
    posting,
    deterministic_candidates: Sequence[CatalogCandidate],
    *,
    threshold: float,
    margin: float = RERANK_MARGIN,
    indexer: Any = None,
    retriever: Any = None,
) -> RerankSignal:
    """Rerank the deterministic candidate set with the job↔posting match.

    No skills or no candidates ⇒ the stage does not run. The posting is
    indexed through the sanctioned writer (unchanged content is a zero-embed
    no-op) and every failure returns a degraded signal; the caller keeps the
    deterministic verdict.
    """
    deterministic_candidates = [
        candidate
        for candidate in deterministic_candidates
        if getattr(candidate.job, "status", None) == "published"
    ]
    if not deterministic_candidates:
        return not_run_rerank(threshold=threshold)

    from app.services.postings.semantic_rescue import _ensure_posting_indexed

    try:
        if posting.id is None:  # pragma: no cover - every caller flushed first
            await db.flush()
        degraded = await _ensure_posting_indexed(db, posting, indexer=indexer)
    except Exception:
        logger.info(
            "semantic rerank could not index posting %s — deterministic-only decision",
            getattr(posting, "id", None),
            exc_info=True,
        )
        return RerankSignal(
            threshold=threshold,
            margin=margin,
            degraded=DegradedReason.EMBED_FAILED.value,
            ran=True,
        )
    if degraded is not None:
        return RerankSignal(
            threshold=threshold,
            margin=margin,
            degraded=str(degraded),
            ran=True,
        )

    from app.services.vector_retrieval_service import (
        JOB_MATCH_VIEW_PAIRS,
        VectorRetrievalService,
    )

    if retriever is None:
        retriever = VectorRetrievalService(db, user_id=None)
    try:
        result = await retriever.match_documents(
            source_kind="posting",
            source_id=str(posting.id),
            target_kind="job",
            view_weights=JOB_MATCH_VIEW_PAIRS,
            limit=RERANK_SEMANTIC_LIMIT,
        )
    except Exception:
        logger.info(
            "semantic rerank match failed for posting %s — deterministic-only decision",
            getattr(posting, "id", None),
            exc_info=True,
        )
        return RerankSignal(
            threshold=threshold,
            margin=margin,
            degraded=DegradedReason.EMBED_FAILED.value,
            ran=True,
        )
    space_key = result.space_key or None
    if result.degraded is not None:
        return RerankSignal(
            threshold=threshold,
            margin=margin,
            space_key=space_key,
            degraded=str(result.degraded),
            ran=True,
        )

    hits = {str(hit.source_id): hit for hit in result.hits}
    reranked: list[RerankCandidate] = []
    for candidate in deterministic_candidates:
        hit = hits.get(candidate.job_id)
        semantic = float(hit.score) if hit is not None else 0.0
        reranked.append(
            RerankCandidate(
                job_id=candidate.job_id,
                code=candidate.code,
                deterministic=round(candidate.score, 4),
                semantic=round(semantic, 4),
                blend=_blend(candidate.score, semantic),
                shared_skill_ids=candidate.shared_skill_ids,
                per_view=dict(hit.per_view) if hit is not None else {},
            )
        )
    reranked.sort(key=lambda item: (-item.blend, -item.deterministic, item.code))
    deterministic_top = deterministic_candidates[0].job_id
    deterministic_cleared = deterministic_candidates[0].score >= threshold
    accepted, top_changed = _acceptance(
        reranked,
        threshold=threshold,
        margin=margin,
        deterministic_cleared=deterministic_cleared,
        deterministic_top=deterministic_top,
    )
    return RerankSignal(
        candidates=tuple(reranked),
        threshold=threshold,
        margin=margin,
        space_key=space_key,
        ran=True,
        accepted=accepted,
        top_changed=top_changed,
    )


__all__ = [
    "RERANK_BLEND_DETERMINISTIC",
    "RERANK_BLEND_SEMANTIC",
    "RERANK_CANDIDATE_K",
    "RERANK_MARGIN",
    "RERANK_SEMANTIC_LIMIT",
    "RerankCandidate",
    "RerankSignal",
    "not_run_rerank",
    "semantic_rerank_signal",
]
