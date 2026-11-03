"""Deterministic catalog candidate generation for the mapping join (plan 164 S1.6).

The catalog decision keeps the existing weighted skill-overlap scorer as the
gate and the only decision score (plan 50 §7.2). This module exposes the
stage-2 candidate set the deterministic scorer already computes so the
bounded semantic rerank can reorder *only* those candidates — semantic can
never introduce a job the skill graph did not propose.

The score is unchanged: ``hit / total`` over ``job_skills`` weights
(importance x required level), no IDF and no lexical/freshness term. Ordering
is deterministic: ``(-score, job.code)`` so equal scores never depend on row
order. The candidate list is bounded by the caller (``K = 25``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_model import Job, JobSkill
from app.models.taxonomy_model import Skill
from app.services.postings.fit.dimensions import IMPORTANCE_WEIGHT

DEFAULT_CANDIDATE_K = 25


@dataclass(frozen=True)
class CatalogCandidate:
    """One deterministic stage-2 candidate and the evidence behind it."""

    job: Job
    score: float
    shared_skill_ids: tuple[uuid.UUID, ...] = ()

    @property
    def job_id(self) -> str:
        return str(self.job.id)

    @property
    def code(self) -> str:
        return str(self.job.code)

    @property
    def shared_skills(self) -> int:
        return len(self.shared_skill_ids)


async def score_catalog_candidates(
    db: AsyncSession,
    posting_skill_ids: set[uuid.UUID],
    *,
    published_only: bool = False,
) -> list[CatalogCandidate]:
    """Score every catalog job against the posting's resolved skill ids.

    One indexed read over ``job_skills`` (the inverted index), pure-Python
    aggregation, deterministic ordering. ``published_only`` is used by the
    rerank path so a draft job can never become a semantic target; the
    deterministic decision itself keeps its existing behaviour.
    """
    if not posting_skill_ids:
        return []
    statement = select(Job, JobSkill).join(JobSkill, JobSkill.job_id == Job.id)
    if published_only:
        statement = statement.where(Job.status == "published")
    rows = await db.execute(statement)
    scored: dict[uuid.UUID, dict] = {}
    for job, link in rows:
        weight = IMPORTANCE_WEIGHT.get(link.importance, 1.0) * (min(link.required_level, 10) / 10.0)
        entry = scored.setdefault(
            job.id,
            {"job": job, "hit": 0.0, "total": 0.0, "shared": set()},
        )
        entry["total"] += weight
        if link.skill_id in posting_skill_ids:
            entry["hit"] += weight
            entry["shared"].add(link.skill_id)
    candidates = [
        CatalogCandidate(
            job=entry["job"],
            score=entry["hit"] / entry["total"],
            shared_skill_ids=tuple(sorted(entry["shared"], key=str)),
        )
        for entry in scored.values()
        if entry["total"] > 0
    ]
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.code))
    return candidates


async def catalog_candidates(
    db: AsyncSession,
    posting_skill_ids: set[uuid.UUID],
    *,
    k: int = DEFAULT_CANDIDATE_K,
    published_only: bool = False,
) -> list[CatalogCandidate]:
    """The bounded stage-2 candidate set (top ``k`` by the deterministic score)."""
    if k <= 0:
        return []
    return (await score_catalog_candidates(db, posting_skill_ids, published_only=published_only))[
        :k
    ]


async def shared_skill_keys(db: AsyncSession, skill_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Resolve shared skill ids to their stable taxonomy keys (audit payload)."""
    if not skill_ids:
        return {}
    rows = await db.execute(select(Skill.id, Skill.key).where(Skill.id.in_(skill_ids)))
    return {row[0]: str(row[1]) for row in rows}


__all__ = [
    "DEFAULT_CANDIDATE_K",
    "CatalogCandidate",
    "catalog_candidates",
    "score_catalog_candidates",
    "shared_skill_keys",
]
