from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.models.enums import CareerStage
from app.schemas.background_job import EnqueueResponse
from app.services.account_service import delete_account, request_export
from app.services.deps import get_current_user

router = APIRouter(prefix="/me", tags=["me"])


class DeleteAccountIn(BaseModel):
    password: str


class StageIn(BaseModel):
    """None clears the explicit stage (falls back to the derivation)."""

    career_stage: CareerStage | None = None


async def _bootstrap_payload(db, profile) -> dict:
    """Shared shape for GET /me/bootstrap and PUT /me/stage (plans 25+27)."""
    from sqlalchemy import select

    from app.models.engagement_model import NotificationRule
    from app.models.enums import NotificationRuleKind
    from app.services.notification_channels import available_channels
    from app.services.experience_service import ExperienceService
    from app.services.stages_service import (
        effective_stage,
        feature_flags,
        stage_preset,
    )

    stage, source = effective_stage(
        profile.basics or {}, await ExperienceService(db).stage_dicts(profile.user_id)
    )
    stored = (profile.preferences or {}).get("scoring_weights")
    target_families: list[str] = []
    rules = (
        (
            await db.execute(
                select(NotificationRule).where(
                    NotificationRule.user_id == profile.user_id,
                    NotificationRule.kind
                    == NotificationRuleKind.NEW_POSTING_MATCH.value,
                    NotificationRule.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for rule in rules:
        target_families.extend(rule.params.get("family_keys") or [])
    return {
        "career_stage": stage.value,
        "stage_source": source,
        "features": feature_flags(stage),
        "suggested_scoring_weights": stage_preset(stage),
        "effective_scoring_weights": stored or stage_preset(stage),
        "weights_overridden": bool(stored),
        "target_mode": bool(target_families),
        "target_families": sorted(set(target_families)),
        "notification_channels": available_channels(),
    }


@router.get("/bootstrap")
async def bootstrap(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Stage + per-feature flags for the SPA shell (plan 25's flag pattern)."""
    from app.services.deps import get_profile_for_user

    profile = await get_profile_for_user(db, user.id)
    from app.services.scheduler.runner import SchedulerService

    await SchedulerService(db).ensure_user_schedules(user.id)
    return await _bootstrap_payload(db, profile)


@router.put("/stage")
async def put_stage(
    body: StageIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Switch stage (Settings): presets re-apply and insights refit.

    Plan 25 wants plan-16's staleness flag; until that phase lands the
    switch refits synchronously — same result, no stale badge needed.
    """
    from app.services.deps import get_profile_for_user
    from app.services.fit.service import FitService
    from app.services.profile_service import ProfileService

    profile = await get_profile_for_user(db, user.id)
    basics = {**(profile.basics or {})}
    if body.career_stage is None:
        basics.pop("career_stage", None)
    else:
        basics["career_stage"] = body.career_stage.value
    profile.basics = basics
    await ProfileService(db).strip_student_fields(profile)
    db.add(profile)
    await db.commit()
    refitted = await FitService(db).refit_user(user.id, profile)
    payload = await _bootstrap_payload(db, profile)
    payload["refitted"] = refitted
    return payload


@router.put("/preferences/scoring")
async def put_scoring_weights(
    weights: dict,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Store fit-dimension weight sliders (1–5) and refit (deterministic only)."""
    from app.schemas.profile import ScoringWeights
    from app.services.deps import get_profile_for_user
    from app.services.fit.service import FitService

    try:
        validated = ScoringWeights(**{k: int(v) for k, v in (weights or {}).items()})
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "weights must be integers 1–5 for skills, location, experience, "
            "education, interests",
        ) from exc
    profile = await get_profile_for_user(db, user.id)
    profile.preferences = {
        **(profile.preferences or {}),
        "scoring_weights": validated.model_dump(mode="json"),
    }
    db.add(profile)
    await db.commit()
    refitted = await FitService(db).refit_user(user.id, profile)
    return {
        "scoring_weights": validated.model_dump(mode="json"),
        "refitted": refitted,
    }


@router.post("/export", response_model=EnqueueResponse, status_code=202)
async def export_my_data(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> EnqueueResponse:
    """Queue a personal-data export; download via /background-jobs/{id}/download."""
    job_id = await request_export(db, user)
    return EnqueueResponse(job_id=job_id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    data: DeleteAccountIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete the caller's account and personal data."""
    try:
        await delete_account(db, user, data.password)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
