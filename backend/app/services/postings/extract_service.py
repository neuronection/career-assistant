"""Deep posting extraction (Phase 31): the queued LLM pass over
`job_postings`.

Two-speed pipeline —'s fast alias/keyword pass stays the sync
path; this module owns the deep pass: one audited structured LLM call
per posting (AITaskType.POSTING_EXTRACT) through the queue,
demand-driven priority (postings matching any alert rule extract
first), `extract_version` staleness for prompt bumps, and normalization
into `posting_skills.required_level`/`priority` + typed columns.
Confidence below the threshold means a field is suppressed and the
posting flagged `needs_review` — never guessed silently."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.enums import (
    BackgroundJobStatus,
    BackgroundJobType,
    PostingEvidence,
)
from app.models.posting_model import JobPosting, PostingSkill
from app.models.taxonomy_model import Skill
from app.services.postings.salary import BASIS_VALUES, annualized

logger = logging.getLogger(__name__)

EXTRACT_VERSION = 4
CONFIDENCE_THRESHOLD = 0.6

# A proposed extraction label seen again from a different posting is
# corroborated; this many distinct postings auto-promote it (plan 147 —
# the orgs decision-8 corroboration pattern applied to skills).
CORROBORATION_MIN_POSTINGS = 2
CORROBORATION_CAP = 20

FIELD_NAMES = (
    "title_norm",
    "seniority",
    "employment_type",
    "remote_policy",
    "location",
    "salary",
    "education",
    "languages",
    "prerequisites",
    "benefits",
    "responsibilities",
    "skills",
    "contract_type",
    "work_hours",
    "schedule_cues",
    "travel_required",
    "onsite_policy",
)

# v2 fields stored as structured `posting_facts["lifestyle"]` — inert
# until the feature map (39.3) binds them, read by the fit gates today.
LIFESTYLE_FACT_KEYS = (
    "contract_type",
    "work_hours",
    "schedule_cues",
    "travel_required",
    "onsite_policy",
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

    With `backlog`, postings NEVER extracted (extract_version NULL) drip
    in after the fresh ones. Rows on an older version are NOT auto-queued
    — re-extraction is a demand/admin decision (an AI-cost lever), and
    demand paths re-extract them via the `!= EXTRACT_VERSION` check.
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
        except Exception:
            logger.warning("Extract enqueue failed", exc_info=True)
    return queued


# ------------------------------------------------------------------- apply


def _sane_salary(low: float | None, high: float | None) -> tuple[float | None, float | None]:
    if low is not None and high is not None and low > high:
        return None, None
    return low, high


async def apply_extract(
    db: AsyncSession,
    posting: JobPosting,
    extract,
    *,
    actor_ref: dict | None = None,
    duration_ms: int | None = None,
) -> JobPosting:
    """Store a validated PostingExtract: suppress low-confidence fields
    (needs_review), normalize typed columns, fill posting_skills levels.
    Journals as `extract_llm` (same transaction; `description_clean` is a
    field of the envelope, folded here — no separate writer)."""
    from app.ai.agents.posting_extractor import PostingExtract
    from app.services.postings.change_journal import (
        EXTRACT_FIELDS,
        PostingChangeJournal,
        extract_snapshot_fields,
        facts_summary,
        snapshot,
    )

    def _snap() -> dict:
        return {
            **snapshot(posting, EXTRACT_FIELDS),
            **extract_snapshot_fields(posting),
            "facts_summary": facts_summary(posting),
        }

    before = _snap()
    if not isinstance(extract, PostingExtract):
        extract = PostingExtract.model_validate(extract)

    conf = extract.field_confidence or {}
    suppressed = [f for f in FIELD_NAMES if float(conf.get(f, 1.0)) < CONFIDENCE_THRESHOLD]
    data = extract.model_dump(mode="json")
    for field in suppressed:
        data[field] = None

    kept_skills = [
        s
        for s in (data.get("skills") or [])
        if float(s.get("confidence", 1.0)) >= CONFIDENCE_THRESHOLD
    ]
    kept_prerequisites = [
        r
        for r in (data.get("prerequisites") or [])
        if float(r.get("confidence", 1.0)) >= CONFIDENCE_THRESHOLD
    ]
    needs_review = (
        bool(suppressed)
        or len(kept_skills) != len(data.get("skills") or [])
        or len(kept_prerequisites) != len(data.get("prerequisites") or [])
    )
    data["skills"] = kept_skills
    data["prerequisites"] = kept_prerequisites
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
    if salary.get("basis") in BASIS_VALUES:
        posting.salary_basis = salary["basis"]
    low, high = _sane_salary(salary.get("min"), salary.get("max"))
    if salary.get("min") is not None and low is None:
        needs_review = True  # insane range suppressed
    posting.salary_min = low if low is not None else posting.salary_min
    posting.salary_max = high if high is not None else posting.salary_max
    norm_low, norm_high = annualized(posting.salary_min, posting.salary_max, posting.salary_period)
    posting.salary_normalized_min = norm_low
    posting.salary_normalized_max = norm_high
    location = data.get("location") or {}
    if location.get("city") or location.get("country"):
        posting.location = {
            **(posting.location or {}),
            **{k: v for k, v in location.items() if v},
        }

    facts = {**(posting.posting_facts or {})}
    for key in ("languages", "benefits", "responsibilities", "values_cues"):
        if data.get(key):
            facts[key] = data[key]
    lifestyle = {key: data[key] for key in LIFESTYLE_FACT_KEYS if data.get(key)}
    if lifestyle:
        facts["lifestyle"] = lifestyle
    posting.posting_facts = facts

    await _apply_extract_skills(db, posting, data["skills"], actor_ref=actor_ref)
    await db.flush()
    outcome = "partial" if posting.needs_review else "ok"
    PostingChangeJournal.record(
        db,
        posting.id,
        "extract_llm",
        actor_ref=actor_ref,
        operation={
            "extract_version": EXTRACT_VERSION,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
        },
        duration_ms=duration_ms,
        before=before,
        after=_snap(),
        outcome=outcome,
    )
    return posting


async def _apply_extract_skills(
    db: AsyncSession, posting: JobPosting, skills: list[dict], *, actor_ref: dict | None = None
) -> None:
    """Fill `posting_skills.required_level`/`priority` for resolved skills
    (update fast-pass rows in place — never delete them); unresolved raw
    labels become proposals (never dropped, never label-matched). Active
    rows resolve first and deprecated exact keys fall back for unmatched
    keys — the matcher precedence `_taxonomy_index` shares. Journals the
    skills set-diff as `extract_llm` (same transaction).
    """
    from app.services.postings.change_journal import PostingChangeJournal, skills_state
    from app.services.postings.postings_service import _norm

    before = await skills_state(db, posting.id)
    unresolved_labels: list[dict] = []
    key_map: dict[str, dict] = {}
    for entry in skills:
        if entry.get("unresolved") or not entry.get("skill_key"):
            unresolved_labels.append(entry)
            continue
        key_map[_norm(entry["skill_key"])] = entry

    resolved_ids: dict[UUID, dict] = {}
    if key_map:
        rows = await db.execute(
            select(Skill).where(
                Skill.key.in_(list(key_map.keys())),
            )
        )
        deprecated: dict[UUID, dict] = {}
        for skill in rows.scalars().all():
            matched_entry = key_map.get(_norm(skill.key))
            if matched_entry is None:
                continue
            if skill.status == "active":
                resolved_ids[skill.id] = matched_entry
            elif skill.status == "deprecated":
                deprecated[skill.id] = matched_entry
        for skill_id, entry in deprecated.items():
            resolved_ids.setdefault(skill_id, entry)

    existing: dict[UUID, PostingSkill] = {}
    if resolved_ids:
        existing_rows = await db.execute(
            select(PostingSkill).where(
                PostingSkill.posting_id == posting.id,
                PostingSkill.skill_id.in_(resolved_ids.keys()),
            )
        )
        existing = {row.skill_id: row for row in existing_rows.scalars().all()}

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

    PostingChangeJournal.record(
        db,
        posting.id,
        "extract_llm",
        actor_ref=actor_ref,
        operation={"extract_version": EXTRACT_VERSION},
        before={"skills": before},
        after={"skills": await skills_state(db, posting.id)},
    )

    if unresolved_labels:
        from app.models.enums import SkillOrigin
        from app.services.catalog.skills_service import SkillService

        service = SkillService(db)
        corroborated: list[tuple[Skill, int]] = []
        for entry in unresolved_labels:
            label = str(entry.get("raw_label") or "").strip()
            if not label:
                continue
            key = _norm(label).replace(" ", "-")[:80]
            if not key:
                continue
            skill, created = await service.propose(
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
                continue
            count = _record_corroboration(skill, posting)
            if count:
                await db.flush()
            if count >= CORROBORATION_MIN_POSTINGS:
                corroborated.append((skill, count))
        for skill, postings_count in corroborated:
            await _auto_promote(db, skill, postings_count)


def _record_corroboration(skill: Skill, posting: JobPosting) -> int:
    """Count the distinct postings behind a proposed extraction label
    (origin posting + `corroborated_postings`), accumulating this posting
    when new. 0 for everything the gate does not apply to (not ai-origin,
    not proposed, same posting re-extracting)."""
    from app.models.enums import SkillOrigin

    if skill.origin != SkillOrigin.AI.value or skill.status != "proposed":
        return 0
    provenance = dict(skill.provenance or {})
    origin_pid = provenance.get("posting_id")
    pid = str(posting.id)
    if pid == origin_pid:
        return 0
    seen = list(provenance.get("corroborated_postings") or [])
    if pid not in seen:
        seen.append(pid)
        provenance["corroborated_postings"] = seen[:CORROBORATION_CAP]
        skill.provenance = provenance
        flag_modified(skill, "provenance")
    distinct = len({origin_pid, *seen}) if origin_pid else len(seen)
    return distinct


async def _auto_promote(db: AsyncSession, skill: Skill, postings_count: int) -> None:
    """plan 147 — the corroboration gate tripped: promote the label to the
    active catalog (the orgs decision-8 pattern; promotion still rides the
    `promote()` seam) and stamp the decision into provenance for audit."""
    from app.services.catalog.taxonomy_service import TaxonomyService

    try:
        promoted = await TaxonomyService(db).promote(
            skill.id, auto=True, detail={"postings": postings_count}
        )
    except ValidationError:
        logger.warning("corroboration promotion skipped for %s (status moved)", skill.key)
        return
    provenance = {
        **(promoted.provenance or {}),
        "auto_promoted": {
            "at": datetime.now(UTC).isoformat(),
            "postings": postings_count,
        },
    }
    promoted.provenance = provenance
    flag_modified(promoted, "provenance")
    await db.commit()
    logger.info(
        "skill %s auto-promoted — corroborated by %s distinct postings",
        promoted.key,
        postings_count,
    )


# -------------------------------------------------------------------- run


async def run_extract_job(db: AsyncSession, payload: dict, *, job_id=None) -> dict:
    """POSTING_EXTRACT handler body: one structured call + apply."""
    posting_id = payload.get("posting_id")
    if not posting_id:
        raise ValidationError("posting_extract requires posting_id")
    rows = await db.execute(select(JobPosting).where(JobPosting.id == UUID(str(posting_id))))
    posting = rows.scalars().first()
    if posting is None:
        return {"skipped": "posting gone"}
    if posting.extract_version == EXTRACT_VERSION:
        return {"skipped": "already extracted"}
    # A previously-extracted posting reaching the queue again IS the
    # re-extract wave (manual bulk enqueue; the auto pass only queues
    # never-extracted rows) — the trigger rides `actor_ref`
    # (plan 142 amendment 4), not a separate actor kind.
    trigger = "bulk" if posting.extract_version is not None else "auto"
    return await extract_posting_now(db, posting, trigger=trigger, job_id=job_id)


async def extract_posting_now(
    db: AsyncSession, posting: JobPosting, *, trigger: str = "manual", job_id=None
) -> dict:
    """The AI call + apply (also used by the admin re-extract action).

    The call is audited with ``run_id`` = the background job id (the
    amendment-5 identity: ``actor_ref.job_id`` = ``background_jobs.id`` =
    ``ai_generations.run_id``) and the journal row carries the audit's
    generation id + the call's duration."""
    from time import perf_counter

    from app.ai.agents.posting_extractor import extract_posting
    from app.ai.gateway import RunRef
    from app.services.postings.postings_service import _active_skill_keys

    description = str((posting.raw or {}).get("description") or "")
    skills_raw = [str(s) for s in (posting.raw or {}).get("_skills_raw", [])]
    taxonomy = await _active_skill_keys(db)
    started = perf_counter()
    run_ref = RunRef(id=job_id, stage="posting_extract") if job_id is not None else None
    result, audit = await extract_posting(
        db,
        None,
        posting.title,
        description,
        skills_raw,
        taxonomy,
        run=run_ref,
    )
    actor_ref: dict = {"trigger": trigger}
    if job_id is not None:
        actor_ref["job_id"] = str(job_id)
    if audit.get("id") is not None:
        actor_ref["ai_generation_id"] = str(audit["id"])
    duration_ms = int((perf_counter() - started) * 1000)
    await apply_extract(db, posting, result, actor_ref=actor_ref, duration_ms=duration_ms)
    await db.commit()
    return {
        "extracted": True,
        "skills": len(result.skills),
        "needs_review": posting.needs_review,
    }
