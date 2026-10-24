"""Per-posting match score (Phase 32): deterministic dimensions over
extracted posting data, cached in `posting_fits` with an inputs-hash
staleness flag. Unextracted postings fall back to the
mapped archetype's fit with a visible estimate note — never silently
blended. Weights reuse's user sliders, dimensions mapped 1:1
(prereqs→education, location_remote→location, seniority_stage→
experience); freshness carries a fixed weight (interests has no posting
analogue and stays unused)."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EducationLevel, EducationLevelOrder, PostingSkillPriority
from app.models.posting_model import JobPosting, PostingFit, PostingSkill
from app.models.user_model import UserSkill
from app.services.postings.fit.dimensions import FIT_VERSION

FRESH_WEIGHT = 1.0
FRESH_DECAY_PER_WEEK = 0.5
FRESH_DECAY_CAP = 2.0
SENIORITY_RANKS = {
    "intern": 0,
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "lead": 4,
    "principal": 5,
}
LANGUAGE_ORDER = {"basic": 0, "intermediate": 1, "advanced": 2, "native": 3}
PRIORITY_WEIGHT = {
    PostingSkillPriority.MUST_HAVE.value: 3.0,
    PostingSkillPriority.NICE_TO_HAVE.value: 2.0,
    PostingSkillPriority.BONUS.value: 1.0,
}

# The posting engine's dimension list as one code-referenced spec
# — the breakdown keys above and the metrics API read this.
POSTING_FIT_DIMENSIONS: tuple[dict, ...] = (
    {"engine": "posting_fit", "key": "skills", "label": "Skills"},
    {"engine": "posting_fit", "key": "prereqs", "label": "Prerequisites"},
    {"engine": "posting_fit", "key": "location_remote", "label": "Location & remote"},
    {"engine": "posting_fit", "key": "seniority_stage", "label": "Seniority & stage"},
    {"engine": "posting_fit", "key": "freshness", "label": "Freshness"},
)


def posting_fit_dimension_spec() -> list[dict]:
    return [dict(entry) for entry in POSTING_FIT_DIMENSIONS]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _canonical_hash(payload: dict) -> str:
    canonical = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _user_skills(db: AsyncSession, user_id: UUID) -> dict[UUID, int]:
    rows = await db.execute(
        select(UserSkill.skill_id, UserSkill.level).where(
            UserSkill.user_id == user_id, UserSkill.derive_enabled
        )
    )
    return dict(rows.all())


def _skills_dimension(links: list[PostingSkill], user_levels: dict[UUID, int]) -> dict:
    """`min(user, required) / required`, priority-weighted; fully-unmet
    must-haves cap the score (the curve, sharpened by levels)."""
    live = [link for link in links if link.required_level is not None]
    if not live:
        return {
            "score": 7.0,
            "detail": "no extracted skill requirements",
            "neutral": True,
        }
    total_weight = 0.0
    covered = 0.0
    must_unmet = 0
    must_partial = 0
    for link in live:
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
        return {
            "score": 7.0,
            "detail": "no weighted skill requirements",
            "neutral": True,
        }
    score = 10.0 * covered / total_weight
    if must_unmet:
        score = min(score, 4.0)
    elif must_partial:
        score = min(score, 6.0)
    return {
        "score": round(score, 2),
        "detail": f"{len(live)} extracted requirement(s) covered",
    }


def _prereqs_dimension(posting: JobPosting, profile) -> dict:
    """Education + language prerequisites vs the profile."""
    score = 10.0
    details: list[str] = []
    required_education = (posting.extract or {}).get("education", {}) or {}
    level = required_education.get("level") or posting.education_level
    if level:
        basics = profile.basics or {}
        user_level = basics.get("education_level")
        if user_level:
            met = EducationLevelOrder.at_least(
                EducationLevel(str(user_level).lower()),
                EducationLevel(str(level).lower()),
            )
            score = 10.0 if met else 3.0
            details.append(f"education {'meets' if met else 'below'} requirement ({level})")
        else:
            details.append(f"requires education: {level} (yours unspecified)")

    required_languages = [
        str(lang).lower() for lang in (posting.extract or {}).get("languages") or []
    ]
    if required_languages:
        academics = profile.academics or {}
        user_languages = {
            str(lang.get("code", "")).lower(): LANGUAGE_ORDER.get(
                str(lang.get("level", "basic")), 0
            )
            for lang in academics.get("languages") or []
        }
        for lang in required_languages:
            if lang not in user_languages or user_languages[lang] < 1:
                details.append(f"language {lang} not evidenced")
                score = min(score, 5.0)
            else:
                details.append(f"language {lang} evidenced")
    if not details:
        return {"score": 7.0, "detail": "no explicit prerequisites", "neutral": True}
    return {"score": round(score, 2), "detail": "; ".join(details[:3])}


def _location_remote_dimension(posting: JobPosting, profile) -> dict:
    """The delta semantics as a standalone 0-10 dimension."""
    prefs = profile.work_preferences or {}
    basics = profile.basics or {}
    location = posting.location or {}
    if location.get("remote"):
        if prefs.get("remote_ok", True):
            return {"score": 10.0, "detail": "remote and you prefer remote"}
        return {"score": 4.0, "detail": "remote but you prefer on-site"}
    city = (location.get("city") or "").strip().lower()
    user_city = str(basics.get("city") or "").strip().lower()
    if user_city and city:
        if city == user_city:
            return {"score": 10.0, "detail": f"in your city ({city})"}
        return {"score": 5.0, "detail": f"in {city}, not your city"}
    return {"score": 7.0, "detail": "location neutral", "neutral": True}


def _seniority_stage_dimension(posting: JobPosting, stage_value: str) -> dict:
    rank = SENIORITY_RANKS.get(posting.seniority or "")
    if rank is None:
        return {"score": 7.0, "detail": "seniority not stated", "neutral": True}
    if stage_value == "student":
        score = 4.0 if rank >= 3 else 10.0 if rank <= 1 else 7.0
    elif stage_value == "experienced":
        score = 4.0 if rank <= 1 else 10.0
    else:
        score = 10.0 if rank <= 2 else 7.0
    return {"score": score, "detail": f"{posting.seniority} role for a {stage_value}"}


def _freshness_dimension(posting: JobPosting) -> dict:
    posted = posting.posted_at or posting.created_at
    if not posted:
        return {"score": 7.0, "detail": "posting date unknown", "neutral": True}
    age_weeks = max(0.0, (_utcnow() - posted).total_seconds() / (7 * 86400))
    decay = min(FRESH_DECAY_CAP, FRESH_DECAY_PER_WEEK * age_weeks)
    return {
        "score": round(10.0 - 10.0 * decay / max(FRESH_DECAY_CAP, 0.1), 2),
        "detail": f"posted {int(age_weeks)} week(s) ago",
    }


async def _load_context(db: AsyncSession, user_id: UUID) -> dict:
    """Shared per-user inputs (profile, stage, skill levels, weights) —
    loaded once per request, never per posting."""
    from app.services.deps import get_profile_for_user
    from app.services.postings.fit.service import FitService
    from app.services.profile.stages_service import stage_for_user

    profile = await get_profile_for_user(db, user_id)
    stage, _source = await stage_for_user(db, user_id)
    user_levels = await _user_skills(db, user_id)
    weights = await FitService(db).scoring_weights(profile)
    return {
        "profile": profile,
        "stage": stage,
        "user_levels": user_levels,
        "weights": weights,
    }


def _inputs_payload(
    user_id: UUID,
    posting: JobPosting,
    user_levels: dict[UUID, int],
    weights: dict,
    stage_value: str,
    constraints: dict | None = None,
) -> dict:
    return {
        "user_id": str(user_id),
        "posting_id": str(posting.id),
        "extract_version": posting.extract_version,
        "posted_at": posting.posted_at.isoformat() if posting.posted_at else None,
        "user_skills": {str(k): v for k, v in sorted(user_levels.items())},
        "weights": weights,
        "stage": stage_value,
        "lifestyle_constraints": {
            key: (constraints or {}).get(key)
            for key in (
                "salary_min",
                "salary_negotiable",
                "travel_days_per_month",
                "shift_tolerance",
                "commute_radius_km",
                "hours_available_per_week",
            )
        },
    }


def lifestyle_gates(posting: JobPosting, constraints: dict | None) -> list[str]:
    """lifestyle constraints vs v2 extract facts.

    gate semantics: reasons move a posting to flag surfaces,
    never silently exclude. Rules (documented, deterministic):
    - travel: stated days/month gate when above the user's tolerance;
      unstated `frequent` gates when tolerance < 10 (frequent ≈ 10+
      days/month by convention); `occasional`/`none` never gate.
    - shift: tolerance `none` + any shift/on-call/nights/weekends cue.
    - hours: stated weekly minimum above `hours_available_per_week`;
      unstated full_time counts as 35.
    """
    gates: list[str] = []
    constraints = constraints or {}
    facts = (posting.posting_facts or {}).get("lifestyle") or {}

    travel = facts.get("travel_required") or {}
    tolerance = constraints.get("travel_days_per_month")
    level = str(travel.get("level") or "")
    if tolerance is not None:
        stated = travel.get("days_per_month")
        if stated is not None:
            if int(stated) > int(tolerance):
                gates.append("travel")
        elif level == "frequent" and int(tolerance) < 10:
            gates.append("travel")

    shift = constraints.get("shift_tolerance")
    cues = {str(cue.get("cue") or "") for cue in facts.get("schedule_cues") or []}
    if shift == "none" and cues & {"shift_work", "on_call", "nights", "weekends"}:
        gates.append("shift")

    hours_available = constraints.get("hours_available_per_week")
    work_hours = facts.get("work_hours") or {}
    if hours_available is not None and work_hours:
        minimum = work_hours.get("hours_per_week_min")
        if minimum is None and work_hours.get("pattern") == "full_time":
            minimum = 35
        if minimum is not None and int(minimum) > int(hours_available):
            gates.append("hours")
    return gates


async def compute_posting_fit(
    db: AsyncSession, user_id: UUID, posting: JobPosting, context: dict | None = None
) -> dict:
    """Full deterministic score: {score, breakdown, extracted, estimate,
    inputs_hash}. When the posting is not deep-extracted the mapped
    archetype's fit is the visible fallback (estimate=true)."""
    if context is None:
        context = await _load_context(db, user_id)
    profile = context["profile"]
    stage = context["stage"]
    user_levels = context["user_levels"]
    weights = context["weights"]

    extracted = posting.extract_version is not None
    dimension_weights = {
        "skills": weights["skills"],
        "prereqs": weights["education"],
        "location_remote": weights["location"],
        "seniority_stage": weights["experience"],
        "freshness": FRESH_WEIGHT,
    }
    # Staleness contract: extract_version bumps whenever the posting's
    # extracted data changes, so the base payload is sufficient — the
    # cheap check in get_posting_fit hashes exactly this. Lifestyle
    # constraints ride the hash so gate changes invalidate cached rows.
    inputs = _inputs_payload(
        user_id,
        posting,
        user_levels,
        weights,
        stage.value,
        constraints=profile.constraints,
    )
    inputs_hash = _canonical_hash(inputs)

    if not extracted:
        from app.services.postings.postings_service import posting_fit

        estimate = await posting_fit(db, user_id, posting)
        return {
            "score": round(float(estimate), 2),
            "breakdown": {
                "archetype_estimate": {
                    "score": round(float(estimate), 2),
                    "detail": (
                        "archetype estimate — deep extraction has not run for this posting yet"
                    ),
                    "weight": 5,
                }
            },
            "extracted": False,
            "estimate": True,
            "gates": [],
            "inputs_hash": inputs_hash,
        }

    links = (
        (await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id)))
        .scalars()
        .all()
    )
    breakdown = {
        "skills": _skills_dimension(links, user_levels),
        "prereqs": _prereqs_dimension(posting, profile),
        "location_remote": _location_remote_dimension(posting, profile),
        "seniority_stage": _seniority_stage_dimension(posting, stage.value),
        "freshness": _freshness_dimension(posting),
    }
    for dim, entry in breakdown.items():
        entry["weight"] = dimension_weights[dim]

    total_weight = sum(entry["weight"] for entry in breakdown.values())
    score = (
        sum(entry["score"] * entry["weight"] for entry in breakdown.values()) / total_weight
        if total_weight
        else 7.0
    )
    return {
        "score": round(float(min(10.0, max(0.0, score))), 2),
        "breakdown": breakdown,
        "extracted": True,
        "estimate": False,
        "gates": lifestyle_gates(posting, profile.constraints),
        "inputs_hash": inputs_hash,
    }


def _expected_hash(user_id: UUID, posting: JobPosting, context: dict) -> str:
    return _canonical_hash(
        _inputs_payload(
            user_id,
            posting,
            context["user_levels"],
            context["weights"],
            context["stage"].value,
            constraints=context["profile"].constraints,
        )
    )


def _cache_is_fresh(cached: PostingFit | None, inputs_hash: str) -> bool:
    return (
        cached is not None
        and cached.inputs_hash == inputs_hash
        and cached.fit_version == FIT_VERSION
    )


def _cached_result(cached: PostingFit, posting: JobPosting, context: dict) -> dict:
    breakdown = cached.breakdown or {}
    return {
        "score": round(float(cached.score), 2),
        "breakdown": breakdown,
        "extracted": breakdown.get("archetype_estimate") is None if breakdown else False,
        "estimate": "archetype_estimate" in breakdown,
        "gates": lifestyle_gates(posting, context["profile"].constraints),
        "inputs_hash": cached.inputs_hash,
    }


def _fit_row(user_id: UUID, posting: JobPosting, computed: dict, now: datetime) -> dict:
    return {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "posting_id": posting.id,
        "score": Decimal(str(computed["score"])),
        "breakdown": computed["breakdown"],
        "inputs_hash": computed["inputs_hash"],
        "computed_at": now,
        "fit_version": FIT_VERSION,
        "created_at": now,
        "updated_at": now,
    }


async def _write_fit_rows(db: AsyncSession, rows: list[dict]) -> None:
    """Conflict-safe batch write-through of computed fits.

    The unique `(user_id, posting_id)` constraint referees concurrent
    requests; the loser adopts the winner's shape by updating the row
    (deterministic inputs ⇒ identical values).
    """
    if not rows:
        return
    from sqlalchemy.dialects import postgresql, sqlite

    table = PostingFit.__table__
    if db.get_bind().dialect.name == "sqlite":
        statement = sqlite.insert(table).values(rows)
    else:
        statement = postgresql.insert(table).values(rows)
    updated = {
        "score": statement.excluded.score,
        "breakdown": statement.excluded.breakdown,
        "inputs_hash": statement.excluded.inputs_hash,
        "computed_at": statement.excluded.computed_at,
        "fit_version": statement.excluded.fit_version,
        "updated_at": statement.excluded.updated_at,
    }
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["user_id", "posting_id"],
            set_=updated,
        )
    )
    await db.commit()


async def get_posting_fit(
    db: AsyncSession, user_id: UUID, posting: JobPosting, *, refresh: bool = False
) -> dict:
    """Cached read: cheap inputs load → hash → cached row is a hit when
    the hash matches; stale (or missing) rows recompute and persist."""
    context = await _load_context(db, user_id)
    inputs_hash = _expected_hash(user_id, posting, context)

    rows = await db.execute(
        select(PostingFit).where(PostingFit.user_id == user_id, PostingFit.posting_id == posting.id)
    )
    cached = rows.scalars().first()
    if not refresh and _cache_is_fresh(cached, inputs_hash):
        return _cached_result(cached, posting, context)

    computed = await compute_posting_fit(db, user_id, posting, context=context)
    await _write_fit_rows(db, [_fit_row(user_id, posting, computed, datetime.now(UTC))])
    return computed


async def get_posting_fits_batch(
    db: AsyncSession,
    user_id: UUID,
    postings: list[JobPosting],
    *,
    write_budget: int | None = None,
    refresh: bool = False,
) -> dict[UUID, dict]:
    """Listing-time batch: one shared context, cache-first per posting.

    Cached rows whose `inputs_hash` still matches are hits; missing or
    stale rows recompute (bounded by the caller's window) and are written
    through — `write_budget` caps the persistence when the caller passes a
    full feed instead of a page.
    """
    if not postings:
        return {}
    context = await _load_context(db, user_id)
    ids = [posting.id for posting in postings]
    cached_rows = (
        (
            await db.execute(
                select(PostingFit).where(
                    PostingFit.user_id == user_id, PostingFit.posting_id.in_(ids)
                )
            )
        )
        .scalars()
        .all()
    )
    cached_by_id = {row.posting_id: row for row in cached_rows}

    result: dict[UUID, dict] = {}
    pending: list[dict] = []
    now = datetime.now(UTC)
    for posting in postings:
        cached = cached_by_id.get(posting.id)
        inputs_hash = _expected_hash(user_id, posting, context)
        if not refresh and _cache_is_fresh(cached, inputs_hash):
            result[posting.id] = _cached_result(cached, posting, context)
            continue
        computed = await compute_posting_fit(db, user_id, posting, context=context)
        result[posting.id] = computed
        if write_budget is None or len(pending) < write_budget:
            pending.append(_fit_row(user_id, posting, computed, now))
    await _write_fit_rows(db, pending)
    return result


FEED_FIT_WRITE_BUDGET = 200
POSTING_FIT_SWEEP_BUDGET = 5000
POSTING_FIT_SWEEP_AGE = timedelta(days=7)
POSTING_FIT_SWEEP_BATCH = 200


async def sweep_posting_fits(
    db: AsyncSession,
    *,
    user_id: UUID | None = None,
    budget: int = POSTING_FIT_SWEEP_BUDGET,
    older_than: timedelta = POSTING_FIT_SWEEP_AGE,
    progress=None,
) -> dict:
    """Backfill and refresh the posting-fit cache off the request path.

    Rows older than `older_than` or stamped with a previous engine
    version are recomputed in batches, then postings with no cache row
    are backfilled newest-first. The row `budget` bounds one sweep; the
    next scheduled run continues where this one stopped. Staleness never
    becomes a stored boolean — every recompute re-derives `inputs_hash`.
    """
    from app.models.user_model import Profile

    if user_id is not None:
        user_ids = [user_id]
    else:
        user_ids = (await db.execute(select(Profile.user_id).distinct())).scalars().all()
    cutoff = _utcnow() - older_than
    processed = 0
    for current_user in user_ids:
        if processed >= budget:
            break
        while processed < budget:
            remaining = budget - processed
            batch_limit = min(POSTING_FIT_SWEEP_BATCH, remaining)
            stale_ids = (
                (
                    await db.execute(
                        select(PostingFit.posting_id)
                        .where(
                            PostingFit.user_id == current_user,
                            (
                                (PostingFit.fit_version != FIT_VERSION)
                                | (PostingFit.computed_at < cutoff)
                            ),
                        )
                        .limit(batch_limit)
                    )
                )
                .scalars()
                .all()
            )
            missing_ids: list[UUID] = []
            if len(stale_ids) < batch_limit:
                missing_ids = (
                    (
                        await db.execute(
                            select(JobPosting.id)
                            .where(
                                JobPosting.status.in_(["mapped", "new"]),
                                ~JobPosting.id.in_(
                                    select(PostingFit.posting_id).where(
                                        PostingFit.user_id == current_user
                                    )
                                ),
                            )
                            .order_by(JobPosting.posted_at.desc().nulls_last())
                            .limit(batch_limit - len(stale_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
            ids = [*stale_ids, *missing_ids]
            if not ids:
                break
            postings = (
                (
                    await db.execute(
                        select(JobPosting)
                        .where(JobPosting.id.in_(ids))
                        .order_by(JobPosting.posted_at.desc().nulls_last())
                    )
                )
                .scalars()
                .all()
            )
            await get_posting_fits_batch(db, current_user, list(postings), refresh=True)
            processed += len(postings)
            if progress is not None:
                percent = 10 + int(80 * min(processed, budget) / max(1, budget))
                await progress(percent, "refreshing posting fits")
            if len(postings) < batch_limit:
                break
    return {"rows": processed, "users": len(user_ids), "budget": budget}
