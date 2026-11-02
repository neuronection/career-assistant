"""Deep posting extraction (Phase 31): the queued LLM pass over
`job_postings`.

Two-speed pipeline —'s fast alias/keyword pass stays the sync
path; this module owns the deep pass: one audited structured LLM call
per posting (AITaskType.POSTING_EXTRACT) through the queue,
demand-driven priority (postings matching any alert rule extract
first), `extract_version` staleness for prompt bumps, and normalization
into `posting_skills.required_level`/`priority` + typed columns.
Confidence below the threshold means a field is suppressed and the
posting flagged `needs_review` — never guessed silently.

Plan 153 v5: pass 1 emits taxonomy-blind verbatim raw labels; this
module resolves them — alias-index exact hits deterministically, the
rest through ONE batched pass-2 `resolve_skills` call — and applies:
matched keys tag `posting_skills` rows (proposed targets included),
unmatched labels propose. The corroborated auto-promote loop runs AFTER
the apply transaction's commit (the journal + data stay atomic;
`TaxonomyService.promote` commits on its own terms), behind the
near-duplicate dedup gate. `mode: "resolve"` replay re-runs only the
resolution over the stored raw labels — no pass-1 spend."""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import AINotConfiguredError, ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.enums import (
    BackgroundJobStatus,
    BackgroundJobType,
    PostingEvidence,
    SkillOrigin,
)
from app.models.posting_model import JobPosting, PostingSkill
from app.models.taxonomy_model import Skill
from app.services.postings.salary import BASIS_VALUES, annualized

if TYPE_CHECKING:
    from app.ai.gateway import RunRef

logger = logging.getLogger(__name__)

EXTRACT_VERSION = 5
CONFIDENCE_THRESHOLD = 0.6

# A proposed extraction label seen again from a different posting is
# corroborated; this many distinct postings auto-promote it (plan 147 —
# the orgs decision-8 corroboration pattern applied to skills).
CORROBORATION_MIN_POSTINGS = 2
CORROBORATION_CAP = 20

# The auto-promote dedup gate (plan 153 slice 3): an ACTIVE skill this
# near to the promoted label blocks promotion — the row stays proposed
# for admin merge, never auto-merged. c/c++-style pairs live at trigram
# 1.0 (punctuation-blind), so the lexical bar catches them; cosine only
# ever adds blocks (semantic is a ranking signal, never a filter).
DEDUP_TRIGRAM_BAR = 0.75
DEDUP_COSINE_BAR = 0.90

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
    run: "RunRef | None" = None,
) -> tuple[JobPosting, list[tuple[Skill, int]]]:
    """Store a validated PostingExtract: suppress low-confidence fields
    (needs_review), normalize typed columns, fill posting_skills levels.
    Journals as `extract_llm` (same transaction; `description_clean` is a
    field of the envelope, folded here — no separate writer).

    Returns the posting plus the corroborated ``(skill, postings_count)``
    pairs the caller must auto-promote AFTER its own commit — promotion
    never rides this transaction (``TaxonomyService.promote`` commits on
    its own terms; plan 153 slice 3's commit-boundary fix)."""
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

    await db.flush()
    promotions = await _apply_extract_skills(
        db, posting, data["skills"], actor_ref=actor_ref, run=run
    )
    posting.extract = data
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
    return posting, promotions


async def _apply_extract_skills(
    db: AsyncSession,
    posting: JobPosting,
    skills: list[dict],
    *,
    actor_ref: dict | None = None,
    run: "RunRef | None" = None,
    operation: dict | None = None,
    journal: bool = True,
) -> list[tuple[Skill, int]]:
    """Resolve verbatim raw labels and apply (plan 153 v5): alias-index
    exact hits resolve deterministically (active rows first, deprecated
    exact keys fall back for unmatched tokens — the matcher precedence
    `_taxonomy_index` shares), the remaining labels go through ONE
    batched pass-2 `resolve_skills` call whose adjudicated verdicts are
    applied directly (never re-validated — the seam already degraded
    unusable answers and off-candidate keys to `new`). Matched keys tag
    `posting_skills` rows in place (proposed targets included, levels
    and priority from pass 1); labels resolving to proposed ai-origin
    rows corroborate them like new proposals do (the fragmentation
    fix). Every stored entry carries both `raw_label` and the stamped
    `skill_key` (null when new) — the replay substrate. Unmatched
    labels become proposals (never dropped, never label-matched).

    Journals the skills set-diff as `extract_llm` (same transaction;
    ``journal=False`` hands the row to the caller — the replay writer
    carries its own ``{replay: true}`` operation row). Returns the
    corroborated ``(skill, postings_count)`` pairs for the caller's
    post-commit promotion loop — this function never promotes and never
    commits.
    """
    from app.services.catalog.skills_service import SkillService
    from app.services.postings.change_journal import PostingChangeJournal, skills_state
    from app.services.postings.postings_service import _norm
    from app.services.postings.skill_candidates import Candidate, candidate_skills

    before = await skills_state(db, posting.id)
    groups: dict[str, list[dict]] = {}
    for entry in skills:
        label = str(entry.get("raw_label") or "").strip()
        if label:
            groups.setdefault(_norm(label), []).append(entry)

    resolved: dict[UUID, dict] = {}
    new_labels: list[dict] = []
    pending: list[tuple[dict, list[Candidate]]] = []
    winners: dict[str, dict] = {}
    for norm, entries in groups.items():
        entry = entries[0]
        candidates = await candidate_skills(db, str(entry["raw_label"]))
        if candidates and candidates[0].signal == "exact":
            resolved[candidates[0].skill_id] = entry
            entry["skill_key"] = candidates[0].key
        else:
            pending.append((entry, candidates))
        winners[norm] = entry

    if pending:
        candidate_rows = await _candidate_skill_rows(db, pending)
        offered = [
            {
                "label_ref": str(ref),
                "raw_label": str(entry["raw_label"]),
                "candidates": [
                    {
                        "key": candidate.key,
                        "label": candidate.label,
                        "aliases": list(candidate_rows[candidate.skill_id].aliases or [])
                        if candidate.skill_id in candidate_rows
                        else [],
                        "score": candidate.score,
                        "signal": candidate.signal,
                    }
                    for candidate in candidates
                ],
            }
            for ref, (entry, candidates) in enumerate(pending)
        ]
        verdicts = await _pass2_verdict_keys(db, offered, run=run)
        for ref, (entry, candidates) in enumerate(pending):
            match_key = verdicts.get(str(ref), "")
            match = next((c for c in candidates if c.key == match_key), None)
            if match is None:
                entry["skill_key"] = None
                new_labels.append(entry)
                continue
            resolved[match.skill_id] = entry
            entry["skill_key"] = match.key

    for norm, entries in groups.items():
        winner = winners[norm].get("skill_key")
        for twin in entries[1:]:
            twin["skill_key"] = winner

    resolved_skills: dict[UUID, Skill] = {}
    if resolved:
        rows = await db.execute(select(Skill).where(Skill.id.in_(list(resolved))))
        resolved_skills = {skill.id: skill for skill in rows.scalars().all()}

    existing: dict[UUID, PostingSkill] = {}
    if resolved:
        existing_rows = await db.execute(
            select(PostingSkill).where(
                PostingSkill.posting_id == posting.id,
                PostingSkill.skill_id.in_(resolved.keys()),
            )
        )
        existing = {row.skill_id: row for row in existing_rows.scalars().all()}

    for skill_id, entry in resolved.items():
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

    corroborated: list[tuple[Skill, int]] = []
    for skill_id in resolved:
        skill = resolved_skills[skill_id]
        count = _record_corroboration(skill, posting)
        if count:
            await db.flush()
        if count >= CORROBORATION_MIN_POSTINGS:
            corroborated.append((skill, count))

    if new_labels:
        service = SkillService(db)
        for entry in new_labels:
            label = str(entry.get("raw_label") or "").strip()
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

    if journal:
        PostingChangeJournal.record(
            db,
            posting.id,
            "extract_llm",
            actor_ref=actor_ref,
            operation=operation or {"extract_version": EXTRACT_VERSION},
            before={"skills": before},
            after={"skills": await skills_state(db, posting.id)},
        )
    return corroborated


async def _candidate_skill_rows(
    db: AsyncSession, pending: list[tuple[dict, list]]
) -> dict[UUID, Skill]:
    """The Skill rows behind one batch's candidates (aliases for the
    pass-2 prompt), ONE query for the whole call."""
    ids = {candidate.skill_id for _entry, candidates in pending for candidate in candidates}
    if not ids:
        return {}
    rows = await db.execute(select(Skill).where(Skill.id.in_(ids)))
    return {skill.id: skill for skill in rows.scalars().all()}


async def _pass2_verdict_keys(
    db: AsyncSession, offered: list[dict], *, run: "RunRef | None" = None
) -> dict[str, str]:
    """One batched pass-2 call → ``{label_ref: match_key}`` (``""`` when
    the label answers new). The reply is the adjudicated resolution
    (§8) — applied directly, never re-validated; an unconfigured or
    failing provider degrades every label to a deterministic `new`."""
    from app.ai.agents.skill_resolver import resolve_skills

    if not offered:
        return {}
    try:
        resolution = await resolve_skills(db, offered, run=run)
    except AINotConfiguredError:
        resolution = None
    if resolution is None:
        return {label["label_ref"]: "" for label in offered}
    return {
        verdict.label_ref: ("" if verdict.new else verdict.match_key)
        for verdict in resolution.verdicts
    }


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


async def _run_promotions(db: AsyncSession, promotions: list[tuple[Skill, int]]) -> None:
    """The corroborated auto-promote loop — run AFTER the caller's apply
    commit (plan 153 slice 3's commit-boundary fix): the extract journal
    and data land in one transaction, `TaxonomyService.promote` then
    commits on its own terms, and a crash between the two commits
    self-heals (the count is already ≥ 2; the next posting re-trips the
    gate)."""
    for skill, postings_count in promotions:
        await _auto_promote(db, skill, postings_count)


async def _dedup_gate_block(db: AsyncSession, skill: Skill) -> tuple[dict, dict] | None:
    """The plan-153 dedup gate: the first ACTIVE skill near the promoted
    label above the bars — exact (a claimed token IS a duplicate),
    trigram ≥ 0.75 or cosine ≥ 0.90. Candidate matching runs against
    active rows only, so a proposed twin never shadows an active
    near-duplicate. The lexical decision reads the trigram layer's own
    alias-aware score; the key/label re-derivation is the alias-free
    lower bound that still catches an embedding-decided candidate above
    the lexical bar (c/c++ blocks either way — plan-153 §7)."""
    from app.services.catalog.organization_service import trigram_similarity
    from app.services.postings.skill_candidates import candidate_skills

    label = skill.label or skill.key
    for candidate in await candidate_skills(db, label, active_only=True):
        trigram = max(
            trigram_similarity(label, candidate.key),
            trigram_similarity(label, candidate.label),
        )
        if candidate.signal == "trigram":
            trigram = max(trigram, candidate.score)
        blocked = (
            candidate.signal == "exact"
            or trigram >= DEDUP_TRIGRAM_BAR
            or (candidate.signal == "embedding" and candidate.score >= DEDUP_COSINE_BAR)
        )
        if blocked:
            return (
                {
                    "key": candidate.key,
                    "label": candidate.label,
                    "skill_id": str(candidate.skill_id),
                },
                {
                    "signal": candidate.signal,
                    "score": candidate.score,
                    "trigram": round(trigram, 4),
                },
            )
    return None


async def _auto_promote(db: AsyncSession, skill: Skill, postings_count: int) -> None:
    """plan 147 — the corroboration gate tripped: promote the label to the
    active catalog (the orgs decision-8 pattern; promotion still rides the
    `promote()` seam) and stamp the decision into provenance for audit.
    The plan-153 dedup gate runs first: a near-duplicate ACTIVE skill
    keeps the row proposed and stamps `auto_promote_blocked` instead."""
    from app.services.catalog.taxonomy_service import TaxonomyService

    blocked = await _dedup_gate_block(db, skill)
    if blocked is not None:
        near, scores = blocked
        skill.provenance = {
            **(skill.provenance or {}),
            "auto_promote_blocked": {
                "near": near,
                "scores": scores,
                "at": datetime.now(UTC).isoformat(),
            },
        }
        flag_modified(skill, "provenance")
        await db.commit()
        logger.info(
            "skill %s auto-promote blocked — near duplicate %s (%s %s)",
            skill.key,
            near["key"],
            scores["signal"],
            scores["score"],
        )
        return
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
    """POSTING_EXTRACT handler body: one structured call + apply.

    ``payload["mode"] == "resolve"`` is the plan-153 replay: checked
    BEFORE the version skip (a replay on a current-version posting must
    run — the skip exists for the full-extract wave only)."""
    posting_id = payload.get("posting_id")
    if not posting_id:
        raise ValidationError("posting_extract requires posting_id")
    rows = await db.execute(select(JobPosting).where(JobPosting.id == UUID(str(posting_id))))
    posting = rows.scalars().first()
    if posting is None:
        return {"skipped": "posting gone"}
    if payload.get("mode") == "resolve":
        return await replay_posting_resolution(db, posting, job_id=job_id)
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
    """The pass-1 call + resolution + apply (also used by the admin
    re-extract action).

    Both calls are audited with ``run_id`` = the background job id (the
    amendment-5 identity: ``actor_ref.job_id`` = ``background_jobs.id`` =
    ``ai_generations.run_id``; pass 2 rides the ``posting_extract.resolve``
    stage) and the journal row carries the audit's generation id + the
    call's duration. The apply transaction commits as one boundary; the
    corroborated auto-promote loop runs after it — promotion commits on
    its own terms."""
    from time import perf_counter

    from app.ai.agents.posting_extractor import extract_posting
    from app.ai.gateway import RunRef

    description = str((posting.raw or {}).get("description") or "")
    skills_raw = [str(s) for s in (posting.raw or {}).get("_skills_raw", [])]
    started = perf_counter()
    run_ref = RunRef(id=job_id, stage="posting_extract") if job_id is not None else None
    resolve_ref = RunRef(id=job_id, stage="posting_extract.resolve") if job_id is not None else None
    result, audit = await extract_posting(
        db,
        None,
        posting.title,
        description,
        skills_raw,
        run=run_ref,
    )
    actor_ref: dict = {"trigger": trigger}
    if job_id is not None:
        actor_ref["job_id"] = str(job_id)
    if audit.get("id") is not None:
        actor_ref["ai_generation_id"] = str(audit["id"])
    duration_ms = int((perf_counter() - started) * 1000)
    _posting, promotions = await apply_extract(
        db, posting, result, actor_ref=actor_ref, duration_ms=duration_ms, run=resolve_ref
    )
    await db.commit()
    await _run_promotions(db, promotions)
    return {
        "extracted": True,
        "skills": len(result.skills),
        "needs_review": posting.needs_review,
    }


async def replay_posting_resolution(
    db: AsyncSession, posting: JobPosting, *, trigger: str = "replay", job_id=None
) -> dict:
    """`mode: "resolve"` — re-run ONLY candidate match + pass 2 over the
    stored verbatim raw labels (no pass-1 spend), re-apply, and journal
    as `extract_llm` with ``operation: {replay: true}``. Taxonomy
    changes (merges, promotions) re-resolve onto the current catalog;
    the envelope's non-skill fields stay untouched.

    A posting not on the current extract version is skipped: v4 rows
    predate the both-fields substrate (their resolved entries carry no
    `raw_label`), so they re-extract on demand instead."""
    entries = [
        entry
        for entry in (posting.extract or {}).get("skills") or []
        if str(entry.get("raw_label") or "").strip()
    ]
    if posting.extract_version != EXTRACT_VERSION or not entries:
        return {"skipped": "no replayable labels"}
    actor_ref: dict = {"trigger": trigger}
    if job_id is not None:
        actor_ref["job_id"] = str(job_id)
    from app.ai.gateway import RunRef
    from app.services.postings.change_journal import PostingChangeJournal, skills_state

    run_ref = RunRef(id=job_id, stage="posting_extract.resolve") if job_id is not None else None
    before_skills = await skills_state(db, posting.id)
    promotions = await _apply_extract_skills(
        db,
        posting,
        entries,
        actor_ref=actor_ref,
        run=run_ref,
        journal=False,
    )
    posting.extract = {**(posting.extract or {}), "skills": entries}
    flag_modified(posting, "extract")
    await db.flush()
    PostingChangeJournal.record(
        db,
        posting.id,
        "extract_llm",
        actor_ref=actor_ref,
        operation={"replay": True, "extract_version": EXTRACT_VERSION},
        before={"skills": before_skills},
        after={"skills": await skills_state(db, posting.id)},
    )
    await db.commit()
    await _run_promotions(db, promotions)
    return {
        "replayed": True,
        "skills": len(entries),
        "needs_review": posting.needs_review,
    }
