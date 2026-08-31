"""Postings service (Phase 26): sync, skill-ID mapping, fit deltas,
listings, interactions, alerts, expiry.

Mapping is literal-ID only: keyword/alias extraction resolves taxonomy
skills, an audited AI pass covers the rest, and catalog matching is an
intersection over `job_skills`/`posting_skills` FK ids — labels never
match (plan 21 discipline)."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import registry
from app.core.errors import ValidationError
from app.models.enums import (
    MappingMethod,
    NotificationRuleKind,
    PostingEvidence,
    PostingSkillPriority,
)
from app.models.job_model import Job, JobSkill
from app.models.posting_model import (
    JobPosting,
    JobSource,
    PostingInteraction,
    PostingSkill,
)
from app.models.taxonomy_model import Skill

AUTO_MAP_THRESHOLD = 0.34
FRESH_DECAY_PER_WEEK = 0.5
FRESH_DECAY_CAP = 2.0
POSTING_MAX_AGE_DAYS = 45

SKILL_ALIASES_EXTRA = {
    "js": "javascript",
    "nodejs": "node",
    "golang": "go",
    "py": "python",
    "postgres": "postgresql",
    "k8s": "kubernetes",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _norm(token: str) -> str:
    return SKILL_ALIASES_EXTRA.get(token.strip().lower(), token.strip().lower())


# ------------------------------------------------------------------- sync


async def sync_source(db: AsyncSession, source: JobSource) -> dict:
    """Fetch via the connector (isolated), upsert postings, map, alert.

    A failing connector errors its own source row — never the queue or
    other sources (plan 26 isolation contract)."""
    try:
        connector = registry.get_connector(source.connector_key)
    except ValidationError as exc:
        source.error = str(exc)
        await db.commit()
        return {"synced": 0, "error": str(exc)}
    try:
        result = await connector.fetch(source.config, source.sync_state or {})
    except Exception as exc:  # noqa: BLE001 — isolation: capture, never raise
        source.error = f"connector failure: {exc}"
        await db.commit()
        return {"synced": 0, "error": str(exc)}

    synced = 0
    errors = list(result.partial_errors)
    fresh: list[tuple[JobPosting, bool]] = []
    for raw in result.postings:
        try:
            posting = await upsert_posting(db, source, raw)
            if posting is not None:
                synced += 1
                demand = False
                if posting.status == "mapped":
                    recipients = await check_new_posting_alerts(db, posting)
                    demand = bool(recipients)
                fresh.append((posting, demand))
        except ValidationError as exc:
            errors.append(f"{raw.external_id}: {exc}")
    source.sync_state = result.next_state or {}
    source.last_run_at = _utcnow()
    source.error = "; ".join(errors)[:2000]
    await db.commit()
    # Deep extraction (plan 31) is queued, never blocking the sync path;
    # demand-matched postings enqueue first (oldest-first claim order).
    from app.services.extract_service import plan_extractions

    extract_queued = await plan_extractions(db, fresh, backlog=True)
    return {"synced": synced, "extract_queued": extract_queued, "errors": errors}


async def upsert_posting(
    db: AsyncSession, source: JobSource, raw
) -> Optional[JobPosting]:
    """Dedup by (source_id, external_id) + content_hash — unchanged content
    is a no-op; changed content re-maps unless a human mapped it."""
    rows = await db.execute(
        select(JobPosting).where(
            JobPosting.source_id == source.id, JobPosting.external_id == raw.external_id
        )
    )
    posting = rows.scalars().first()
    content = raw.model_dump(mode="json")
    content_hash = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    if posting is not None and posting.content_hash == content_hash:
        return None
    content_changed = posting is not None
    if posting is None:
        posting = JobPosting(
            source_id=source.id, external_id=raw.external_id, content_hash=content_hash
        )
        db.add(posting)
    else:
        posting.content_hash = content_hash
    posting.title = raw.title[:300]
    posting.org = raw.org[:200]
    posting.location = raw.location.model_dump(mode="json")
    posting.url = raw.url[:1000]
    posting.seniority = raw.seniority
    posting.employment_type = raw.employment_type
    posting.contract_type = raw.contract_type
    posting.onsite_policy = raw.onsite_policy
    posting.work_hours = raw.work_hours
    posting.hours_per_week_min = raw.hours_per_week_min
    posting.hours_per_week_max = raw.hours_per_week_max
    posting.travel_class = raw.travel_class
    posting.education_level = raw.education_level
    posting.salary_currency = raw.salary.currency if raw.salary else None
    posting.salary_min = raw.salary.min if raw.salary else None
    posting.salary_max = raw.salary.max if raw.salary else None
    posting.salary_period = raw.salary.period if raw.salary else None
    posting.posted_at = raw.posted_at or posting.posted_at or _utcnow()
    posting.expires_at = raw.expires_at
    posting.raw = raw.raw or {}
    if posting.status == "expired":
        posting.status = "new"
    posting.raw = {**(raw.raw or {}), "_skills_raw": list(raw.skills_raw)[:60]}
    if posting.mapping_method != MappingMethod.MANUAL.value:
        await map_posting(db, posting, tokens=raw.skills_raw)
    if content_changed:
        # Content changed ⇒ any previous deep extract is stale (plan-31
        # staleness pattern): reset so the queued pass re-runs.
        posting.extract = {}
        posting.extract_version = None
        posting.needs_review = False
    await db.flush()
    return posting


# ----------------------------------------------------------------- mapping


async def _taxonomy_index(db: AsyncSession) -> dict[str, UUID]:
    """lower(alias/label/key) + extra aliases → skill_id."""
    rows = (await db.execute(select(Skill))).scalars().all()
    index: dict[str, UUID] = {}
    for skill in rows:
        index[_norm(skill.key)] = skill.id
        index[_norm(skill.label)] = skill.id
        for alias in skill.aliases or []:
            index[_norm(str(alias))] = skill.id
    return index


def _match_keywords(text: str, index: dict[str, UUID]) -> dict[str, UUID]:
    """Whole-token scan over the alias index (explicit hits). Punctuation is
    neutralized so 'Python, SQL' still matches both."""
    normalized = text.lower()
    for char in ",;|/()[]":
        normalized = normalized.replace(char, " ")
    haystack = f" {normalized} "
    found: dict[str, UUID] = {}
    for token in sorted(index, key=len, reverse=True):
        if token and f" {token} " in haystack:
            found.setdefault(token, index[token])
    return found


async def map_posting(
    db: AsyncSession, posting: JobPosting, tokens: Optional[list[str]] = None
) -> None:
    """Extract taxonomy skills (alias index first, audited AI second) and
    map onto the catalog by skill-ID intersection; below threshold stays
    unmapped for plan-15 moderation."""
    index = await _taxonomy_index(db)
    tokens = tokens if tokens is not None else _posting_skill_tokens(posting)
    description = str((posting.raw or {}).get("description") or "")
    haystack = " ".join([posting.title, *tokens, description])
    explicit = _match_keywords(haystack, index)

    inferred: dict[str, UUID] = {}
    confidence_ai = 0.6
    if len(explicit) < 2 and description:
        try:
            inferred = await _ai_extract_skills(db, posting, index)
        except Exception:  # noqa: BLE001 — AI is optional sugar on the pipeline
            inferred = {}

    skills: dict[UUID, tuple[str, float]] = {}
    for skill_id in explicit.values():
        skills.setdefault(skill_id, (PostingEvidence.EXPLICIT.value, 1.0))
    for skill_id in inferred.values():
        skills.setdefault(skill_id, (PostingEvidence.INFERRED.value, confidence_ai))

    await db.execute(
        PostingSkill.__table__.delete().where(PostingSkill.posting_id == posting.id)
    )
    for skill_id, (evidence, confidence) in skills.items():
        db.add(
            PostingSkill(
                posting_id=posting.id,
                skill_id=skill_id,
                evidence=evidence,
                confidence=confidence,
            )
        )

    if not skills:
        posting.mapping_method = None
        posting.mapping_confidence = None
        posting.mapping_reason = "no taxonomy skills recognised"
        posting.status = "new" if posting.status == "mapped" else posting.status
        return

    best_job, best_score, runner_up = await _best_catalog_job(db, set(skills))
    if best_job is not None and best_score >= AUTO_MAP_THRESHOLD:
        posting.catalog_job_id = best_job.id
        posting.mapping_method = MappingMethod.SKILL_OVERLAP.value
        posting.mapping_confidence = round(best_score, 3)
        posting.mapping_reason = (
            f"{len(skills)} skills intersect; overlap {best_score:.2f} "
            f"(runner-up {runner_up:.2f})"
        )
        posting.status = "mapped"
    else:
        posting.catalog_job_id = None
        posting.mapping_method = None
        posting.mapping_confidence = round(best_score, 3) if best_job else None
        posting.mapping_reason = (
            f"best overlap {best_score:.2f} below {AUTO_MAP_THRESHOLD} — moderation"
        )
        posting.status = "new" if posting.status == "mapped" else posting.status


def _posting_skill_tokens(posting: JobPosting) -> list[str]:
    return [str(s) for s in (posting.raw or {}).get("_skills_raw", [])]


async def resolve_posting(db: AsyncSession, ref_or_id: str) -> Optional[JobPosting]:
    """Plan 32: everywhere accepts a short `ref` (Crockford base32) or the
    internal UUID; unknown values resolve to None (caller 404s)."""
    token = str(ref_or_id).strip()
    try:
        posting_id = UUID(token)
    except ValueError:
        rows = await db.execute(
            select(JobPosting).where(JobPosting.ref == token.upper())
        )
        return rows.scalars().first()
    rows = await db.execute(select(JobPosting).where(JobPosting.id == posting_id))
    return rows.scalars().first()


async def _ai_extract_skills(
    db: AsyncSession, posting: JobPosting, index: dict[str, UUID]
) -> dict[str, UUID]:
    from app.ai.agents.posting_mapper import extract_skill_keys

    known_keys = await _active_skill_keys(db)
    result = await extract_skill_keys(
        db,
        None,
        posting.title,
        str((posting.raw or {}).get("description") or ""),
        known_keys,
    )
    resolved: dict[str, UUID] = {}
    for key in result:
        skill_id = index.get(_norm(key))
        if skill_id is not None:
            resolved[key] = skill_id
    return resolved


async def _active_skill_keys(db: AsyncSession) -> list[str]:
    rows = await db.execute(select(Skill.key).where(Skill.status == "active"))
    return list(rows.scalars().all())


async def _best_catalog_job(
    db: AsyncSession, posting_skill_ids: set[UUID]
) -> tuple[Optional[Job], float, float]:
    """Skill-ID intersection weighted by job_skills importance/level."""
    from app.services.fit.dimensions import IMPORTANCE_WEIGHT

    rows = await db.execute(
        select(Job, JobSkill).join(JobSkill, JobSkill.job_id == Job.id)
    )
    scored: dict[UUID, tuple[float, float, Job]] = {}
    for job, link in rows:
        weight = IMPORTANCE_WEIGHT.get(link.importance, 1.0) * (
            min(link.required_level, 10) / 10.0
        )
        entry = scored.setdefault(job.id, [0.0, 0.0, job])
        entry[1] += weight
        if link.skill_id in posting_skill_ids:
            entry[0] += weight
    best = None
    best_score = 0.0
    runner_up = 0.0
    ranked: list[tuple[float, UUID]] = []
    for job_id, (hit, total, job) in scored.items():
        if total <= 0:
            continue
        ranked.append((hit / total, job_id))
        if best is None or hit / total > best_score:
            runner_up = best_score
            best = job
            best_score = hit / total
        elif hit / total > runner_up:
            runner_up = hit / total
    if best is None:
        return None, 0.0, 0.0
    return best, best_score, runner_up


# --------------------------------------------------------------- user fit


async def posting_fit(db: AsyncSession, user_id: UUID, posting: JobPosting) -> float:
    """Mapped catalog fit + deterministic deltas — no per-posting AI."""
    from app.services.deps import get_profile_for_user

    if posting.catalog_job_id is None:
        return 0.0
    from app.services.job_service import JOB_LOAD_OPTIONS

    rows = await db.execute(
        select(Job).options(*JOB_LOAD_OPTIONS).where(Job.id == posting.catalog_job_id)
    )
    catalog_job = rows.scalars().unique().first()
    if catalog_job is None:
        return 0.0
    profile = await get_profile_for_user(db, user_id)
    from app.services.fit.service import FitService

    fit_service = FitService(db)
    result = await fit_service.fit_for(profile, catalog_job)
    score = result.score

    now = _utcnow()
    posted = posting.posted_at or posting.created_at
    if posted:
        age_weeks = max(0.0, (now - posted).total_seconds() / (7 * 86400))
        score -= min(FRESH_DECAY_CAP, FRESH_DECAY_PER_WEEK * age_weeks)

    basics = profile.basics or {}
    prefs = profile.work_preferences or {}
    location = posting.location or {}
    if location.get("remote"):
        score += 0.5 if prefs.get("remote_ok", True) else -1.0
    elif basics.get("city") and location.get("city"):
        if basics["city"].strip().lower() != location["city"].strip().lower():
            score -= 0.5

    stage, _source = await _stage_for(db, user_id)
    seniority_ranks = {
        "intern": 0,
        "junior": 1,
        "mid": 2,
        "senior": 3,
        "lead": 4,
        "principal": 5,
    }
    posting_rank = seniority_ranks.get(posting.seniority or "", None)
    if posting_rank is not None:
        if stage.value == "student" and posting_rank >= 3:
            score -= 1.0
        if stage.value == "experienced" and posting_rank <= 1:
            score -= 0.5

    return round(max(0.0, min(10.0, score)), 2)


async def _stage_for(db: AsyncSession, user_id: UUID):
    from app.services.stages_service import stage_for_user

    return await stage_for_user(db, user_id)


# ---------------------------------------------------------------- listings


async def list_postings(
    db: AsyncSession,
    user_id: UUID,
    *,
    source_id: Optional[UUID] = None,
    remote: Optional[bool] = None,
    seniority: Optional[str] = None,
    catalog_job_id: Optional[UUID] = None,
    saved: bool = False,
    sort: str = "fit",
    include_hidden: bool = False,
) -> dict:
    """Live tab: mapped-first listings with fit sort (unseen-first honored)."""
    from sqlalchemy.orm import selectinload

    from app.models.job_model import JobTag

    query = (
        select(JobPosting, PostingInteraction)
        .options(
            selectinload(JobPosting.catalog_job).selectinload(Job.family),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.tag_links)
            .selectinload(JobTag.tag),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.skill_links)
            .selectinload(JobSkill.skill),
        )
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == user_id),
        )
        .where(JobPosting.status.in_(["mapped", "new"]))
    )
    if not include_hidden:
        query = query.where(
            or_(
                PostingInteraction.id.is_(None),
                PostingInteraction.hidden_at.is_(None),
            )
        )
    if source_id is not None:
        query = query.where(JobPosting.source_id == source_id)
    if remote is not None:
        query = query.where(JobPosting.location["remote"].as_boolean() == remote)
    if seniority:
        query = query.where(JobPosting.seniority == seniority)
    if catalog_job_id is not None:
        query = query.where(JobPosting.catalog_job_id == catalog_job_id)
    rows = (await db.execute(query.order_by(JobPosting.posted_at.desc()))).all()

    items = []
    unseen = 0
    for posting, interaction in rows:
        seen = interaction is not None and interaction.seen_at is not None
        if saved:
            if interaction is None or interaction.saved_at is None:
                continue
        if not seen:
            unseen += 1
        items.append({"posting": posting, "interaction": interaction, "seen": seen})

    if sort == "fresh":
        items.sort(key=lambda i: i["posting"].posted_at or _utcnow(), reverse=True)
    else:
        fits = {}
        for item in items:
            fits[item["posting"].id] = await posting_fit(db, user_id, item["posting"])
        items.sort(
            key=lambda i: (
                0 if not i["seen"] else 1,
                -fits[i["posting"].id],
                i["posting"].title,
            )
        )
        for item in items:
            item["fit"] = fits[item["posting"].id]
    return {"items": items, "unseen": unseen, "total": len(items)}


# ------------------------------------------------------- skill-level search


PRIORITY_WEIGHT = {"must_have": 3.0, "nice_to_have": 2.0, "bonus": 1.0}


def parse_skill_entries(raw: str) -> list[tuple[str, Optional[int]]]:
    """`skills=sql:4,python:3` → [(key, level|None)]; validated at API."""
    entries: list[tuple[str, Optional[int]]] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, level = part.partition(":")
        key = key.strip()
        if not key:
            raise ValidationError(f"invalid skills filter segment: {part!r}")
        if sep:
            try:
                lvl = int(level)
            except ValueError as exc:
                raise ValidationError(
                    f"invalid level for skill {key!r} (use 1–10)"
                ) from exc
            if not 1 <= lvl <= 10:
                raise ValidationError(f"level for {key!r} out of range 1–10")
            entries.append((key, lvl))
        else:
            entries.append((key, None))
    if not entries:
        raise ValidationError("skills filter is empty")
    return entries


async def search_postings(
    db: AsyncSession,
    user_id: UUID,
    *,
    entries: list[tuple[str, Optional[int]]],
    mode: str = "all",
    priority: Optional[str] = None,
    source_id: Optional[UUID] = None,
    remote: Optional[bool] = None,
    seniority: Optional[str] = None,
    catalog_job_id: Optional[UUID] = None,
    saved: bool = False,
    sort: str = "fresh",
    match_profile: bool = False,
) -> dict:
    """Skill+level search (plan 31): `posting_skills` join on skill_id +
    required_level ≥ requested; all/any semantics; NULL-level rows are
    excluded from level-threshold matches (not yet deep-extracted)."""
    from sqlalchemy.orm import selectinload

    from app.models.job_model import Job, JobSkill, JobTag

    normalized: list[tuple[str, Optional[int]]] = []
    for key, lvl in entries:
        normalized.append((_norm(key), lvl))
    rows = await db.execute(
        select(Skill).where(Skill.key.in_([k for k, _ in normalized]))
    )
    by_key = {skill.key: skill for skill in rows.scalars().all()}
    unknown = [
        orig for (orig, _), (key, _) in zip(entries, normalized) if key not in by_key
    ]
    if unknown:
        raise ValidationError(f"Unknown skills: {', '.join(sorted(set(unknown)))}")

    conditions = []
    for norm_key, lvl in normalized:
        skill = by_key.get(norm_key)
        if skill is None:
            continue
        cond = select(PostingSkill.id).where(
            PostingSkill.posting_id == JobPosting.id,
            PostingSkill.skill_id == skill.id,
        )
        if priority:
            cond = cond.where(PostingSkill.priority == priority)
        if lvl is not None:
            cond = cond.where(
                PostingSkill.required_level.is_not(None),
                PostingSkill.required_level >= lvl,
            )
        conditions.append(cond.exists())

    query = (
        select(JobPosting, PostingInteraction)
        .options(
            selectinload(JobPosting.catalog_job).selectinload(Job.family),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.tag_links)
            .selectinload(JobTag.tag),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.skill_links)
            .selectinload(JobSkill.skill),
        )
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == user_id),
        )
        .where(JobPosting.status.in_(["mapped", "new"]))
    )
    if mode == "all":
        query = query.where(and_(*conditions))
    else:
        query = query.where(or_(*conditions))
    if not saved:
        query = query.where(
            or_(
                PostingInteraction.id.is_(None),
                PostingInteraction.hidden_at.is_(None),
            )
        )
    if source_id is not None:
        query = query.where(JobPosting.source_id == source_id)
    if remote is not None:
        query = query.where(JobPosting.location["remote"].as_boolean() == remote)
    if seniority:
        query = query.where(JobPosting.seniority == seniority)
    if catalog_job_id is not None:
        query = query.where(JobPosting.catalog_job_id == catalog_job_id)
    rows = (await db.execute(query.order_by(JobPosting.posted_at.desc()))).all()

    items = []
    unseen = 0
    for posting, interaction in rows:
        seen = interaction is not None and interaction.seen_at is not None
        if saved:
            if interaction is None or interaction.saved_at is None:
                continue
        if not seen:
            unseen += 1
        items.append({"posting": posting, "interaction": interaction, "seen": seen})

    if match_profile:
        coverages = {}
        for item in items:
            coverages[item["posting"].id] = await profile_coverage(
                db, user_id, item["posting"]
            )
        items.sort(
            key=lambda i: (
                0 if not i["seen"] else 1,
                -coverages[i["posting"].id],
                i["posting"].title,
            )
        )
        for item in items:
            item["coverage"] = coverages[item["posting"].id]
    elif sort == "fit":
        fits = {}
        for item in items:
            fits[item["posting"].id] = await posting_fit(db, user_id, item["posting"])
        items.sort(
            key=lambda i: (
                0 if not i["seen"] else 1,
                -fits[i["posting"].id],
                i["posting"].title,
            )
        )
        for item in items:
            item["fit"] = fits[item["posting"].id]
    else:
        items.sort(key=lambda i: i["posting"].posted_at or _utcnow(), reverse=True)
    return {"items": items, "unseen": unseen, "total": len(items)}


async def profile_coverage(
    db: AsyncSession, user_id: UUID, posting: JobPosting
) -> float:
    """Deterministic coverage of the user's skills over the posting's
    extracted requirements — the plan-22 curve, no new semantics:
    per skill `min(user, required) / required`, priority-weighted, with
    fully-unmet must-have requirements capping the score at 4.0."""
    from app.models.user_model import UserSkill

    rows = await db.execute(
        select(PostingSkill).where(PostingSkill.posting_id == posting.id)
    )
    links = [link for link in rows.scalars().all() if link.required_level is not None]
    if not links:
        return 0.0
    level_rows = await db.execute(
        select(UserSkill.skill_id, UserSkill.level).where(UserSkill.user_id == user_id)
    )
    user_levels: dict[UUID, int] = {
        skill_id: level for skill_id, level in level_rows.all()
    }

    total_weight = 0.0
    covered = 0.0
    must_unmet = 0
    must_partial = 0
    for link in links:
        weight = PRIORITY_WEIGHT.get(link.priority or "", 1.0)
        total_weight += weight
        level = user_levels.get(link.skill_id)
        if level is None:
            if link.priority == PostingSkillPriority.MUST_HAVE.value:
                must_unmet += 1
            continue
        ratio = min(level, link.required_level) / max(1, link.required_level)
        covered += weight * ratio
        if link.priority == PostingSkillPriority.MUST_HAVE.value:
            if ratio <= 0:
                must_unmet += 1
            elif ratio < 1:
                must_partial += 1
    if total_weight <= 0:
        return 0.0
    score = 10.0 * covered / total_weight
    if must_unmet:
        score = min(score, 4.0)
    elif must_partial:
        score = min(score, 6.0)
    return round(score, 2)


async def _lazy_interaction(
    db: AsyncSession, user_id: UUID, posting_id: UUID
) -> PostingInteraction:
    rows = await db.execute(
        select(PostingInteraction).where(
            PostingInteraction.user_id == user_id,
            PostingInteraction.posting_id == posting_id,
        )
    )
    interaction = rows.scalars().first()
    if interaction is None:
        interaction = PostingInteraction(user_id=user_id, posting_id=posting_id)
        db.add(interaction)
        await db.flush()
    return interaction


async def mark_seen(db: AsyncSession, user_id: UUID, posting_ids: list[UUID]) -> int:
    marked = 0
    for posting_id in posting_ids:
        interaction = await _lazy_interaction(db, user_id, posting_id)
        if interaction.seen_at is None:
            interaction.seen_at = _utcnow()
            marked += 1
    await db.commit()
    return marked


async def set_state(
    db: AsyncSession,
    user_id: UUID,
    posting_id: UUID,
    *,
    field: str,
    value: Optional[datetime],
    extra: Optional[dict] = None,
) -> PostingInteraction:
    rows = await db.execute(select(JobPosting).where(JobPosting.id == posting_id))
    if rows.scalars().first() is None:
        raise ValidationError("Posting not found")
    interaction = await _lazy_interaction(db, user_id, posting_id)
    setattr(interaction, field, value)
    if extra:
        for key, val in extra.items():
            setattr(interaction, key, val)
    await db.commit()
    await db.refresh(interaction)
    return interaction


# ------------------------------------------------------------------ alerts


async def check_new_posting_alerts(db: AsyncSession, posting: JobPosting) -> list[UUID]:
    """new_posting_match: mapped posting above a user's fit threshold —
    plan 24's rule table + dedup/cooldown machinery, new trigger.

    Returns the recipients — plan 31 reuses the evaluation as the
    demand signal for extraction priority."""
    if posting.status != "mapped" or posting.catalog_job_id is None:
        return []
    from app.models.engagement_model import NotificationRule
    from app.services.engagement_service import EngagementService

    engagement = EngagementService(db)
    rules = (
        (
            await db.execute(
                select(NotificationRule).where(
                    NotificationRule.kind
                    == NotificationRuleKind.NEW_POSTING_MATCH.value,
                    NotificationRule.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    recipients: list[UUID] = []
    for rule in rules:
        params = {
            "min_fit": 7.0,
            "max_per_day": 5,
            **(rule.params or {}),
        }
        if engagement._quiet_suppressed(params):
            continue
        fit = await posting_fit(db, rule.user_id, posting)
        if fit < float(params["min_fit"]):
            continue
        recipients.append(rule.user_id)
        await engagement.emit(
            rule.user_id,
            NotificationRuleKind.NEW_POSTING_MATCH.value,
            title=f"New match: {posting.title}",
            body=f"{posting.org or 'A company'} posted a role mapping to your catalog — fit {fit:.1f}/10.",
            payload={
                "posting_id": str(posting.id),
                "job_id": str(posting.catalog_job_id),
                "url": posting.url,
                "score": fit,
                "link": "/postings",
            },
            dedup_key=f"posting-match:{rule.user_id}:{posting.id}",
            max_per_day=int(params["max_per_day"]),
        )
    return recipients


# ------------------------------------------------------------------ expiry


async def expire_stale(db: AsyncSession) -> int:
    """expires_at passed or 45 days old → `expired` (plan-29 schedule later)."""
    now = _utcnow()
    cutoff = now - timedelta(days=POSTING_MAX_AGE_DAYS)
    rows = await db.execute(
        select(JobPosting).where(
            JobPosting.status.in_(["new", "mapped"]),
            (JobPosting.expires_at.is_not(None) & (JobPosting.expires_at < now))
            | (JobPosting.posted_at.is_not(None) & (JobPosting.posted_at < cutoff)),
        )
    )
    expired = 0
    for posting in rows.scalars().all():
        posting.status = "expired"
        expired += 1
    if expired:
        await db.commit()
    return expired


# ------------------------------------------------------------------- queue


async def run_sync_job(db: AsyncSession, payload: dict) -> dict:
    """POSTING_SYNC handler: one source or every enabled source."""
    source_id = payload.get("source_id")
    if source_id:
        rows = await db.execute(
            select(JobSource).where(JobSource.id == UUID(source_id))
        )
        sources = list(rows.scalars().all())
    else:
        sources = list(
            (await db.execute(select(JobSource).where(JobSource.enabled.is_(True))))
            .scalars()
            .all()
        )
    totals = {"synced": 0, "sources": len(sources), "errors": []}
    for source in sources:
        result = await sync_source(db, source)
        totals["synced"] += result.get("synced", 0)
        if result.get("error"):
            totals["errors"].append(f"{source.key}: {result['error']}")
    await expire_stale(db)
    return totals
