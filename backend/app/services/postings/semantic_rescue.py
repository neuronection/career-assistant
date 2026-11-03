"""The semantic catalog rescue on the family vector store (plan 50 §7.2, P2a).

Plan 185's two-signal join, re-homed on ``vector_spaces`` /
``vector_documents`` / ``vector_records``: the deterministic weighted skill
overlap stays the gate and the primary decision, and where it misses this
module offers a **bounded semantic rescue**. A candidate enters the rescue
pool only if it passes the same shared-skill gate the deterministic path
implies (≥1 resolved skill linked to both the posting and the job), so a
vector hit can never resurrect a job the deterministic evidence excluded —
semantic is a ranking signal, never a gate (ADR-0012 §4, ADR-0051 §7).

Freshness — the one ingest-time exception plan 50 §5.5 sanctions: a posting
that is not indexed yet is written through the same
:class:`~app.services.vector_index_service.VectorIndexService` the
``VECTOR_INDEX`` job uses (budget-checked gateway embed, content-hash dedupe)
*before* the match, so an ingest decision never silently degrades into a
no-op. An unchanged posting costs zero provider calls, and the match itself
uses the stored document vectors — no provider round trip.

Failure is always fail-safe: no provider, a gateway/budget error, a missing
space, a dimension mismatch or an over-cap scan return a degraded signal and
the caller keeps the overlap-only verdict. Writing a posting never fails
because its embedding did.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_model import Job, JobSkill
from app.storage.vector_backends import VectorBackendError
from app.storage.vector_contract import BACKEND_LINEAR, DegradedReason

logger = logging.getLogger(__name__)

#: The pinned plan-185 rescue constants (test-pinned, not live-tuned).
SEMANTIC_MAP_THRESHOLD = 0.6
SEMANTIC_MIN_SHARED_SKILLS = 1
SEMANTIC_CANDIDATE_K = 5
#: Candidates fetched before the deterministic gates truncate them to K.
SEMANTIC_SCAN_WINDOW = 25


@dataclass(frozen=True)
class SemanticCandidate:
    """One gated rescue candidate: the job plus its explainable score."""

    job_id: str
    code: str
    score: float
    shared_skills: int
    per_view: Mapping[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "code": self.code,
            "score": round(self.score, 4),
            "shared_skills": self.shared_skills,
            "per_view": {view: round(value, 4) for view, value in sorted(self.per_view.items())},
        }


@dataclass(frozen=True)
class SemanticSignal:
    """The semantic half of the join — what the audit trace records."""

    candidates: tuple[SemanticCandidate, ...] = ()
    threshold: float | None = None
    space_key: str | None = None
    degraded: str | None = None

    @property
    def top(self) -> float | None:
        """The best *gated* candidate's score (``None`` when none passed)."""
        return self.candidates[0].score if self.candidates else None

    @property
    def top_candidate(self) -> SemanticCandidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def cleared(self) -> bool:
        """True when the top candidate clears the rescue threshold."""
        top = self.top
        return top is not None and top >= (self.threshold or SEMANTIC_MAP_THRESHOLD)

    def as_dict(self) -> dict[str, Any]:
        return {
            "top": round(self.top, 4) if self.top is not None else None,
            "threshold": self.threshold,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "space_key": self.space_key,
            "degraded": self.degraded,
        }


def not_run_signal() -> SemanticSignal:
    """The trace shape when the rescue never ran (overlap decided, no skills)."""
    return SemanticSignal()


async def _ensure_posting_indexed(
    db: AsyncSession,
    posting,
    *,
    indexer: Any = None,
) -> str | None:
    """Index the posting through the sanctioned writer; a reason or ``None``.

    Returns the structured degradation reason when the document could not be
    written (no space yet, no provider, broken index, over cap), ``None`` on
    success. An unchanged posting is a zero-embed no-op.

    The space must already exist: provisioning is the migration/CLI/job's
    job and never runs inside an ingest request (plan 50 §3.4). A fresh
    deployment reports ``index_missing`` until the first index/reconcile run
    creates the space — explicit in the trace, never a silent no-op, and
    never request-time DDL.
    """
    if indexer is None:
        from app.services.vector_index_service import VectorIndexService

        indexer = VectorIndexService(db)
    try:
        space = indexer.store.active_space(indexer.space_name)
    except VectorBackendError:
        return DegradedReason.INDEX_MISSING.value
    if space.index_table is None:
        if indexer.store.backend.name != BACKEND_LINEAR:
            return DegradedReason.INDEX_MISSING.value
    elif not indexer.store.backend.health(space).ok:
        return DegradedReason.INDEX_MISSING.value
    outcome = await indexer.index_document(kind="posting", source_id=str(posting.id))
    return outcome.degraded


async def _gated_candidates(
    db: AsyncSession,
    hits,
    skill_ids: set[uuid.UUID],
    *,
    limit: int,
) -> list[SemanticCandidate]:
    """Hydrate semantic hits against ``jobs`` and apply the shared-skill gate.

    One bounded query over the candidate ids: published status and the count
    of resolved skills linked to both sides. A draft job or a job with zero
    shared skills is dropped *before* the threshold decision — the gate is
    the same deterministic evidence the overlap path uses.
    """
    job_ids: list[uuid.UUID] = []
    for hit in hits:
        try:
            job_ids.append(uuid.UUID(str(hit.source_id)))
        except (TypeError, ValueError):
            continue
    if not job_ids:
        return []
    rows = (
        await db.execute(
            select(Job.id, Job.code, Job.status, func.count(JobSkill.id))
            .select_from(Job)
            .outerjoin(
                JobSkill,
                and_(JobSkill.job_id == Job.id, JobSkill.skill_id.in_(skill_ids)),
            )
            .where(Job.id.in_(job_ids))
            .group_by(Job.id, Job.code, Job.status)
        )
    ).all()
    shared = {row[0]: int(row[3] or 0) for row in rows}
    published = {row[0]: (str(row[1]), str(row[2])) for row in rows}
    candidates: list[SemanticCandidate] = []
    for hit in hits:
        try:
            job_id = uuid.UUID(str(hit.source_id))
        except (TypeError, ValueError):
            continue
        code, status = published.get(job_id, ("", ""))
        shared_skills = shared.get(job_id, 0)
        if status != "published" or shared_skills < SEMANTIC_MIN_SHARED_SKILLS:
            continue
        candidates.append(
            SemanticCandidate(
                job_id=str(job_id),
                code=code,
                score=float(hit.score),
                shared_skills=shared_skills,
                per_view=dict(hit.per_view),
            )
        )
        if len(candidates) >= limit:
            break
    return candidates


async def semantic_catalog_signal(
    db: AsyncSession,
    posting,
    skill_ids: set[uuid.UUID],
    *,
    indexer: Any = None,
    retriever: Any = None,
    window: int = SEMANTIC_SCAN_WINDOW,
) -> SemanticSignal:
    """Rank published catalog jobs against one posting, gated by shared skills.

    No skills resolved ⇒ no signal at all (the gate cannot be passed). Every
    failure is caught and reported as ``degraded``: the caller decides with
    the overlap alone.
    """
    if not skill_ids:
        return not_run_signal()

    from app.services.vector_retrieval_service import (
        JOB_MATCH_VIEW_PAIRS,
        VectorRetrievalService,
    )

    try:
        if posting.id is None:  # pragma: no cover - every caller flushed first
            await db.flush()
        degraded = await _ensure_posting_indexed(db, posting, indexer=indexer)
    except Exception:
        logger.info(
            "semantic rescue could not index posting %s — overlap-only decision",
            getattr(posting, "id", None),
            exc_info=True,
        )
        return SemanticSignal(
            threshold=SEMANTIC_MAP_THRESHOLD, degraded=DegradedReason.EMBED_FAILED.value
        )
    if degraded is not None:
        return SemanticSignal(threshold=SEMANTIC_MAP_THRESHOLD, degraded=str(degraded))

    if retriever is None:
        retriever = VectorRetrievalService(db, user_id=None)
    try:
        result = await retriever.match_documents(
            source_kind="posting",
            source_id=str(posting.id),
            target_kind="job",
            view_weights=JOB_MATCH_VIEW_PAIRS,
            limit=max(int(window), SEMANTIC_CANDIDATE_K),
        )
    except Exception:
        logger.info(
            "semantic rescue match failed for posting %s — overlap-only decision",
            getattr(posting, "id", None),
            exc_info=True,
        )
        return SemanticSignal(
            threshold=SEMANTIC_MAP_THRESHOLD, degraded=DegradedReason.EMBED_FAILED.value
        )
    space_key = result.space_key or None
    if result.degraded is not None:
        return SemanticSignal(
            threshold=SEMANTIC_MAP_THRESHOLD,
            space_key=space_key,
            degraded=str(result.degraded),
        )
    try:
        candidates = await _gated_candidates(db, result.hits, skill_ids, limit=SEMANTIC_CANDIDATE_K)
    except Exception:  # pragma: no cover - a broken job table is not a posting failure
        logger.info(
            "semantic rescue gate query failed for posting %s",
            getattr(posting, "id", None),
            exc_info=True,
        )
        return SemanticSignal(
            threshold=SEMANTIC_MAP_THRESHOLD,
            space_key=space_key,
            degraded=DegradedReason.EMBED_FAILED.value,
        )
    return SemanticSignal(
        candidates=tuple(candidates),
        threshold=SEMANTIC_MAP_THRESHOLD,
        space_key=space_key,
    )


__all__ = [
    "SEMANTIC_CANDIDATE_K",
    "SEMANTIC_MAP_THRESHOLD",
    "SEMANTIC_MIN_SHARED_SKILLS",
    "SEMANTIC_SCAN_WINDOW",
    "SemanticCandidate",
    "SemanticSignal",
    "not_run_signal",
    "semantic_catalog_signal",
]
