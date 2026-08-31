"""Skill ontology: browse, user skills, gap report."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.schemas.skills import SkillGapReport, SkillJobsOut, UserSkillsIn, UserSkillOut
from app.services.deps import get_current_user
from app.services.job_service import JobService
from app.services.skills_service import SkillService

router = APIRouter(tags=["skills"])


def _skill_out(skill, *, jobs=None, children_keys=None) -> SkillJobsOut:
    return SkillJobsOut(
        id=skill.id,
        key=skill.key,
        label=skill.label,
        category=skill.category,
        description=skill.description,
        parent_id=skill.parent_id,
        level_anchors=skill.level_anchors or [],
        aliases=skill.aliases or [],
        status=skill.status,
        children_keys=children_keys or [],
        jobs=jobs or [],
    )


@router.get("/skills")
async def list_skills(
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Browse the active ontology (flat; parent_id gives the tree shape)."""
    rows = await SkillService(db).list_skills(q=q, category=category)
    return [
        {
            "id": s.id,
            "key": s.key,
            "label": s.label,
            "category": s.category,
            "description": s.description,
            "parent_id": s.parent_id,
            "level_anchors": s.level_anchors or [],
        }
        for s in rows
    ]


@router.get("/skills/{key}", response_model=SkillJobsOut)
async def get_skill(
    key: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SkillJobsOut:
    """One skill with subskills and the published jobs asking for it."""
    service = SkillService(db)
    try:
        skill = await service.require_skill(key)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    children = [s.key for s in await service.list_skills() if s.parent_id == skill.id]
    links = await service.jobs_for_skill(skill)
    jobs = [
        {
            "skill_id": link.skill_id,
            "key": skill.key,
            "label": skill.label,
            "required_level": link.required_level,
            "importance": link.importance,
            "rationale": link.rationale,
        }
        for link in links
    ]
    return _skill_out(skill, jobs=jobs, children_keys=children)


@router.get("/me/skills", response_model=list[UserSkillOut])
async def my_skills(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[UserSkillOut]:
    """The caller's skills across every source, strongest first."""
    rows = await SkillService(db).user_skills(user.id)
    return [_user_skill_out(row) for row in rows]


@router.put("/me/skills", response_model=list[UserSkillOut])
async def put_my_skills(
    data: UserSkillsIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserSkillOut]:
    """Bulk-upsert the caller's self-reported skills (other sources kept).

    Unknown keys auto-create `proposed` skills (origin=user) — self-reporting
    never hard-fails; promotion to active is an admin decision.
    """
    rows = await SkillService(db).put_user_skills(
        user.id, [item.model_dump() for item in data.skills]
    )
    return [_user_skill_out(row) for row in rows]


@router.get("/me/skills/gaps", response_model=SkillGapReport)
async def my_skill_gaps(
    job_id: str = Query(...),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillGapReport:
    """Per-skill required-vs-current report for one job."""
    try:
        job = await JobService(db).require_job(job_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    report = await SkillService(db).gaps(user.id, job)
    return SkillGapReport.model_validate(report)


def _user_skill_out(row) -> UserSkillOut:
    skill = row.skill
    return UserSkillOut(
        skill_id=skill.id,
        key=skill.key,
        label=skill.label,
        category=skill.category,
        level=row.level,
        source=row.source,
        confidence=row.confidence,
        level_anchors=skill.level_anchors or [],
    )
