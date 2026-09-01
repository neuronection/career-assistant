"""Experience profile API (plan 40): structured items, derivation, evidence."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.experience import (
    DerivationApplyOut,
    DerivationOut,
    ExperienceItemIn,
    ExperienceItemOut,
    ExperienceItemUpdate,
    ExperienceOut,
    EvidenceOut,
)
from app.services.deps import get_current_user
from app.services.experience_service import ExperienceService

router = APIRouter(tags=["experience"])


def _skill_out(link) -> dict:
    return {
        "skill_id": link.skill_id,
        "skill_key": link.skill.key,
        "skill_label": link.skill.label,
        "role_in_item": link.role_in_item,
        "level_claim": link.level_claim,
        "last_used": link.last_used,
    }


def _item_out(item) -> ExperienceItemOut:
    return ExperienceItemOut(
        id=item.id,
        kind=item.kind,
        title=item.title,
        org_name=item.org_name,
        org_id=item.org_id,
        start=item.start,
        end=item.end,
        open_ended=item.open_ended,
        hours_per_week=item.hours_per_week,
        onsite_policy=item.onsite_policy,
        description=item.description,
        links=item.links or [],
        source=item.source,
        status=item.status,
        created_at=item.created_at,
        skills=[_skill_out(link) for link in item.skills],
        achievements=[
            {"id": a.id, "text": a.text, "metric": a.metric} for a in item.achievements
        ],
    )


@router.get("/me/experience", response_model=ExperienceOut)
async def list_experience(
    status: str | None = Query(default=None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExperienceOut:
    """The caller's structured experience items (newest first)."""
    service = ExperienceService(db)
    items = await service.list_items(user.id, status=status)
    derivation = await service.derivation(user.id)
    return ExperienceOut(
        items=[_item_out(item) for item in items],
        years_of_experience=derivation["years_of_experience"],
    )


@router.post("/me/experience", response_model=ExperienceItemOut, status_code=201)
async def create_experience(
    data: ExperienceItemIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExperienceItemOut:
    """Add one structured experience item (org find-or-proposes)."""
    item = await ExperienceService(db).create_item(user.id, data.model_dump())
    item = await ExperienceService(db).get_item(user.id, item.id)
    return _item_out(item)


@router.patch("/me/experience/{item_id}", response_model=ExperienceItemOut)
async def update_experience(
    item_id: UUID,
    data: ExperienceItemUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExperienceItemOut:
    """Edit an item (full-replace of skills/achievements when present)."""
    payload = data.model_dump(exclude_unset=True)
    item = await ExperienceService(db).update_item(user.id, item_id, payload)
    item = await ExperienceService(db).get_item(user.id, item.id)
    return _item_out(item)


@router.delete("/me/experience/{item_id}", status_code=204)
async def delete_experience(
    item_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ExperienceService(db).delete_item(user.id, item_id)


@router.get("/me/experience/derivation", response_model=DerivationOut)
async def experience_derivation(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DerivationOut:
    """Live preview of derived levels + years (never written)."""
    return DerivationOut.model_validate(await ExperienceService(db).derivation(user.id))


@router.post("/me/experience/derivation/apply", response_model=DerivationApplyOut)
async def apply_experience_derivation(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DerivationApplyOut:
    """Write derived levels to user_skills + skill_evidence (conflict-aware)."""
    from app.services.job_worker import enqueue
    from app.models.enums import BackgroundJobType
    from app.services.fit.service import FitService

    service = ExperienceService(db)
    result = await service.apply_derivation(user.id)
    await enqueue(
        db, BackgroundJobType.MATCH_SCORE.value, {"limit": 10}, user_id=user.id
    )
    await FitService(db).refit_user(user.id)
    return DerivationApplyOut.model_validate(result)


@router.get("/me/skills/{skill_id}/evidence", response_model=EvidenceOut)
async def skill_evidence(
    skill_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvidenceOut:
    """Trace: which items/runs/documents support this skill's level."""
    return EvidenceOut.model_validate(
        await ExperienceService(db).skill_evidence(user.id, skill_id)
    )
