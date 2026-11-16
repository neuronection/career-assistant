"""Catalog-first job-type candidate assembly (plan 202 AD2).

Deterministic sources only: exact normalized title, token containment,
skill overlap (published only) and the non-deferred semantic trace. The
proposer sees this bounded list and must map to one of its codes or create
a type; an exact match never calls a provider.

The title labels load once per page through :func:`load_title_catalog`; the
skill-overlap stage (:func:`catalog_candidates`) still runs per posting,
bounded by the shared-skill index since S1a. A page-level published
``JobSkill`` preload is a follow-up if a profile shows it material — this
slice does not claim that residual closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_titles import normalize_job_type_title
from app.models.job_model import Job, JobFamily
from app.models.posting_model import JobPosting, PostingSkill
from app.services.postings.job_type_text import contains_title_tokens
from app.services.postings.mapping_candidates import catalog_candidates
from app.services.postings.mapping_score import posting_skill_weights

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


@dataclass(frozen=True)
class TitleCatalogEntry:
    """The label fields a proposal needs — no ORM row, no lazy family."""

    code: str
    title: str
    family_key: str
    family_label: str
    short_description: str


@dataclass(frozen=True)
class TitleCatalog:
    """One page-level catalog snapshot for candidate + duplicate assembly."""

    published: tuple[TitleCatalogEntry, ...]
    non_retired: tuple[TitleCatalogEntry, ...]


async def _catalog_rows(db: AsyncSession, condition) -> tuple[TitleCatalogEntry, ...]:
    rows = await db.execute(
        select(
            Job.code,
            Job.title,
            JobFamily.key,
            JobFamily.label,
            Job.short_description,
        )
        .join(JobFamily, JobFamily.id == Job.family_id)
        .where(condition)
        .order_by(Job.title, Job.code)
    )
    return tuple(
        TitleCatalogEntry(
            code=str(code),
            title=str(title),
            family_key=str(family_key or ""),
            family_label=str(family_label or ""),
            short_description=str(short_description or ""),
        )
        for code, title, family_key, family_label, short_description in rows.all()
    )


async def load_title_catalog(db: AsyncSession) -> TitleCatalog:
    """Load the published and non-retired title catalogs in two queries."""
    published = await _catalog_rows(db, Job.status == "published")
    non_retired = await _catalog_rows(db, Job.status != "retired")
    return TitleCatalog(published=published, non_retired=non_retired)


def _candidate(entry: TitleCatalogEntry, *, score: float, source: str) -> JobTypeCandidate:
    return JobTypeCandidate(
        code=entry.code,
        title=entry.title,
        family_key=entry.family_key,
        family_label=entry.family_label,
        short_description=entry.short_description,
        score=score,
        source=source,
    )


async def job_type_candidates(
    db: AsyncSession,
    posting: JobPosting,
    extract: dict,
    *,
    limit: int = JOB_TYPE_CANDIDATE_CAP,
    catalog: TitleCatalog | None = None,
) -> tuple[list[JobTypeCandidate], JobTypeCandidate | None]:
    """Build the bounded candidate set; returns ``(candidates, exact_match)``.

    Order: exact > containment > skill > semantic; deduped by code, capped.
    A page-level caller can pass ``catalog`` so the two label queries run once
    for the whole queue instead of once per posting.
    """
    catalog = catalog or await load_title_catalog(db)
    jobs = catalog.published
    by_code = {entry.code: entry for entry in jobs}
    postings_title = f"{posting.title} {extract.get('title_norm') or ''}"
    normalized_norm = normalize_job_type_title(str(extract.get("title_norm") or ""))
    normalized_raw = normalize_job_type_title(str(posting.title or ""))

    found: dict[str, JobTypeCandidate] = {}
    exact: JobTypeCandidate | None = None
    if normalized_norm or normalized_raw:
        for entry in jobs:
            normalized_job = normalize_job_type_title(entry.title)
            if normalized_job and normalized_job in {normalized_norm, normalized_raw}:
                exact = _candidate(entry, score=1.0, source="exact")
                found[exact.code] = exact
                break

    for entry in jobs:
        if entry.code in found:
            continue
        if contains_title_tokens(entry.title, postings_title):
            found[entry.code] = _candidate(entry, score=0.7, source="containment")

    posting_weights = posting_skill_weights(
        (
            await db.execute(
                select(
                    PostingSkill.skill_id,
                    PostingSkill.priority,
                    PostingSkill.required_level,
                ).where(PostingSkill.posting_id == posting.id)
            )
        ).all()
    )
    if posting_weights:
        for candidate in await catalog_candidates(
            db,
            posting_weights,
            k=limit,
            published_only=True,
            posting_title=posting.title,
        ):
            code = str(candidate.job.code)
            if code in found:
                continue
            entry = by_code.get(code) or TitleCatalogEntry(
                code=code,
                title=str(candidate.job.title),
                family_key="",
                family_label="",
                short_description=str(candidate.job.short_description or ""),
            )
            found[code] = _candidate(entry, score=candidate.skill, source="skill")

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
    "TitleCatalog",
    "TitleCatalogEntry",
    "job_type_candidates",
    "load_title_catalog",
]
