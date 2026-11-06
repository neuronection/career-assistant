"""Catalog-first job-type candidate assembly (plan 202 AD2).

Deterministic sources only: exact normalized title, token containment,
skill overlap (published only) and the non-deferred semantic trace. The
proposer sees this bounded list and must map to one of its codes or create
a type; an exact match never calls a provider.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.job_model import Job, JobFamily
from app.models.posting_model import JobPosting, PostingSkill
from app.services.postings.job_type_text import (
    contains_title_tokens,
    normalize_job_type_title,
)
from app.services.postings.mapping_candidates import catalog_candidates

#: The bounded proposer candidate set (the prompt cap).
JOB_TYPE_CANDIDATE_CAP = 12

_SOURCE_RANK = {"exact": 0, "containment": 1, "skill": 2, "semantic": 3}


@dataclass(frozen=True)
class JobTypeCandidate:
    """One catalog job type the proposer may map the posting onto."""

    code: str
    title: str
    family_key: str
    family_label: str
    short_description: str
    score: float
    source: str


async def _published_jobs(db: AsyncSession) -> list[Job]:
    rows = await db.execute(
        select(Job)
        .options(selectinload(Job.family))
        .join(JobFamily, JobFamily.id == Job.family_id)
        .where(Job.status == "published")
        .order_by(Job.title, Job.code)
    )
    return list(rows.scalars().all())


def _family_key(job: Job) -> str:
    return job.family.key if job.family else ""


def _family_label(job: Job) -> str:
    return job.family.label if job.family else ""


def _candidate(job: Job, *, score: float, source: str) -> JobTypeCandidate:
    return JobTypeCandidate(
        code=str(job.code),
        title=str(job.title),
        family_key=_family_key(job),
        family_label=_family_label(job),
        short_description=str(job.short_description or ""),
        score=score,
        source=source,
    )


async def job_type_candidates(
    db: AsyncSession,
    posting: JobPosting,
    extract: dict,
    *,
    limit: int = JOB_TYPE_CANDIDATE_CAP,
) -> tuple[list[JobTypeCandidate], JobTypeCandidate | None]:
    """Build the bounded candidate set; returns ``(candidates, exact_match)``.

    Order: exact > containment > skill > semantic; deduped by code, capped.
    """
    jobs = await _published_jobs(db)
    by_code = {str(job.code): job for job in jobs}
    postings_title = f"{posting.title} {extract.get('title_norm') or ''}"
    normalized_norm = normalize_job_type_title(str(extract.get("title_norm") or ""))
    normalized_raw = normalize_job_type_title(str(posting.title or ""))

    found: dict[str, JobTypeCandidate] = {}
    exact: JobTypeCandidate | None = None
    if normalized_norm or normalized_raw:
        for job in jobs:
            normalized_job = normalize_job_type_title(job.title)
            if normalized_job and normalized_job in {normalized_norm, normalized_raw}:
                exact = _candidate(job, score=1.0, source="exact")
                found[exact.code] = exact
                break

    for job in jobs:
        if job.code in found:
            continue
        if contains_title_tokens(job.title, postings_title):
            found[job.code] = _candidate(job, score=0.7, source="containment")

    skill_ids = set(
        (
            await db.execute(
                select(PostingSkill.skill_id).where(PostingSkill.posting_id == posting.id)
            )
        )
        .scalars()
        .all()
    )
    if skill_ids:
        for candidate in await catalog_candidates(db, skill_ids, k=limit, published_only=True):
            code = str(candidate.job.code)
            if code in found:
                continue
            found[code] = _candidate(candidate.job, score=candidate.score, source="skill")

    signals = (posting.posting_facts or {}).get("mapping_signals") or {}
    semantic = (signals.get("semantic") or {}).get("candidates") or []
    for entry in semantic:
        code = str((entry or {}).get("code") or "")
        semantic_job = by_code.get(code)
        if semantic_job is None or code in found:
            continue
        found[code] = _candidate(
            semantic_job,
            score=float((entry or {}).get("score") or 0.0),
            source="semantic",
        )

    ordered = sorted(
        found.values(),
        key=lambda candidate: (
            _SOURCE_RANK.get(candidate.source, 9),
            -candidate.score,
            candidate.code,
        ),
    )[:limit]
    return ordered, exact


__all__ = [
    "JOB_TYPE_CANDIDATE_CAP",
    "JobTypeCandidate",
    "job_type_candidates",
]
