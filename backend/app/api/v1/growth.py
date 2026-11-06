"""Growth toolkit endpoints (Phase 28)."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.enums import GrowthPlanStatus, GrowthStepStatus
from app.models.growth_model import LearningResource
from app.models.user_model import User
from app.services.deps import get_current_user
from app.services.growth.growth_service import (
    checkin_status,
    complete_checkin,
    create_plan,
    list_plans,
    market_snapshot,
    near_miss_radar,
    patch_step,
)


class TargetJobRef(BaseModel):
    id: str
    title: str
    code: str


class GrowthResourceOut(BaseModel):
    id: str
    kind: str
    title: str
    provider: str
    url: str
    cost: str


class GrowthStepOut(BaseModel):
    id: str
    position: int
    kind: str
    label: str
    skill_id: str | None = None
    target_level: int | None = None
    status: GrowthStepStatus
    completed_level: int | None = None
    resources: list[GrowthResourceOut] = Field(default_factory=list)


class GrowthStepRefOut(BaseModel):
    """The patched step's post-write state (minimal envelope)."""

    id: str
    position: int
    status: GrowthStepStatus
    completed_level: int | None = None


class StepPatchOut(BaseModel):
    step: GrowthStepRefOut
    conflicts: list[dict] = Field(default_factory=list)
    refitted: int = 0


class GrowthPlanOut(BaseModel):
    id: str
    status: GrowthPlanStatus
    target_job: TargetJobRef
    completed_at: datetime | None = None
    steps: list[GrowthStepOut] = Field(default_factory=list)


class RadarDeficitOut(BaseModel):
    skill_id: str
    key: str
    label: str
    current_level: int
    required_level: int
    delta: int
    importance: str


class RadarEntryOut(BaseModel):
    job_id: str
    code: str
    title: str
    family_key: str
    fit_score: float
    deficits: list[RadarDeficitOut] = Field(default_factory=list)
    headline: str


class MarketMonthPointOut(BaseModel):
    month: str
    postings: int


class MarketSalaryBandOut(BaseModel):
    p25: float | None = None
    p75: float | None = None


class MarketTopEmployerOut(BaseModel):
    org: str
    count: int


class MarketTopSkillOut(BaseModel):
    key: str
    count: int


class MarketSnapshotOut(BaseModel):
    """Posting analytics for one scope (never a fit input)."""

    sample_size: int
    thin_sample: bool
    months: list[MarketMonthPointOut] = Field(default_factory=list)
    salary_band: MarketSalaryBandOut | None = None
    top_employers: list[MarketTopEmployerOut] = Field(default_factory=list)
    top_skills: list[MarketTopSkillOut] = Field(default_factory=list)


class MarketTrendPointOut(BaseModel):
    capture_date: str
    captured_at: str
    sample_size: int
    thin_sample: bool
    salary_band: dict | None = None
    months: list = Field(default_factory=list)


class CheckinStatusOut(BaseModel):
    due: bool
    next_at: str | None = None
    last_at: str | None = None


class CheckinCompleteOut(BaseModel):
    skipped: bool
    applied_skills: int
    conflicts: list[dict] = Field(default_factory=list)
    stage: str
    next_at: str | None = None


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


@router.post("/growth/plans", response_model=GrowthPlanOut)
async def post_growth_plan(
    data: PlanCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate a tracked roadmap: curated path steps + skill gaps."""
    return await create_plan(db, user.id, data.target_job_id)


@router.get("/growth/plans", response_model=list[GrowthPlanOut])
async def get_growth_plans(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """The caller's roadmaps with steps + resources."""
    return await list_plans(db, user.id)


@router.patch("/growth/steps/{step_id}", response_model=StepPatchOut)
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


@router.get("/growth/radar", response_model=list[RadarEntryOut])
async def growth_radar(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Near-miss radar: close-fit jobs missing few discrete skills."""
    return await near_miss_radar(db, user.id)


@router.get("/market/snapshot", response_model=MarketSnapshotOut)
async def get_market_snapshot(
    family_key: str | None = Query(default=None),
    job_id: UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Posting analytics for a family or job (thin-sample honesty included)."""
    return await market_snapshot(db, family_key=family_key, job_id=job_id)


@router.get("/market/trend", response_model=list[MarketTrendPointOut])
async def get_market_trend(
    family_key: str | None = Query(default=None),
    job_id: UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Persisted demand history for one scope, oldest first."""
    from app.services.postings import market_history_service

    if (family_key is None) == (job_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "exactly one of family_key / job_id is required",
        )
    return await market_history_service.trend(db, family_key=family_key, job_id=job_id)


@router.get("/me/checkin", response_model=CheckinStatusOut)
async def get_checkin(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Quarterly check-in state (banner); lazily schedules the first one."""
    return await checkin_status(db, user.id)


@router.post("/me/checkin", response_model=CheckinCompleteOut)
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
async def skill_resources(skill_id: UUID, db: AsyncSession = Depends(get_db)) -> list[dict]:
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
    """Admin CRUD ( hosts the full moderation queue; AI suggestions
    land as drafts via `source`)."""
    from urllib.parse import urlparse

    from app.core.errors import ValidationError

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
