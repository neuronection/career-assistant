"""Read surfaces over the job↔posting match (plan 50 §7.3, P2a).

Two read-only questions the job detail asks, answered by the family vector
store's bounded document match and always degradable to the deterministic
skill evidence the app already had:

* **similar catalog jobs** — the job's own stored views against other
  ``job`` documents (excluding itself), then a published-only hydration;
* **live postings for this job** — the job's views against ``posting``
  documents under the feed's visibility rules (``mapped``/``new``, never a
  posting the user hid), then the candidates' product rows.

The semantic ranking only orders; the eligibility filters are applied when
the ranked ids are hydrated (jobs: ``status='published'``; postings: the
live-feed visibility predicate). Those filters can only *remove* rows, and
a row that fails one is never returned — the same invariant the vector
scope enforces, applied to the product columns the store does not carry.

The stored document vectors are the query, so the normal path makes no
provider call. When the job itself is not indexed yet, its composed text is
embedded once as the query (the plan 50 §7.3 fallback for a document missing
from the store) and the same view pairs are searched. A missing index, an
unassigned provider, a dimension mismatch or an over-cap store returns the
skill/catalog listing with ``degraded`` set — never a 500.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_model import Job, JobSkill
from app.models.posting_model import JobPosting, PostingInteraction
from app.services.catalog.job_service import JOB_LOAD_OPTIONS
from app.services.postings.fit.dimensions import IMPORTANCE_WEIGHT
from app.services.vector_composers import compose_job_views
from app.services.vector_retrieval_service import (
    JOB_MATCH_VIEW_PAIRS,
    RetrievalResult,
    VectorRetrievalService,
)
from app.storage.vector_contract import DegradedReason

#: Over-fetch factor for the eligibility filters applied at hydration.
VISIBILITY_WINDOW_FACTOR = 3
LIVE_POSTING_STATUSES = ("mapped", "new")


def _link_weight(link: JobSkill) -> float:
    return IMPORTANCE_WEIGHT.get(link.importance, 1.0) * (min(link.required_level, 10) / 10.0)


class JobMatchService:
    """Similar jobs and live postings for one catalog job."""

    def __init__(
        self, db: AsyncSession, *, retriever: VectorRetrievalService | None = None
    ) -> None:
        self.db = db
        self._retriever = retriever

    def _service(self) -> VectorRetrievalService:
        if self._retriever is None:
            self._retriever = VectorRetrievalService(self.db)
        return self._retriever

    async def similar_jobs(self, job: Job, *, limit: int = 10, offset: int = 0) -> dict[str, Any]:
        """Published catalog jobs nearest ``job`` by long-text views.

        Stored document vectors first; the composed job text when the index
        has not reached the job yet. Per-view cosines ride each item.
        """
        window = max((int(limit) + int(offset)) * VISIBILITY_WINDOW_FACTOR, int(limit))
        result = await self._ranked(job, "job", window)
        if result.hits:
            ranked = await self._published_jobs([hit.source_id for hit in result.hits])
            items = []
            for hit in result.hits:
                candidate = ranked.get(hit.source_id)
                if candidate is None:
                    continue
                items.append(
                    {
                        "code": candidate.code,
                        "title": candidate.title,
                        "family_key": candidate.family.key if candidate.family else None,
                        "family_label": candidate.family.label if candidate.family else None,
                        "score": hit.score,
                        "per_view": dict(hit.per_view),
                        "source": "semantic",
                    }
                )
            if items:
                return {
                    "items": items[offset : offset + limit],
                    "source": "semantic",
                    "degraded": None,
                    "space_key": result.space_key or None,
                }
        return {
            "items": await self._overlap_jobs(job, limit=limit, offset=offset),
            "source": "skill_overlap",
            "degraded": str(result.degraded) if result.degraded is not None else None,
            "space_key": result.space_key or None,
        }

    async def live_postings(
        self,
        job: Job,
        *,
        user_id: uuid.UUID,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        """The live postings (``mapped``/``new``) nearest ``job`` by view.

        Visibility is applied when the ranked ids are hydrated, so a hidden
        or closed posting can never come back. Degrades to the postings the
        catalog already mapped to this job.
        """
        window = max((int(limit) + int(offset)) * VISIBILITY_WINDOW_FACTOR, int(limit))
        result = await self._ranked(job, "posting", window)
        if result.hits:
            ranked = await self._visible_postings(user_id, [hit.source_id for hit in result.hits])
            items = []
            for hit in result.hits:
                posting = ranked.get(hit.source_id)
                if posting is None:
                    continue
                items.append(
                    {
                        "id": posting.id,
                        "ref": posting.ref,
                        "title": posting.title,
                        "org": posting.org,
                        "posted_at": posting.posted_at,
                        "status": posting.status,
                        "catalog_job_id": posting.catalog_job_id,
                        "score": hit.score,
                        "per_view": dict(hit.per_view),
                        "source": "semantic",
                    }
                )
            if items:
                return {
                    "items": items[offset : offset + limit],
                    "source": "semantic",
                    "degraded": None,
                }
        return {
            "items": await self._catalog_postings(job, user_id, limit=limit, offset=offset),
            "source": "catalog",
            "degraded": str(result.degraded) if result.degraded is not None else None,
        }

    # ----------------------------------------------------------- internals

    async def _ranked(self, job: Job, target_kind: str, window: int) -> RetrievalResult:
        """Stored document vectors first; the composed job text when absent.

        A job the index has not reached yet still answers: the composed job
        text is embedded once as the QUERY (the plan 50 §7.3 allowance for a
        document missing from the store) and searched view by view. That is
        the only provider call in these reads, and it disappears once the
        job is indexed. A missing space/provider still degrades before any
        embed.
        """
        result = await self._service().match_documents(
            source_kind="job",
            source_id=str(job.id),
            target_kind=target_kind,
            view_weights=JOB_MATCH_VIEW_PAIRS,
            limit=window,
            exclude_self=True,
        )
        if result.degraded is not DegradedReason.INDEX_MISSING:
            return result
        text = _composed_text(job)
        if not text:
            return result
        textual = await self._service().match_text(
            text,
            target_kind=target_kind,
            view_weights=JOB_MATCH_VIEW_PAIRS,
            limit=window,
        )
        return textual if textual.hits else result

    async def _published_jobs(self, source_ids: list[str]) -> dict[str, Job]:
        ids: list[uuid.UUID] = []
        for value in source_ids:
            try:
                ids.append(uuid.UUID(str(value)))
            except (TypeError, ValueError):
                continue
        if not ids:
            return {}
        rows = (
            (
                await self.db.execute(
                    select(Job)
                    .options(*JOB_LOAD_OPTIONS)
                    .where(Job.id.in_(ids), Job.status == "published")
                )
            )
            .scalars()
            .unique()
            .all()
        )
        return {str(row.id): row for row in rows}

    async def _visible_postings(
        self, user_id: uuid.UUID, source_ids: list[str]
    ) -> dict[str, JobPosting]:
        ids: list[uuid.UUID] = []
        for value in source_ids:
            try:
                ids.append(uuid.UUID(str(value)))
            except (TypeError, ValueError):
                continue
        if not ids:
            return {}
        rows = (
            (
                await self.db.execute(
                    select(JobPosting)
                    .outerjoin(
                        PostingInteraction,
                        (PostingInteraction.posting_id == JobPosting.id)
                        & (PostingInteraction.user_id == user_id),
                    )
                    .where(
                        JobPosting.id.in_(ids),
                        JobPosting.status.in_(LIVE_POSTING_STATUSES),
                        or_(
                            PostingInteraction.id.is_(None),
                            PostingInteraction.hidden_at.is_(None),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {str(row.id): row for row in rows}

    async def _overlap_jobs(self, job: Job, *, limit: int, offset: int) -> list[dict[str, Any]]:
        """The lexical fallback: published jobs sharing this job's skills.

        The candidate score is the share of THIS job's weighted requirements
        a peer covers — the same importance x level weighting the catalog
        decision uses. Deterministic tie-break on the code.
        """
        own_skills = {link.skill_id: _link_weight(link) for link in job.skill_links}
        total = sum(own_skills.values())
        if not own_skills or total <= 0:
            return []
        rows = (
            await self.db.execute(
                select(Job, JobSkill)
                .options(*JOB_LOAD_OPTIONS)
                .join(JobSkill, JobSkill.job_id == Job.id)
                .where(
                    Job.status == "published",
                    Job.id != job.id,
                    JobSkill.skill_id.in_(list(own_skills)),
                )
            )
        ).all()
        hits: dict[uuid.UUID, float] = {}
        for candidate, link in rows:
            hits[candidate.id] = hits.get(candidate.id, 0.0) + min(
                _link_weight(link), own_skills[link.skill_id]
            )
        jobs = await self._published_jobs([str(job_id) for job_id in hits])
        items: list[dict[str, Any]] = [
            {
                "code": candidate.code,
                "title": candidate.title,
                "family_key": candidate.family.key if candidate.family else None,
                "family_label": candidate.family.label if candidate.family else None,
                "score": round(min(hits[candidate.id] / total, 1.0), 4),
                "per_view": {},
                "source": "skill_overlap",
            }
            for candidate in jobs.values()
        ]
        items.sort(key=lambda item: (-float(item["score"]), str(item["code"])))
        return items[offset : offset + limit]

    async def _catalog_postings(
        self, job: Job, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        """The lexical fallback: postings the catalog already mapped here."""
        rows = (
            (
                await self.db.execute(
                    select(JobPosting)
                    .outerjoin(
                        PostingInteraction,
                        (PostingInteraction.posting_id == JobPosting.id)
                        & (PostingInteraction.user_id == user_id),
                    )
                    .where(
                        JobPosting.catalog_job_id == job.id,
                        JobPosting.status.in_(LIVE_POSTING_STATUSES),
                        or_(
                            PostingInteraction.id.is_(None),
                            PostingInteraction.hidden_at.is_(None),
                        ),
                    )
                    .order_by(JobPosting.posted_at.desc(), JobPosting.id)
                    .offset(int(offset))
                    .limit(int(limit))
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": posting.id,
                "ref": posting.ref,
                "title": posting.title,
                "org": posting.org,
                "posted_at": posting.posted_at,
                "status": posting.status,
                "catalog_job_id": posting.catalog_job_id,
                "score": 1.0,
                "per_view": {},
                "source": "catalog",
            }
            for posting in rows
        ]


def _composed_text(job: Job) -> str:
    """The job's embeddable text, for the query-embedding fallback."""
    composed = compose_job_views(job)
    return "\n".join(value for value in composed.views.values() if value)


def match_view_weights() -> Mapping[tuple[str, str], float]:
    """The pinned job↔posting view pairs (exposed for diagnostics/tests)."""
    return JOB_MATCH_VIEW_PAIRS


__all__ = [
    "LIVE_POSTING_STATUSES",
    "VISIBILITY_WINDOW_FACTOR",
    "JobMatchService",
    "match_view_weights",
]
