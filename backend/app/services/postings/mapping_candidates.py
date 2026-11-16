"""Deterministic catalog candidate generation for the mapping join (plan 164 S1.6).

The catalog decision keeps the existing weighted skill-overlap scorer as the
gate and the only decision score (plan 50 §7.2). This module exposes the
stage-2 candidate set the deterministic scorer already computes so the
bounded semantic rerank can reorder *only* those candidates — semantic can
never introduce a job the skill graph did not propose.

The score is two-way coverage (plan 210 AD2): each side's weights are
normalized independently and combined with the harmonic mean; a title term
orders already-gated candidates without admitting an ungated one. Ordering is
deterministic: ``(-score, -skill, job.code)`` so equal scores never depend on
row order. The candidate list is bounded by the caller (``K = 25``).

The candidate set is loaded through the inverted index (shared skills → job
ids → all links of those jobs), so a posting with no shared skill yields an
empty list instead of a zero-score tail.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_model import Job, JobSkill
from app.models.taxonomy_model import Skill
from app.services.postings.mapping_score import (
    TITLE_LAMBDA,
    candidate_order,
    job_skill_weights,
    score_breakdown,
    title_signal,
)

DEFAULT_CANDIDATE_K = 25


@dataclass(frozen=True)
class CatalogCandidate:
    """One deterministic stage-2 candidate and the evidence behind it.

    ``skill`` is the gated two-way coverage, ``title`` the deterministic
    title signal and ``score`` the winner rail (``skill + λ·title``).
    """

    job: Job
    skill: float
    title: float
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
    posting_skill_weights: Mapping[uuid.UUID, float],
    *,
    posting_title: str | None = None,
    published_only: bool = False,
    title_lambda: float = TITLE_LAMBDA,
) -> list[CatalogCandidate]:
    """Score every catalog job that shares a resolved skill with the posting.

    Two indexed reads (shared job ids, then those jobs' links) over
    ``job_skills``, pure-Python aggregation, deterministic ordering.
    ``published_only`` is used by the rerank path so a draft job can never
    become a semantic target; the deterministic decision itself keeps its
    existing behaviour.
    """
    if not posting_skill_weights:
        return []
    job_ids = list(
        (
            await db.execute(
                select(JobSkill.job_id)
                .where(JobSkill.skill_id.in_(posting_skill_weights.keys()))
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    if not job_ids:
        return []
    statement = (
        select(Job, JobSkill).join(JobSkill, JobSkill.job_id == Job.id).where(Job.id.in_(job_ids))
    )
    if published_only:
        statement = statement.where(Job.status == "published")
    else:
        statement = statement.where(Job.status != "retired")
    rows = await db.execute(statement)
    links: dict[uuid.UUID, list[JobSkill]] = {}
    jobs: dict[uuid.UUID, Job] = {}
    for job, link in rows:
        jobs[job.id] = job
        links.setdefault(job.id, []).append(link)
    candidates: list[CatalogCandidate] = []
    for job_id, job_links in links.items():
        job_weights = job_skill_weights(job_links)
        breakdown = score_breakdown(job_weights, posting_skill_weights)
        if breakdown.skill <= 0:
            continue
        title = title_signal(jobs[job_id].title, posting_title)
        candidates.append(
            CatalogCandidate(
                job=jobs[job_id],
                skill=breakdown.skill,
                title=title,
                score=candidate_order(breakdown.skill, title, title_lambda),
                shared_skill_ids=tuple(
                    sorted(set(job_weights) & set(posting_skill_weights), key=str)
                ),
            )
        )
    candidates.sort(key=lambda candidate: (-candidate.score, -candidate.skill, candidate.code))
    return candidates


async def catalog_candidates(
    db: AsyncSession,
    posting_skill_weights: Mapping[uuid.UUID, float],
    *,
    k: int = DEFAULT_CANDIDATE_K,
    published_only: bool = False,
    posting_title: str | None = None,
    title_lambda: float = TITLE_LAMBDA,
) -> list[CatalogCandidate]:
    """The bounded stage-2 candidate set (top ``k`` by the order rail)."""
    if k <= 0:
        return []
    return (
        await score_catalog_candidates(
            db,
            posting_skill_weights,
            posting_title=posting_title,
            published_only=published_only,
            title_lambda=title_lambda,
        )
    )[:k]


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
