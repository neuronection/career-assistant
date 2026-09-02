"""Target mode service (Phase 27): the second front door.

Express onboarding resolves a job title to catalog archetypes (alias +
trigram match deterministic first, audited AI fallback, family-picker
deference), wires alert rules + sparse profile context in one call, and
aggregates the target dashboard. Progressive profiling nudges reuse
plan-23 custom runs with a global frequency cap and permanent dismissal.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ValidationError
from app.models.engagement_model import NotificationRule
from app.models.enums import (
    NotificationRuleKind,
    TagSource,
)
from app.models.job_model import Job, JobFamily, JobRelation, JobTag
from app.models.posting_model import JobPosting, PostingInteraction
from app.models.taxonomy_model import Skill
from app.models.user_model import Profile, UserInterest
from app.services.engagement_service import EngagementService
from app.services.experience_service import ExperienceService

NUDGE_COOLDOWN_DAYS = 3
NUDGE_TYPES = ("skills_micro_run", "interests_micro_run", "experience_micro_run")

TRIGRAM = re.compile(r"[a-z0-9]+")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _trigrams(text: str) -> set[str]:
    tokens = TRIGRAM.findall(text.lower())
    grams: set[str] = set()
    for token in tokens:
        padded = f"  {token} "
        grams.update(padded[i : i + 3] for i in range(len(padded) - 2))
    return grams


def _trigram_similarity(a: str, b: str) -> float:
    ga, gb = _trigrams(a), _trigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


# ----------------------------------------------------------------- resolve


async def resolve_query(db: AsyncSession, user_id, query: str) -> dict:
    """Typeahead resolve: deterministic alias/trigram first, audited AI as
    fallback; outputs are catalog keys only (never labels)."""
    query = (query or "").strip()
    if len(query) < 2:
        return {
            "query": query,
            "resolved_by": "empty",
            "families": [],
            "skill_keys": [],
            "archetypes": [],
        }

    lowered = query.lower()
    families = (
        (await db.execute(select(JobFamily).order_by(JobFamily.level, JobFamily.key)))
        .scalars()
        .all()
    )
    skills = (
        (await db.execute(select(Skill).where(Skill.status == "active")))
        .scalars()
        .all()
    )
    from app.services.job_service import JOB_LOAD_OPTIONS

    jobs = (
        (await db.execute(select(Job).options(*JOB_LOAD_OPTIONS).order_by(Job.title)))
        .scalars()
        .unique()
        .all()
    )

    # Deterministic pass: trigram + substring on titles, family-label boost
    # over the subtree, and skills.aliases mapping onto requiring jobs.
    family_boost: dict[UUID, float] = {}
    matched_skill_keys: set[str] = set()
    for family in families:
        if lowered in family.key.lower() or lowered in family.label.lower():
            for other in families:
                if other.path.startswith(family.path):
                    family_boost[other.id] = max(family_boost.get(other.id, 0.0), 0.25)
    for skill in skills:
        haystacks = [skill.key.lower(), skill.label.lower()]
        haystacks += [str(a).lower() for a in (skill.aliases or [])]
        if lowered in haystacks or any(
            lowered == h or (len(lowered) >= 3 and lowered in h) for h in haystacks
        ):
            matched_skill_keys.add(skill.key)

    def score_job(job: Job) -> float:
        score = _trigram_similarity(lowered, job.title)
        if score < 0.15 and lowered not in job.title.lower():
            score = 0.0
        if lowered in job.title.lower():
            score += 0.5
        if job.family_id in family_boost:
            score += family_boost[job.family_id]
        for link in job.skill_links or []:
            if link.skill.key in matched_skill_keys:
                score += 0.35
        return score

    ranked = sorted(
        ((score_job(job), job) for job in jobs),
        key=lambda pair: (-pair[0], pair[1].title),
    )
    ranked = [(score, job) for score, job in ranked if score > 0][:8]
    resolved_by = "deterministic"

    if not ranked:
        from app.ai.agents.target_resolver import resolve_target

        resolution = await resolve_target(
            db,
            user_id,
            query,
            [f.key for f in families],
            [s.key for s in skills],
        )
        if resolution.family_keys:
            keys = set(resolution.family_keys)
            ranked = [
                (1.0 - index * 0.05, job)
                for index, job in enumerate(jobs)
                if job.family is not None and job.family.key in keys
            ][:8]
            resolved_by = "ai"

    return {
        "query": query,
        "resolved_by": resolved_by,
        "families": [
            {"key": f.key, "label": f.label}
            for f in families
            if lowered in f.key.lower() or lowered in f.label.lower()
        ][:6],
        "skill_keys": sorted(matched_skill_keys)[:10],
        "archetypes": [
            {
                "code": job.code,
                "title": job.title,
                "family_key": job.family.key if job.family else "",
                "score": round(score, 3),
            }
            for score, job in ranked
        ],
    }


# ----------------------------------------------------------------- express


async def express_onboarding(
    db: AsyncSession,
    user_id: UUID,
    *,
    targets: list[str],
    location: Optional[str] = None,
    remote: Optional[bool] = None,
    stage: Optional[str] = None,
    min_fit: float = 7.0,
    max_per_day: int = 5,
) -> dict:
    """One call: resolve targets → sparse context → alert rules → target mode.

    `targets` are job codes or family keys (from the resolve endpoint or the
    family picker). Express interests land with source=express so a later
    full assessment merges cleanly (same tables, higher confidence)."""
    if not targets:
        raise ValidationError("Pick at least one target")

    families = (await db.execute(select(JobFamily))).scalars().all()
    family_by_key = {f.key: f for f in families}
    job_by_code = {j.code: j for j in (await db.execute(select(Job))).scalars().all()}

    target_family_ids: set[UUID] = set()
    target_family_keys: set[str] = set()
    target_labels: list[str] = []
    for target in targets:
        family = family_by_key.get(target)
        if family is not None:
            target_family_ids.add(family.id)
            target_family_keys.add(family.key)
            target_labels.append(family.label)
            for other in families:
                if other.path.startswith(family.path):
                    target_family_ids.add(other.id)
                    target_family_keys.add(other.key)
            continue
        job = job_by_code.get(target)
        if job is not None:
            target_family_ids.add(job.family_id)
            fam = next((f for f in families if f.id == job.family_id), None)
            if fam is not None:
                target_family_keys.add(fam.key)
                target_labels.append(job.title)
            continue
        raise ValidationError(f"Unknown target: {target}")

    if not target_family_ids:
        raise ValidationError("Targets resolved to no catalog families")

    profile = await _profile(db, user_id)
    basics = {**(profile.basics or {})}
    if location:
        basics["city"] = location
    if stage:
        basics["career_stage"] = stage
    profile.basics = basics
    if remote is not None:
        profile.work_preferences = {
            **(profile.work_preferences or {}),
            "remote_ok": bool(remote),
        }

    # Express interests: the dominant interest tags across target families'
    # jobs (source=express, weight 4) — enough signal for sane sparse fit.
    tag_rows = await db.execute(
        select(JobTag.interest_tag_id, func.count(JobTag.id))
        .where(
            JobTag.job_id.in_(
                select(Job.id).where(Job.family_id.in_(target_family_ids))
            )
        )
        .group_by(JobTag.interest_tag_id)
        .order_by(func.count(JobTag.id).desc())
        .limit(4)
    )
    express_tag_ids = [row[0] for row in tag_rows.all()]
    existing = {
        row.interest_tag_id: row
        for row in (
            await db.execute(
                select(UserInterest).where(UserInterest.user_id == user_id)
            )
        )
        .scalars()
        .all()
    }
    for tag_id in express_tag_ids:
        row = existing.get(tag_id)
        if row is None:
            db.add(
                UserInterest(
                    user_id=user_id,
                    interest_tag_id=tag_id,
                    weight=4,
                    source=TagSource.EXPRESS.value,
                )
            )
        elif row.source == TagSource.EXPRESS.value:
            row.weight = max(row.weight, 4)

    aspirations = [
        a for a in (profile.aspirations or []) if a.get("source") != "express"
    ]
    for label in target_labels[:3]:
        aspirations.append(
            {
                "label": label,
                "tag_keys": [],
                "notes": "express target",
                "source": "express",
            }
        )
    profile.aspirations = aspirations[:6]

    db.add(profile)
    await db.commit()

    # Alert rules scoped to the target families (plan 24 defaults, sane).
    engagement = EngagementService(db)
    await engagement.upsert_rule(
        user_id,
        NotificationRuleKind.NEW_POSTING_MATCH,
        {
            "min_fit": min_fit,
            "max_per_day": max_per_day,
            "family_keys": sorted(target_family_keys),
        },
        True,
    )
    await engagement.upsert_rule(
        user_id,
        NotificationRuleKind.FIT_THRESHOLD,
        {
            "min_fit": min_fit,
            "max_per_day": max_per_day,
            "family_keys": sorted(target_family_keys),
        },
        True,
    )

    return {
        "target_families": sorted(target_family_keys),
        "target_labels": target_labels,
        "interest_tags_written": len(express_tag_ids),
        "target_mode": True,
    }


async def _profile(db: AsyncSession, user_id: UUID) -> Profile:
    from app.services.deps import get_profile_for_user

    return await get_profile_for_user(db, user_id)


# ------------------------------------------------------------- completeness


async def completeness_ring(db: AsyncSession, user_id: UUID) -> dict:
    """What data would sharpen results — each segment links to a fix."""
    profile = await _profile(db, user_id)
    from sqlalchemy import func as _func

    from app.models.user_model import UserSkill

    skill_count = (
        await db.execute(
            select(_func.count(UserSkill.id)).where(UserSkill.user_id == user_id)
        )
    ).scalar() or 0
    interest_count = (
        await db.execute(
            select(_func.count(UserInterest.id)).where(UserInterest.user_id == user_id)
        )
    ).scalar() or 0
    basics = profile.basics or {}
    segments = [
        {
            "key": "skills",
            "label": "Your skills",
            "filled": skill_count >= 3,
            "hint": "Add your skills — alerts get far more precise",
            "href": "/profile",
        },
        {
            "key": "interests",
            "label": "Interests",
            "filled": interest_count >= 3,
            "hint": "Tell us what you enjoy — fit uses it directly",
            "href": "/profile",
        },
        {
            "key": "experience",
            "label": "Experience",
            "filled": await ExperienceService(db).has_items(user_id),
            "hint": "Add projects or jobs — evidence beats guesses",
            "href": "/profile",
        },
        {
            "key": "location",
            "label": "Location & remote",
            "filled": bool(basics.get("city")),
            "hint": "Where are you? Postings get distance-aware",
            "href": "/profile",
        },
        {
            "key": "work_style",
            "label": "Work style",
            "filled": bool((profile.work_preferences or {}).get("focus_areas")),
            "hint": "A 5-minute micro-run sharpens alerts",
            "href": "/assessment",
        },
        {
            "key": "constraints",
            "label": "Constraints",
            "filled": bool(
                (profile.constraints or {}).get("max_education_years")
                or (profile.constraints or {}).get("physical_conditions")
            ),
            "hint": "Hard limits keep bad matches out",
            "href": "/profile",
        },
    ]
    filled = sum(1 for s in segments if s["filled"])
    return {
        "percent": round(filled / len(segments) * 100),
        "segments": segments,
    }


# ----------------------------------------------------------------- nudges


async def get_nudges(db: AsyncSession, user_id: UUID) -> list[dict]:
    """Contextual micro-run nudges: global cooldown, permanent dismissal."""
    profile = await _profile(db, user_id)
    store = (profile.preferences or {}).get("nudges") or {}
    dismissed = set(store.get("dismissed") or [])
    last_fired = store.get("last_fired") or {}
    now = _utcnow()
    from sqlalchemy import func as _func

    from app.models.user_model import UserSkill

    skill_count = (
        await db.execute(
            select(_func.count(UserSkill.id)).where(UserSkill.user_id == user_id)
        )
    ).scalar() or 0

    candidates = {
        "skills_micro_run": (
            skill_count < 3,
            "Answer 3 quick questions about your skills — alerts get sharper",
        ),
        "interests_micro_run": (
            not (profile.aspirations or []),
            "Tell us what you're aiming for — suggestions get closer",
        ),
        "experience_micro_run": (
            not await ExperienceService(db).has_items(user_id),
            "Add one project or job — evidence beats guesses",
        ),
    }
    nudges: list[dict] = []
    for nudge_type, (applicable, message) in candidates.items():
        if not applicable or nudge_type in dismissed:
            continue
        fired_at = last_fired.get(nudge_type)
        if fired_at:
            fired = datetime.fromisoformat(fired_at)
            if now - fired < timedelta(days=NUDGE_COOLDOWN_DAYS):
                continue
        nudges.append({"type": nudge_type, "message": message})
    # Record the serve as a firing (global frequency cap per type).
    if nudges:
        fired = dict(last_fired)
        for nudge in nudges:
            fired[nudge["type"]] = now.isoformat()
        profile.preferences = {
            **(profile.preferences or {}),
            "nudges": {**store, "last_fired": fired},
        }
        db.add(profile)
        await db.commit()
    return nudges


async def dismiss_nudge(db: AsyncSession, user_id: UUID, nudge_type: str) -> dict:
    if nudge_type not in NUDGE_TYPES:
        raise ValidationError(f"Unknown nudge type: {nudge_type}")
    profile = await _profile(db, user_id)
    store = (profile.preferences or {}).get("nudges") or {}
    dismissed = set(store.get("dismissed") or [])
    dismissed.add(nudge_type)
    profile.preferences = {
        **(profile.preferences or {}),
        "nudges": {**store, "dismissed": sorted(dismissed)},
    }
    db.add(profile)
    await db.commit()
    return {"dismissed": nudge_type, "forever": True}


# -------------------------------------------------------- target dashboard


async def target_dashboard(db: AsyncSession, user_id: UUID) -> dict:
    """The target-mode dashboard aggregate: open jobs, adjacent targets,
    market snapshot, nudges (plan 27)."""
    from app.services.experience_service import ExperienceService
    from app.services.stages_service import effective_stage

    profile = await _profile(db, user_id)
    _stage, _source = effective_stage(
        profile.basics or {}, await ExperienceService(db).stage_dicts(user_id)
    )

    rules = (
        (
            await db.execute(
                select(NotificationRule).where(
                    NotificationRule.user_id == user_id,
                    NotificationRule.kind
                    == NotificationRuleKind.NEW_POSTING_MATCH.value,
                    NotificationRule.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    family_keys: set[str] = set()
    for rule in rules:
        family_keys.update(rule.params.get("family_keys") or [])

    postings_rows = (
        (
            await db.execute(
                select(JobPosting)
                .options(selectinload(JobPosting.catalog_job).selectinload(Job.family))
                .where(
                    JobPosting.status.in_(["mapped", "new"]),
                    JobPosting.catalog_job_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )

    open_postings: list[JobPosting] = []
    for posting in postings_rows:
        if not family_keys:
            break
        job = posting.catalog_job
        if job is None:
            continue
        fam = job.family
        if fam is not None and set(fam.path.split("/")) & family_keys:
            open_postings.append(posting)

    interaction_rows = await db.execute(
        select(PostingInteraction).where(PostingInteraction.user_id == user_id)
    )
    seen_ids = {
        i.posting_id for i in interaction_rows.scalars().all() if i.seen_at is not None
    }

    salary_mins = [
        float(p.salary_min) for p in open_postings if p.salary_min is not None
    ]
    salary_maxs = [
        float(p.salary_max) for p in open_postings if p.salary_max is not None
    ]
    employer_counts: dict[str, int] = {}
    for p in open_postings:
        if p.org:
            employer_counts[p.org] = employer_counts.get(p.org, 0) + 1
    top_employers = [
        {"org": org, "count": count}
        for org, count in sorted(employer_counts.items(), key=lambda kv: -kv[1])[:5]
    ]

    # Adjacent targets: families reachable via similar_to/specialises_into
    # edges from jobs inside the target families.
    adjacent: dict[str, dict] = {}
    if family_keys:
        target_job_ids = [p.catalog_job_id for p in open_postings]
        if target_job_ids:
            edges = (
                (
                    await db.execute(
                        select(JobRelation).where(
                            or_(
                                JobRelation.from_job_id.in_(target_job_ids),
                                JobRelation.to_job_id.in_(target_job_ids),
                            ),
                            JobRelation.relation_type.in_(
                                ["similar_to", "specialises_into"]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            from app.services.job_service import JOB_LOAD_OPTIONS

            for edge in edges[:50]:
                other_id = (
                    edge.to_job_id
                    if edge.from_job_id in target_job_ids
                    else edge.from_job_id
                )
                job = (
                    (
                        await db.execute(
                            select(Job)
                            .options(*JOB_LOAD_OPTIONS)
                            .where(Job.id == other_id)
                        )
                    )
                    .scalars()
                    .first()
                )
                if job is None or job.family is None:
                    continue
                if set(job.family.path.split("/")) & family_keys:
                    continue
                adjacent.setdefault(
                    job.family.key,
                    {
                        "family_key": job.family.key,
                        "label": job.family.label,
                        "sample": job.title,
                    },
                )

    nudges = await get_nudges(db, user_id)
    ring = await completeness_ring(db, user_id)

    return {
        "families": sorted(family_keys),
        "open_postings": {
            "total": len(open_postings),
            "unseen": sum(1 for p in open_postings if p.id not in seen_ids),
            "salary_band": {
                "min": min(salary_mins) if salary_mins else None,
                "max": max(salary_maxs) if salary_maxs else None,
            },
            "top_employers": top_employers,
        },
        "adjacent_targets": list(adjacent.values())[:6],
        "nudges": nudges,
        "completeness": ring,
    }
