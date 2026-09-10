"""Metric dimension registry + the caller's metric profile."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.metric_model import UserMetricProfile
from app.services.deps import get_current_user
from app.services.metric_service import MetricService

router = APIRouter(prefix="/metrics", tags=["metrics"])


class MetricDimensionOut(BaseModel):
    key: str
    label: str
    group: str
    description: str
    scale: str
    reverse_score: bool
    sources: list[str]
    consumers: list[str]


class UserMetricOut(BaseModel):
    dimension_key: str
    value: float
    confidence: float
    source: str
    evidence: dict

    model_config = {"from_attributes": True}


class MetricRegistryOut(BaseModel):
    dimensions: list[MetricDimensionOut]


class UserMetricsOut(BaseModel):
    metrics: list[UserMetricOut]


def _dimension_out(row) -> MetricDimensionOut:
    return MetricDimensionOut(
        key=row.key,
        label=row.label,
        group=row.group,
        description=row.description,
        scale=row.scale,
        reverse_score=row.reverse_score,
        sources=row.sources or [],
        consumers=row.consumers or [],
    )


@router.get("/registry", response_model=MetricRegistryOut)
async def metric_registry(
    _user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> MetricRegistryOut:
    """The curated dimension registry (labels, groups, sources, consumers)."""
    return MetricRegistryOut(
        dimensions=[_dimension_out(row) for row in await MetricService(db).registry()]
    )


@router.get("/me", response_model=UserMetricsOut)
async def my_metrics(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UserMetricsOut:
    """The caller's measured values with provenance."""
    rows = await MetricService(db).user_metrics(user.id)
    return UserMetricsOut(metrics=[UserMetricOut.model_validate(row) for row in rows])


@router.post("/me/interest-affinity/recompute", response_model=dict)
async def recompute_interest_affinity(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Re-derive the RIASEC vector from the caller's current interest tags."""
    count = await MetricService(db).recompute_interest_affinity(user.id)
    return {"dimensions": count}


@router.post("/me/revealed/recompute", response_model=dict)
async def recompute_revealed_preferences(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Opt-in behavior drift for the RIASEC affinities.

    A no-op unless the user enabled revealed preferences; each call moves
    `interest.*` values by at most 5% of the scale toward the engagement
    signal. The exploration slot is never touched."""
    return await MetricService(db).apply_revealed_preferences(user.id)


@router.get("/me/outcomes", response_model=list[dict])
async def my_outcomes(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Application funnel per catalog family — observation only (plan
    38.6): never fed back into scoring."""
    return await MetricService(db).outcome_funnel(user.id)


@router.get("/engine-dimensions", response_model=list[dict])
async def engine_dimensions(
    _user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Both fit engines' dimension lists from their code specs:
    key, label and default weight — the single source for settings UIs."""
    return MetricService(db).engine_dimensions()


@router.get("/transferability", response_model=list[dict])
async def skill_transferability(
    skill_key: str | None = None,
    limit: int = 100,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Derived per-skill transferability over the job-family graph.

    `share` = fraction of job families (with published jobs) whose jobs
    ask for the skill — "your SQL transfers to 12 of 20 families".
    """
    return await MetricService(db).transferability_rows(
        skill_key=skill_key, limit=limit
    )


@router.post("/transferability/recompute", response_model=dict)
async def recompute_transferability(
    _user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Rebuild the transferability stats (also runs on catalog changes)."""
    count = await MetricService(db).recompute_skill_transferability()
    return {"skills": count}


@router.get("/me/{dimension_key}", response_model=UserMetricOut)
async def my_metric(
    dimension_key: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserMetricOut:
    """One dimension value for the caller (404 when never measured)."""
    row = (
        (
            await db.execute(
                select(UserMetricProfile).where(
                    UserMetricProfile.user_id == user.id,
                    UserMetricProfile.dimension_key == dimension_key,
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise NotFoundError("Metric not measured")
    return UserMetricOut.model_validate(row)
