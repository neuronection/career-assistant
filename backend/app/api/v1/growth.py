"""Growth toolkit endpoints (Phase 28)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.growth_model import LearningResource
from app.models.user_model import User
from app.services.deps import get_current_user
from app.services.growth_service import (
    checkin_status,
    complete_checkin,
    create_plan,
    list_plans,
    market_snapshot,
    near_miss_radar,
    patch_step,
)

router = APIRouter(tags=["growth"])


class PlanCreateIn(BaseModel):
    target_job_id: UUID


class StepPatchIn(BaseModel):
    status: str | None = Field(default=None, pattern="^(todo|doing|done|skipped)$")
    position: int | None = Field(default=None, ge=0, le=99)
    completed_level: int | None = Field(default=None, ge=1, le=10)


class CheckinIn(BaseModel):
    stage: str | None = Field(default=None, max_length=20)
    skills: dict[str, int] | None = None
    skipped: bool = False


@router.post("/growth/plans")
async def post_growth_plan(
    data: PlanCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate a tracked roadmap: curated path steps + skill gaps."""
    return await create_plan(db, user.id, data.target_job_id)


@router.get("/growth/plans")
async def get_growth_plans(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """The caller's roadmaps with steps + resources."""
    return await list_plans(db, user.id)


@router.patch("/growth/steps/{step_id}")
async def patch_growth_step(
    step_id: UUID,
    data: StepPatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Edit/reorder a step; completing a skill step upserts the skill and
    re-fits — the loop closes visibly."""
    return await patch_step(
        db,
        user.id,
        step_id,
        status=data.status,
        position=data.position,
        completed_level=data.completed_level,
    )


@router.get("/growth/radar")
async def growth_radar(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Near-miss radar: close-fit jobs missing few discrete skills."""
    return await near_miss_radar(db, user.id)


@router.get("/market/snapshot")
async def get_market_snapshot(
    family_key: str | None = Query(default=None),
    job_id: UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Posting analytics for a family or job (thin-sample honesty included)."""
    return await market_snapshot(db, family_key=family_key, job_id=job_id)


@router.get("/me/checkin")
async def get_checkin(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Quarterly check-in state (banner); lazily schedules the first one."""
    return await checkin_status(db, user.id)


@router.post("/me/checkin")
async def post_checkin(
    data: CheckinIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Complete (stage + micro self-report with conflict surfacing) or skip."""
    return await complete_checkin(
        db, user.id, stage=data.stage, skills=data.skills, skipped=data.skipped
    )


@router.get("/skills/{skill_id}/resources")
async def skill_resources(
    skill_id: UUID, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Published learning resources for a skill (gap panels, radar cards)."""
    rows = (
        (
            await db.execute(
                select(LearningResource)
                .where(
                    LearningResource.skill_id == skill_id,
                    LearningResource.status == "published",
                )
                .order_by(LearningResource.level_target.nulls_last())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "kind": r.kind,
            "title": r.title,
            "provider": r.provider,
            "url": r.url,
            "cost": r.cost,
            "level_target": r.level_target,
        }
        for r in rows
    ]


@router.post("/skills/{skill_id}/resources", status_code=201)
async def create_skill_resource(
    skill_id: UUID,
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin CRUD (plan 15 hosts the full moderation queue; AI suggestions
    land as drafts via `source`)."""
    from app.core.errors import ValidationError
    from urllib.parse import urlparse

    if not user.is_admin:
        from fastapi import HTTPException
        from fastapi import status as http_status

        raise HTTPException(http_status.FORBIDDEN, "Admin only")
    url = str(payload.get("url") or "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValidationError("Resource urls must be absolute https:// urls")
    from app.models.enums import (
        ResourceCost,
        ResourceKind,
        ResourceSource,
        ResourceStatus,
    )

    kind = payload.get("kind", "course")
    if kind not in {k.value for k in ResourceKind}:
        raise ValidationError(f"Invalid resource kind: {kind}")
    cost = payload.get("cost", "free")
    if cost not in {c.value for c in ResourceCost}:
        raise ValidationError(f"Invalid resource cost: {cost}")
    source = payload.get("source", "admin")
    if source not in {s.value for s in ResourceSource}:
        raise ValidationError(f"Invalid resource source: {source}")
    status = (
        ResourceStatus.DRAFT.value
        if source == ResourceSource.AI.value
        else ResourceStatus.PUBLISHED.value
    )
    resource = LearningResource(
        skill_id=skill_id,
        kind=kind,
        title=str(payload.get("title") or "")[:200],
        provider=str(payload.get("provider") or "")[:120],
        url=url[:500],
        cost=cost,
        level_target=payload.get("level_target"),
        status=status,
        source=source,
    )
    db.add(resource)
    await db.commit()
    await db.refresh(resource)
    return {
        "id": str(resource.id),
        "status": resource.status,
        "source": resource.source,
    }
