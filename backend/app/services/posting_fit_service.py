"""Per-posting match score (Phase 32): deterministic dimensions over
extracted posting data, cached in `posting_fits` with an inputs-hash
staleness flag (plan-16 pattern). Unextracted postings fall back to the
mapped archetype's fit with a visible estimate note — never silently
blended. Weights reuse plan 22's user sliders, dimensions mapped 1:1
(prereqs→education, location_remote→location, seniority_stage→
experience); freshness carries a fixed weight (interests has no posting
analogue and stays unused)."""

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EducationLevel, EducationLevelOrder
from app.models.enums import PostingSkillPriority
from app.models.posting_model import JobPosting, PostingFit, PostingSkill
from app.models.user_model import UserSkill

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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload or {}, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _user_skills(db: AsyncSession, user_id: UUID) -> dict[UUID, int]:
    rows = await db.execute(
        select(UserSkill.skill_id, UserSkill.level).where(UserSkill.user_id == user_id)
    )
    return {skill_id: level for skill_id, level in rows.all()}


def _skills_dimension(links: list[PostingSkill], user_levels: dict[UUID, int]) -> dict:
    """`min(user, required) / required`, priority-weighted; fully-unmet
    must-haves cap the score (the plan-22 curve, sharpened by levels)."""
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
            details.append(
                f"education {'meets' if met else 'below'} requirement ({level})"
            )
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
    """The plan-26 delta semantics as a standalone 0–10 dimension."""
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
    from app.services.fit.service import FitService
    from app.services.stages_service import stage_for_user

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
) -> dict:
    return {
        "user_id": str(user_id),
        "posting_id": str(posting.id),
        "extract_version": posting.extract_version,
        "posted_at": posting.posted_at.isoformat() if posting.posted_at else None,
        "user_skills": {str(k): v for k, v in sorted(user_levels.items())},
        "weights": weights,
        "stage": stage_value,
    }


async def compute_posting_fit(
    db: AsyncSession, user_id: UUID, posting: JobPosting, context: Optional[dict] = None
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
    # cheap check in get_posting_fit hashes exactly this.
    inputs = _inputs_payload(user_id, posting, user_levels, weights, stage.value)
    inputs_hash = _canonical_hash(inputs)

    if not extracted:
        from app.services.postings_service import posting_fit

        estimate = await posting_fit(db, user_id, posting)
        return {
            "score": round(float(estimate), 2),
            "breakdown": {
                "archetype_estimate": {
                    "score": round(float(estimate), 2),
                    "detail": (
                        "archetype estimate — deep extraction has not run "
                        "for this posting yet"
                    ),
                    "weight": 5,
                }
            },
            "extracted": False,
            "estimate": True,
            "inputs_hash": inputs_hash,
        }

    links = (
        (
            await db.execute(
                select(PostingSkill).where(PostingSkill.posting_id == posting.id)
            )
        )
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
        sum(entry["score"] * entry["weight"] for entry in breakdown.values())
        / total_weight
        if total_weight
        else 7.0
    )
    return {
        "score": round(float(min(10.0, max(0.0, score))), 2),
        "breakdown": breakdown,
        "extracted": True,
        "estimate": False,
        "inputs_hash": inputs_hash,
    }


async def get_posting_fit(
    db: AsyncSession, user_id: UUID, posting: JobPosting, *, refresh: bool = False
) -> dict:
    """Cached read: cheap inputs load → hash → cached row is a hit when
    the hash matches; stale (or missing) rows recompute and persist."""
    context = await _load_context(db, user_id)
    inputs = _inputs_payload(
        user_id,
        posting,
        context["user_levels"],
        context["weights"],
        context["stage"].value,
    )
    inputs_hash = _canonical_hash(inputs)

    rows = await db.execute(
        select(PostingFit).where(
            PostingFit.user_id == user_id, PostingFit.posting_id == posting.id
        )
    )
    cached = rows.scalars().first()
    if cached is not None and not refresh and cached.inputs_hash == inputs_hash:
        return {
            "score": round(float(cached.score), 2),
            "breakdown": cached.breakdown or {},
            "extracted": cached.breakdown.get("archetype_estimate") is None
            if cached.breakdown
            else False,
            "estimate": cached.breakdown is not None
            and "archetype_estimate" in cached.breakdown,
            "inputs_hash": cached.inputs_hash,
        }

    computed = await compute_posting_fit(db, user_id, posting, context=context)
    if cached is None:
        cached = PostingFit(user_id=user_id, posting_id=posting.id)
        db.add(cached)
    cached.score = Decimal(str(computed["score"]))
    cached.breakdown = computed["breakdown"]
    cached.inputs_hash = computed["inputs_hash"]
    await db.flush()
    return computed


async def get_posting_fits_batch(
    db: AsyncSession, user_id: UUID, postings: list[JobPosting]
) -> dict[UUID, dict]:
    """Listing-time batch: compute with one shared context and persist
    nothing (the cache is a view-time artifact; a listing must never
    write hundreds of rows)."""
    if not postings:
        return {}
    context = await _load_context(db, user_id)
    result: dict[UUID, dict] = {}
    for posting in postings:
        result[posting.id] = await compute_posting_fit(
            db, user_id, posting, context=context
        )
    return result
