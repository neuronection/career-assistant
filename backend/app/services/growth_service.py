"""Growth toolkit service (Phase 28): roadmaps, near-miss radar, market
snapshots, check-ins. Everything is deterministic over shipped layers
(21 skills/paths, 22 fit breakdown, 25 stages, 26 postings) — no new
scoring concepts, no AI in the hot path."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, ValidationError
from app.models.enums import (
    GrowthPlanStatus,
    GrowthStepKind,
    GrowthStepStatus,
    JobSkillImportance,
)
from app.models.growth_model import GrowthPlan, GrowthPlanStep, LearningResource
from app.models.job_model import Job, JobSkill
from app.models.matching_model import MatchInsight
from app.models.posting_model import JobPosting
from app.models.schedule_model import Schedule
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill

# Radar band + deficit limits (plan 28 §2, deterministic, no AI).
RADAR_MIN_FIT = 5.5
RADAR_MAX_FIT = 7.5
RADAR_MAX_CORE_DEFICITS = 3
RADAR_MAX_LEVEL_GAP = 3

SNAPSHOT_MIN_SAMPLE = 5
DEFAULT_CHECKIN_DAYS = 90


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _percentile(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    if len(values) < SNAPSHOT_MIN_SAMPLE:
        return None
    sorted_values = sorted(values)
    index = min(len(sorted_values) - 1, max(0, int(len(sorted_values) * pct)))
    return sorted_values[index]


# ---------------------------------------------------------------- radar


async def near_miss_radar(
    db: AsyncSession, user_id: UUID, limit: int = 8
) -> list[dict]:
    """Jobs in the 5.5–7.5 fit band missing few discrete skills.

    Deficits: core/important job skills where the user is missing or below
    required by ≤ RADAR_MAX_LEVEL_GAP levels; at most RADAR_MAX_CORE_DEFICITS
    of them. Deterministic over fit_breakdown + job_skills — no AI."""
    rows = (
        await db.execute(
            select(MatchInsight, Job)
            .join(Job, Job.id == MatchInsight.job_id)
            .options(selectinload(Job.family))
            .where(
                MatchInsight.user_id == user_id,
                MatchInsight.fit_score >= RADAR_MIN_FIT,
                MatchInsight.fit_score <= RADAR_MAX_FIT,
                Job.status == "published",
            )
            .order_by(MatchInsight.fit_score.desc())
            .limit(80)
        )
    ).all()
    skill_levels = {
        row.skill_id: row.level
        for row in (
            await db.execute(select(UserSkill).where(UserSkill.user_id == user_id))
        )
        .scalars()
        .all()
    }
    radar: list[dict] = []
    for insight, job in rows:
        gates = (insight.fit_breakdown or {}).get("gates") or []
        if gates:
            continue
        links = (
            await db.execute(
                select(JobSkill, Skill)
                .join(Skill, Skill.id == JobSkill.skill_id)
                .where(JobSkill.job_id == job.id)
            )
        ).all()
        deficits = []
        for link, skill in links:
            current = skill_levels.get(link.skill_id)
            level = int(current) if current is not None else 0
            gap = link.required_level - level
            if gap <= 0:
                continue
            if link.importance == JobSkillImportance.BONUS.value:
                continue
            if gap > RADAR_MAX_LEVEL_GAP:
                deficits = []
                break
            deficits.append(
                {
                    "skill_id": str(link.skill_id),
                    "key": skill.key,
                    "label": skill.label,
                    "current_level": level,
                    "required_level": link.required_level,
                    "delta": gap,
                    "importance": link.importance,
                }
            )
        core_deficits = [d for d in deficits if d["importance"] == "core"]
        if not deficits or len(core_deficits) > RADAR_MAX_CORE_DEFICITS:
            continue
        radar.append(
            {
                "job_id": str(job.id),
                "code": job.code,
                "title": job.title,
                "family_key": job.family.key if job.family else "",
                "fit_score": float(insight.fit_score),
                "deficits": sorted(deficits, key=lambda d: (-d["delta"], d["label"]))[
                    :4
                ],
                "headline": (
                    f"{len(deficits)} skill{'s' if len(deficits) != 1 else ''} away"
                    f" from {job.title}: "
                    + ", ".join(
                        f"{d['label']} +{d['delta']}"
                        for d in sorted(deficits, key=lambda d: -d["delta"])[:3]
                    )
                ),
            }
        )
        if len(radar) >= limit:
            break
    return radar


# ------------------------------------------------------------- roadmaps


async def create_plan(db: AsyncSession, user_id: UUID, target_job_id: UUID) -> dict:
    """Generate a roadmap for the target job: curated path steps + skill
    gaps → proposed steps (user-editable afterwards)."""
    from app.services.job_service import JOB_LOAD_OPTIONS

    job = (
        (
            await db.execute(
                select(Job).options(*JOB_LOAD_OPTIONS).where(Job.id == target_job_id)
            )
        )
        .scalars()
        .unique()
        .first()
    )
    if job is None:
        raise NotFoundError("Target job not found")
    existing = (
        (
            await db.execute(
                select(GrowthPlan).where(
                    GrowthPlan.user_id == user_id,
                    GrowthPlan.target_job_id == target_job_id,
                    GrowthPlan.status == GrowthPlanStatus.ACTIVE.value,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        raise ValidationError("An active plan for this job already exists")

    plan = GrowthPlan(user_id=user_id, target_job_id=target_job_id)
    db.add(plan)
    await db.flush()

    from app.services.skills_service import SkillService

    gap_report = await SkillService(db).gaps(user_id, job)
    skill_gaps = [
        gap for gap in gap_report["gaps"] if gap["delta"] is None or gap["delta"] < 0
    ]
    path_hints = await SkillService(db)._path_hints(job.id)

    position = 0
    for gap in skill_gaps[:6]:
        db.add(
            GrowthPlanStep(
                plan_id=plan.id,
                position=position,
                kind=GrowthStepKind.SKILL.value,
                skill_id=gap["skill_id"],
                label=f"Raise {gap['label']} to level {gap['required_level']}",
                target_level=gap["required_level"],
                status=GrowthStepStatus.TODO.value,
            )
        )
        position += 1
    if not skill_gaps:
        for hint_skill_id, hint in list(path_hints.items())[:3]:
            db.add(
                GrowthPlanStep(
                    plan_id=plan.id,
                    position=position,
                    kind=GrowthStepKind.CERTIFICATION.value,
                    skill_id=hint_skill_id,
                    label=hint,
                    status=GrowthStepStatus.TODO.value,
                )
            )
            position += 1
    await db.commit()
    return await plan_out(db, plan)


async def plan_out(db: AsyncSession, plan: GrowthPlan) -> dict:
    job = (
        (await db.execute(select(Job).where(Job.id == plan.target_job_id)))
        .scalars()
        .first()
    )
    steps = (
        (
            await db.execute(
                select(GrowthPlanStep)
                .where(GrowthPlanStep.plan_id == plan.id)
                .order_by(GrowthPlanStep.position)
            )
        )
        .scalars()
        .all()
    )
    skill_ids = {step.skill_id for step in steps if step.skill_id}
    resources: dict[UUID, list] = {}
    if skill_ids:
        rows = (
            (
                await db.execute(
                    select(LearningResource).where(
                        LearningResource.skill_id.in_(skill_ids),
                        LearningResource.status == "published",
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            resources.setdefault(row.skill_id, []).append(
                {
                    "id": str(row.id),
                    "kind": row.kind,
                    "title": row.title,
                    "provider": row.provider,
                    "url": row.url,
                    "cost": row.cost,
                }
            )
    return {
        "id": str(plan.id),
        "status": plan.status,
        "target_job": {
            "id": str(plan.target_job_id),
            "title": job.title if job else "",
            "code": job.code if job else "",
        },
        "completed_at": plan.completed_at,
        "steps": [
            {
                "id": str(step.id),
                "position": step.position,
                "kind": step.kind,
                "label": step.label,
                "skill_id": str(step.skill_id) if step.skill_id else None,
                "target_level": step.target_level,
                "status": step.status,
                "completed_level": step.completed_level,
                "resources": resources.get(step.skill_id, []) if step.skill_id else [],
            }
            for step in steps
        ],
    }


async def list_plans(db: AsyncSession, user_id: UUID) -> list[dict]:
    plans = (
        (
            await db.execute(
                select(GrowthPlan)
                .where(GrowthPlan.user_id == user_id)
                .order_by(GrowthPlan.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await plan_out(db, plan) for plan in plans]


async def patch_step(
    db: AsyncSession,
    user_id: UUID,
    step_id: UUID,
    *,
    status: Optional[str] = None,
    position: Optional[int] = None,
    completed_level: Optional[int] = None,
) -> dict:
    """Edit one step. Completing a skill step self-reports the level,
    upserts user_skills (23-style conflict awareness) and re-fits (22)."""
    step = (
        (await db.execute(select(GrowthPlanStep).where(GrowthPlanStep.id == step_id)))
        .scalars()
        .first()
    )
    if step is None:
        raise NotFoundError("Step not found")
    plan = (
        (await db.execute(select(GrowthPlan).where(GrowthPlan.id == step.plan_id)))
        .scalars()
        .first()
    )
    if plan is None or plan.user_id != user_id:
        raise NotFoundError("Step not found")

    conflicts: list[dict] = []
    if status is not None:
        if status not in {s.value for s in GrowthStepStatus}:
            raise ValidationError(f"Invalid status: {status}")
        step.status = status
    if position is not None:
        step.position = position
    if completed_level is not None:
        if not 1 <= completed_level <= 10:
            raise ValidationError("completed_level must be 1–10")
        step.completed_level = completed_level

    refit_jobs = 0
    if step.status == GrowthStepStatus.DONE.value and step.skill_id is not None:
        level = completed_level or step.target_level or step.completed_level
        if level is not None:
            from app.models.enums import UserSkillSource

            existing = (
                (
                    await db.execute(
                        select(UserSkill).where(
                            UserSkill.user_id == user_id,
                            UserSkill.skill_id == step.skill_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None and abs(existing.level - int(level)) > 2:
                conflicts.append(
                    {
                        "skill_id": str(step.skill_id),
                        "self_level": existing.level,
                        "reported_level": int(level),
                    }
                )
            else:
                if existing is None:
                    db.add(
                        UserSkill(
                            user_id=user_id,
                            skill_id=step.skill_id,
                            level=int(level),
                            source=UserSkillSource.SELF_REPORT.value,
                        )
                    )
                else:
                    existing.level = int(level)
                    existing.source = UserSkillSource.SELF_REPORT.value
                from app.services.fit.service import FitService

                refit_jobs = await FitService(db).refit_user(user_id)
    if plan.status == GrowthPlanStatus.ACTIVE.value:
        remaining = (
            await db.execute(
                select(func.count(GrowthPlanStep.id)).where(
                    GrowthPlanStep.plan_id == plan.id,
                    GrowthPlanStep.status.in_(["todo", "doing"]),
                )
            )
        ).scalar() or 0
        total = (
            await db.execute(
                select(func.count(GrowthPlanStep.id)).where(
                    GrowthPlanStep.plan_id == plan.id
                )
            )
        ).scalar() or 0
        if total > 0 and remaining == 0:
            plan.status = GrowthPlanStatus.COMPLETED.value
            plan.completed_at = _utcnow()
    db.add(step)
    db.add(plan)
    await db.commit()
    await db.refresh(step)
    return {
        "step": {
            "id": str(step.id),
            "position": step.position,
            "status": step.status,
            "completed_level": step.completed_level,
        },
        "conflicts": conflicts,
        "refitted": refit_jobs,
    }


# --------------------------------------------------------- market snapshot


async def market_snapshot(
    db: AsyncSession,
    *,
    family_key: Optional[str] = None,
    job_id: Optional[UUID] = None,
) -> dict:
    """Aggregates over postings — analytics only, never a fit input (22)."""

    query = (
        select(JobPosting)
        .options(selectinload(JobPosting.catalog_job).selectinload(Job.family))
        .where(
            JobPosting.status.in_(["mapped", "new"]),
            JobPosting.catalog_job_id.is_not(None),
        )
        .order_by(JobPosting.posted_at.desc())
        .limit(1000)
    )
    if job_id is not None:
        query = query.where(JobPosting.catalog_job_id == job_id)
    postings = (await db.execute(query)).scalars().unique().all()

    if family_key is not None:
        postings = [
            p
            for p in postings
            if p.catalog_job is not None
            and p.catalog_job.family is not None
            and family_key in p.catalog_job.family.path.split("/")
        ]

    sample = len(postings)
    salaries = [
        float(v)
        for p in postings
        for v in (p.salary_min, p.salary_max)
        if v is not None and float(v) > 0
    ]

    months: dict[str, int] = {}
    for p in postings:
        stamp = p.posted_at or p.created_at
        key = stamp.strftime("%Y-%m")
        months[key] = months.get(key, 0) + 1

    employers: dict[str, int] = {}
    for p in postings:
        if p.org:
            employers[p.org] = employers.get(p.org, 0) + 1

    from app.models.posting_model import PostingSkill

    skill_rows = (
        (
            await db.execute(
                select(Skill.key, func.count(PostingSkill.id))
                .join(PostingSkill, PostingSkill.skill_id == Skill.id)
                .where(PostingSkill.posting_id.in_([p.id for p in postings]))
                .group_by(Skill.key)
                .order_by(func.count(PostingSkill.id).desc())
                .limit(8)
            )
        ).all()
        if postings
        else []
    )

    thin = sample < SNAPSHOT_MIN_SAMPLE
    return {
        "sample_size": sample,
        "thin_sample": thin,
        "months": [{"month": key, "postings": months[key]} for key in sorted(months)][
            -12:
        ],
        "salary_band": None
        if thin
        else {
            "p25": _percentile(salaries, 0.25),
            "p75": _percentile(salaries, 0.75),
        },
        "top_employers": [
            {"org": org, "count": count}
            for org, count in sorted(employers.items(), key=lambda kv: -kv[1])[:5]
        ],
        "top_skills": [{"key": key, "count": count} for key, count in skill_rows],
    }


# --------------------------------------------------------------- check-ins


async def checkin_status(db: AsyncSession, user_id: UUID) -> dict:
    """Quarterly check-in state — owned by the plan-29 scheduler.

    The schedule is provisioned lazily; `due` is its next_run_at."""
    from app.models.enums import ScheduleKind
    from app.services.scheduler.runner import SchedulerService

    service = SchedulerService(db)
    await service.ensure_user_schedules(user_id)
    rows = await db.execute(
        select(Schedule).where(
            Schedule.owner_user_id == user_id,
            Schedule.kind == ScheduleKind.USER_CHECKIN.value,
        )
    )
    schedule = rows.scalars().first()
    if schedule is None or schedule.next_run_at is None:
        return {"due": False, "next_at": None, "last_at": None}
    return {
        "due": schedule.next_run_at <= _utcnow(),
        "next_at": schedule.next_run_at.isoformat(),
        "last_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
    }


async def complete_checkin(
    db: AsyncSession,
    user_id: UUID,
    *,
    stage: Optional[str] = None,
    skills: Optional[dict[str, int]] = None,
    skipped: bool = False,
) -> dict:
    """5-minute flow: confirm stage, micro self-report with conflict
    surfacing (23 reconciliation), or skip (+90 days)."""
    from app.services.deps import get_profile_for_user
    from app.services.stages_service import effective_stage

    profile = await get_profile_for_user(db, user_id)
    now = _utcnow()
    conflicts: list[dict] = []
    applied = 0

    if not skipped:
        if stage:
            basics = {**(profile.basics or {}), "career_stage": stage}
            profile.basics = basics
        if skills:
            resolved = await _resolve_skills(db, list(skills.keys()))
            existing = {
                row.skill_id: row
                for row in (
                    await db.execute(
                        select(UserSkill).where(UserSkill.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            }
            for key, level in skills.items():
                skill_id = resolved.get(key)
                if skill_id is None or not 1 <= int(level) <= 10:
                    continue
                row = existing.get(skill_id)
                if row is not None and abs(row.level - int(level)) > 2:
                    conflicts.append(
                        {
                            "key": key,
                            "self_level": row.level,
                            "reported_level": int(level),
                        }
                    )
                    continue
                applied += 1
                if row is None:
                    db.add(
                        UserSkill(
                            user_id=user_id,
                            skill_id=skill_id,
                            level=int(level),
                            source="self_report",
                        )
                    )
                else:
                    row.level = int(level)
                    row.source = "self_report"
        if applied:
            from app.services.fit.service import FitService

            await FitService(db).refit_user(user_id)
        current_stage, _source = effective_stage(
            profile.basics or {}, profile.experience or []
        )
    else:
        current_stage, _source = effective_stage(
            profile.basics or {}, profile.experience or []
        )

    from app.models.enums import ScheduleKind
    from app.services.scheduler import triggers as trigger_registry
    from app.services.scheduler.runner import SchedulerService

    service = SchedulerService(db)
    await service.ensure_user_schedules(user_id)
    rows = await db.execute(
        select(Schedule).where(
            Schedule.owner_user_id == user_id,
            Schedule.kind == ScheduleKind.USER_CHECKIN.value,
        )
    )
    schedule = rows.scalars().first()
    next_dt = now + timedelta(days=DEFAULT_CHECKIN_DAYS)
    if schedule is not None:
        schedule.last_run_at = now
        schedule.next_run_at = trigger_registry.next_after(schedule.trigger, now)
        schedule.last_status = "ok"
        schedule.consecutive_failures = 0
        next_dt = schedule.next_run_at
    db.add(profile)
    await db.commit()
    return {
        "skipped": skipped,
        "applied_skills": applied,
        "conflicts": conflicts,
        "stage": current_stage.value,
        "next_at": next_dt.isoformat() if next_dt else None,
    }


async def _resolve_skills(db: AsyncSession, keys: list[str]) -> dict[str, UUID]:
    rows = (await db.execute(select(Skill).where(Skill.key.in_(keys)))).scalars().all()
    return {s.key: s.id for s in rows}
