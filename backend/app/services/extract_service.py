"""Deep posting extraction (Phase 31): the queued LLM pass over
`job_postings`.

Two-speed pipeline — plan 26's fast alias/keyword pass stays the sync
path; this module owns the deep pass: one audited structured LLM call
per posting (AITaskType.POSTING_EXTRACT) through the plan-12 queue,
demand-driven priority (postings matching any alert rule extract
first), `extract_version` staleness for prompt bumps, and normalization
into `posting_skills.required_level`/`priority` + typed columns.
Confidence below the threshold means a field is suppressed and the
posting flagged `needs_review` — never guessed silently."""

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.enums import (
    BackgroundJobStatus,
    PostingEvidence,
)
from app.models.enums import BackgroundJobType
from app.models.posting_model import JobPosting, PostingSkill
from app.models.taxonomy_model import Skill

logger = logging.getLogger(__name__)

EXTRACT_VERSION = 1
CONFIDENCE_THRESHOLD = 0.6

FIELD_NAMES = (
    "title_norm",
    "seniority",
    "employment_type",
    "remote_policy",
    "location",
    "salary",
    "education",
    "languages",
    "benefits",
    "responsibilities",
    "skills",
)


# ------------------------------------------------------------------ queue


async def has_pending_extract(db: AsyncSession, posting_id: UUID) -> bool:
    rows = await db.execute(
        select(BackgroundJob.id).where(
            BackgroundJob.job_type == BackgroundJobType.POSTING_EXTRACT.value,
            BackgroundJob.status.in_(
                [
                    BackgroundJobStatus.QUEUED.value,
                    BackgroundJobStatus.RUNNING.value,
                ]
            ),
            BackgroundJob.payload["posting_id"].as_string() == str(posting_id),
        )
    )
    return rows.scalars().first() is not None


async def queue_posting_extract(
    db: AsyncSession, posting: JobPosting, *, demand: bool = False
) -> bool:
    """Enqueue one extraction job unless one is already queued/running."""
    from app.services.job_worker import enqueue

    if await has_pending_extract(db, posting.id):
        return False
    await enqueue(
        db,
        BackgroundJobType.POSTING_EXTRACT.value,
        {"posting_id": str(posting.id), "demand": demand},
        max_attempts=2,
    )
    return True


async def plan_extractions(
    db: AsyncSession, fresh: list[tuple[JobPosting, bool]], backlog: bool = False
) -> int:
    """Queue extractions demand-first (claim order = insertion order, and
    the queue claims oldest-first — that IS the priority mechanism).

    With `backlog`, postings never extracted (extract_version NULL —
    includes version-bump staleness) drip in after the fresh ones.
    """
    queued = 0
    if backlog:
        rows = await db.execute(
            select(JobPosting).where(
                JobPosting.extract_version.is_(None),
                JobPosting.status.in_(["new", "mapped"]),
            )
        )
        for posting in rows.scalars().all():
            fresh.append((posting, False))
    for posting, demand in fresh:
        try:
            if await queue_posting_extract(db, posting, demand=demand):
                queued += 1
        except Exception:  # noqa: BLE001 — one bad posting can't block sync
            logger.warning("Extract enqueue failed", exc_info=True)
    return queued


# ------------------------------------------------------------------- apply


def _sane_salary(
    low: Optional[float], high: Optional[float]
) -> tuple[Optional[float], Optional[float]]:
    if low is not None and high is not None and low > high:
        return None, None
    return low, high


async def apply_extract(db: AsyncSession, posting: JobPosting, extract) -> JobPosting:
    """Store a validated PostingExtract: suppress low-confidence fields
    (needs_review), normalize typed columns, fill posting_skills levels.
    """
    from app.ai.agents.posting_extractor import PostingExtract

    if not isinstance(extract, PostingExtract):
        extract = PostingExtract.model_validate(extract)

    conf = extract.field_confidence or {}
    suppressed = [
        f for f in FIELD_NAMES if float(conf.get(f, 1.0)) < CONFIDENCE_THRESHOLD
    ]
    data = extract.model_dump(mode="json")
    for field in suppressed:
        data[field] = None

    kept_skills = [
        s
        for s in (data.get("skills") or [])
        if float(s.get("confidence", 1.0)) >= CONFIDENCE_THRESHOLD
    ]
    needs_review = bool(suppressed) or len(kept_skills) != len(data.get("skills") or [])
    data["skills"] = kept_skills
    data["_suppressed_fields"] = suppressed
    posting.extract = data
    posting.extract_version = EXTRACT_VERSION
    posting.needs_review = needs_review

    if data.get("seniority"):
        posting.seniority = data["seniority"]
    if data.get("employment_type"):
        posting.employment_type = data["employment_type"]
    if data.get("remote_policy"):
        posting.onsite_policy = data["remote_policy"]
    if data.get("education") and data["education"].get("level"):
        posting.education_level = data["education"]["level"]
    salary = data.get("salary") or {}
    if salary.get("currency"):
        posting.salary_currency = salary["currency"][:3]
    if salary.get("period"):
        posting.salary_period = salary["period"]
    low, high = _sane_salary(salary.get("min"), salary.get("max"))
    if salary.get("min") is not None and low is None:
        needs_review = True  # insane range suppressed
    posting.salary_min = low if low is not None else posting.salary_min
    posting.salary_max = high if high is not None else posting.salary_max
    location = data.get("location") or {}
    if location.get("city") or location.get("country"):
        posting.location = {
            **(posting.location or {}),
            **{k: v for k, v in location.items() if v},
        }

    facts = {**(posting.posting_facts or {})}
    for key in ("languages", "benefits", "responsibilities"):
        if data.get(key):
            facts[key] = data[key]
    posting.posting_facts = facts

    await _apply_extract_skills(db, posting, data["skills"])
    await db.flush()
    return posting


async def _apply_extract_skills(
    db: AsyncSession, posting: JobPosting, skills: list[dict]
) -> None:
    """Fill `posting_skills.required_level`/`priority` for resolved skills
    (update fast-pass rows in place — never delete them); unresolved raw
    labels become plan-15 proposals (never dropped, never label-matched).
    """
    from app.services.postings_service import _norm

    unresolved_labels: list[dict] = []
    key_map: dict[str, UUID] = {}
    for entry in skills:
        if entry.get("unresolved") or not entry.get("skill_key"):
            unresolved_labels.append(entry)
            continue
        key_map[_norm(entry["skill_key"])] = entry

    resolved_ids: dict[UUID, dict] = {}
    if key_map:
        rows = await db.execute(
            select(Skill).where(
                Skill.status == "active",
                Skill.key.in_(list(key_map.keys())),
            )
        )
        for skill in rows.scalars().all():
            entry = key_map.get(_norm(skill.key))
            if entry is not None:
                resolved_ids[skill.id] = entry

    existing: dict[UUID, PostingSkill] = {}
    if resolved_ids:
        rows = await db.execute(
            select(PostingSkill).where(
                PostingSkill.posting_id == posting.id,
                PostingSkill.skill_id.in_(resolved_ids.keys()),
            )
        )
        existing = {row.skill_id: row for row in rows.scalars().all()}

    for skill_id, entry in resolved_ids.items():
        row = existing.get(skill_id)
        if row is None:
            row = PostingSkill(
                posting_id=posting.id,
                skill_id=skill_id,
                evidence=PostingEvidence.EXPLICIT.value,
            )
            db.add(row)
        row.required_level = int(entry["required_level"])
        row.priority = entry["priority"]
        row.confidence = float(entry.get("confidence", 1.0))

    if unresolved_labels:
        from app.models.enums import SkillOrigin
        from app.services.skills_service import SkillService

        service = SkillService(db)
        for entry in unresolved_labels:
            label = str(entry.get("raw_label") or "").strip()
            if not label:
                continue
            key = _norm(label).replace(" ", "-")[:80]
            if not key:
                continue
            _, created = await service.propose(
                key,
                label=label[:120],
                origin=SkillOrigin.AI,
                provenance={
                    "posting_id": str(posting.id),
                    "evidence_quote": entry.get("evidence_quote", "")[:400],
                    "extract_version": EXTRACT_VERSION,
                    "required_level": entry.get("required_level"),
                    "priority": entry.get("priority"),
                },
            )
            if created:
                await db.flush()


# -------------------------------------------------------------------- run


async def run_extract_job(db: AsyncSession, payload: dict) -> dict:
    """POSTING_EXTRACT handler body: one structured call + apply."""
    posting_id = payload.get("posting_id")
    if not posting_id:
        raise ValidationError("posting_extract requires posting_id")
    rows = await db.execute(
        select(JobPosting).where(JobPosting.id == UUID(str(posting_id)))
    )
    posting = rows.scalars().first()
    if posting is None:
        return {"skipped": "posting gone"}
    if posting.extract_version == EXTRACT_VERSION:
        return {"skipped": "already extracted"}
    return await extract_posting_now(db, posting)


async def extract_posting_now(db: AsyncSession, posting: JobPosting) -> dict:
    """The AI call + apply (also used by the admin re-extract action)."""
    from app.ai.agents.posting_extractor import extract_posting
    from app.services.postings_service import _active_skill_keys

    description = str((posting.raw or {}).get("description") or "")
    skills_raw = [str(s) for s in (posting.raw or {}).get("_skills_raw", [])]
    taxonomy = await _active_skill_keys(db)
    result = await extract_posting(
        db,
        None,
        posting.title,
        description,
        skills_raw,
        taxonomy,
    )
    await apply_extract(db, posting, result)
    await db.commit()
    return {
        "extracted": True,
        "skills": len(result.skills),
        "needs_review": posting.needs_review,
    }
