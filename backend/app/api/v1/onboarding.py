"""Express onboarding + target mode endpoints (Phase 27)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.onboarding import (
    CompletenessOut,
    ExpressIn,
    ExpressOut,
    NudgeOut,
    ResolveOut,
    TargetDashboardOut,
)
from app.services.deps import get_current_user
from app.services.target_service import (
    completeness_ring,
    dismiss_nudge,
    express_onboarding,
    get_nudges,
    resolve_query,
    target_dashboard,
)

router = APIRouter(tags=["onboarding"])


@router.get("/onboarding/resolve", response_model=ResolveOut)
async def resolve(
    q: str = Query(default="", max_length=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResolveOut:
    """Typeahead: alias/trigram first, AI fallback — taxonomy keys only."""
    result = await resolve_query(db, user.id, q)
    return ResolveOut.model_validate(result)


@router.post("/onboarding/express", response_model=ExpressOut)
async def express(
    data: ExpressIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ExpressOut:
    """The 2-minute path: targets + sparse context + alert rules in one call."""
    result = await express_onboarding(
        db,
        user.id,
        targets=data.targets,
        location=data.location,
        remote=data.remote,
        stage=data.stage,
        min_fit=data.min_fit,
        max_per_day=data.max_per_day,
    )
    return ExpressOut.model_validate(result)


@router.get("/me/completeness", response_model=CompletenessOut)
async def me_completeness(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CompletenessOut:
    """Profile ring segments: what data would sharpen results."""
    return CompletenessOut.model_validate(await completeness_ring(db, user.id))


@router.get("/me/nudges", response_model=list[NudgeOut])
async def me_nudges(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[NudgeOut]:
    """Contextual micro-run nudges (capped + dismissible)."""
    return [NudgeOut.model_validate(n) for n in await get_nudges(db, user.id)]


@router.post("/me/nudges/{nudge_type}/dismiss")
async def dismiss_a_nudge(
    nudge_type: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Dismiss a nudge type forever."""
    return await dismiss_nudge(db, user.id, nudge_type)


@router.get("/dashboard/target", response_model=TargetDashboardOut)
async def dashboard_target(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> TargetDashboardOut:
    """Target-mode aggregate: open jobs, adjacent targets, market snapshot."""
    return TargetDashboardOut.model_validate(await target_dashboard(db, user.id))
