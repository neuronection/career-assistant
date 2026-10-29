"""Skill ontology: browse, user skills, gap report."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.models.taxonomy_model import SkillChange
from app.schemas.skills import (
    SkillChangeOut,
    SkillGapReport,
    SkillHistoryOut,
    SkillJobsOut,
    UserSkillOut,
    UserSkillPatchIn,
    UserSkillsIn,
)
from app.services.catalog.job_service import JobService
from app.services.catalog.skills_service import SkillService
from app.services.deps import get_current_user

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
    from app.models.enums import LabelEntityKind
    from app.services.catalog.label_overlay_service import LabelOverlayService
    from app.services.locale_service import effective_locale

    rows = await SkillService(db).list_skills(q=q, category=category)
    overlays = await LabelOverlayService(db).approved_map(
        LabelEntityKind.SKILL,
        [skill.id for skill in rows],
        await effective_locale(db, user),
    )
    return [
        {
            "id": skill.id,
            "key": skill.key,
            "label": overlays.get(skill.id, {}).get("label") or skill.label,
            "category": skill.category,
            "description": overlays.get(skill.id, {}).get("description") or skill.description,
            "parent_id": skill.parent_id,
            "level_anchors": skill.level_anchors or [],
        }
        for skill in rows
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
    from app.models.enums import LabelEntityKind
    from app.services.catalog.label_overlay_service import LabelOverlayService
    from app.services.locale_service import effective_locale

    locale = await effective_locale(db, user)
    overlay = (
        await LabelOverlayService(db).approved_map(LabelEntityKind.SKILL, [skill.id], locale)
    ).get(skill.id, {})
    localized_label = overlay.get("label") or skill.label
    localized_description = overlay.get("description") or skill.description
    children = [s.key for s in await service.list_skills() if s.parent_id == skill.id]
    links = await service.jobs_for_skill(skill)
    jobs = [
        {
            "skill_id": link.skill_id,
            "key": skill.key,
            "label": localized_label,
            "required_level": link.required_level,
            "importance": link.importance,
            "rationale": link.rationale,
        }
        for link in links
    ]
    from app.schemas.job import JobSkillOut

    return SkillJobsOut(
        id=skill.id,
        key=skill.key,
        label=localized_label,
        category=skill.category,
        description=localized_description,
        parent_id=skill.parent_id,
        level_anchors=skill.level_anchors or [],
        aliases=skill.aliases or [],
        status=skill.status,
        children_keys=children,
        jobs=[JobSkillOut.model_validate(row) for row in jobs],
    )


@router.get("/skills/{key}/history", response_model=SkillHistoryOut)
async def skill_history(
    key: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> SkillHistoryOut:
    """One skill's lifecycle journal, newest first (plan 148) — event
    kind, actor role and the capped detail per row. User-visible for
    every signed-in user, exactly like the postings journal read."""
    service = SkillService(db)
    try:
        skill = await service.require_skill(key)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    total = (
        await db.execute(
            select(func.count()).select_from(SkillChange).where(SkillChange.skill_id == skill.id)
        )
    ).scalar_one()
    rows = await db.execute(
        select(SkillChange)
        .where(SkillChange.skill_id == skill.id)
        .order_by(SkillChange.occurred_at.desc(), SkillChange.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        SkillChangeOut(
            id=row.id,
            occurred_at=row.occurred_at,
            event=row.event,
            actor_kind=row.actor_kind,
            actor_ref=row.actor_ref or {},
            detail=row.detail or {},
        )
        for row in rows.scalars().all()
    ]
    return SkillHistoryOut(
        items=items, total=total, limit=limit, offset=offset, skill_id=skill.id, skill_key=skill.key
    )


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


@router.patch("/me/skills/{skill_id}", response_model=UserSkillOut)
async def patch_my_skill(
    skill_id: str,
    data: UserSkillPatchIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSkillOut:
    """Toggle per-skill derivation participation (opt in/opt out)."""
    row = await SkillService(db).set_derive_enabled(
        user.id, uuid.UUID(skill_id), data.derive_enabled
    )
    return _user_skill_out(row)


@router.delete("/me/skills/{skill_id}", status_code=204)
async def delete_my_skill(
    skill_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a skill row permanently: hidden everywhere, derivation
    never resurrects it (re-adding the skill makes a fresh row)."""
    await SkillService(db).delete_user_skill(user.id, uuid.UUID(skill_id))


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
        derive_enabled=row.derive_enabled,
        hidden=row.hidden,
    )
