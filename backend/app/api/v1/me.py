from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.enums import CareerStage, OnboardingPath
from app.schemas.application import FollowupRuleIn, FollowupRuleOut, FollowupSurfaceOut
from app.schemas.background_job import EnqueueResponse
from app.schemas.bootstrap import BootstrapOut
from app.schemas.i18n import LocaleIn, MeLocaleStateOut
from app.schemas.radar import RadarIn, RadarOut
from app.services.deps import get_current_user, get_profile_id
from app.services.postings.radar_service import get_radar, upsert_radar
from app.services.profile.account_service import request_export

router = APIRouter(prefix="/me", tags=["me"])


class StageIn(BaseModel):
    """None clears the explicit stage (falls back to the derivation)."""

    career_stage: CareerStage | None = None


class OnboardingPathIn(BaseModel):
    """None clears the start path (back to the hero picker)."""

    path: OnboardingPath | None = None


class AiSetupPrefsIn(BaseModel):
    """First-run AI setup step skip state (typed `profiles.preferences` key)."""

    dismissed: bool = True


async def _fit_stale(db, user_id) -> bool:
    """True while fits are being recomputed or still on an old version."""
    from sqlalchemy import select

    from app.models.background_job_model import BackgroundJob
    from app.models.enums import BackgroundJobStatus, BackgroundJobType
    from app.models.matching_model import MatchInsight
    from app.services.postings.fit.dimensions import FIT_VERSION

    pending = (
        (
            await db.execute(
                select(BackgroundJob.id)
                .where(
                    BackgroundJob.user_id == user_id,
                    BackgroundJob.job_type == BackgroundJobType.FIT_REFIT.value,
                    BackgroundJob.status.in_(
                        [
                            BackgroundJobStatus.QUEUED.value,
                            BackgroundJobStatus.RUNNING.value,
                        ]
                    ),
                )
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if pending is not None:
        return True
    off_version = (
        (
            await db.execute(
                select(MatchInsight.id)
                .where(
                    MatchInsight.user_id == user_id,
                    MatchInsight.fit_version != FIT_VERSION,
                )
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return off_version is not None


async def _bootstrap_payload(db, profile) -> dict:
    """Shared shape for GET /me/bootstrap and PUT /me/stage (plans 25+27)."""
    from sqlalchemy import select

    from app.ai.status import ai_status
    from app.models.engagement_model import NotificationRule
    from app.models.enums import NotificationRuleKind
    from app.services.notification_channels import available_channels
    from app.services.profile.experience_service import ExperienceService
    from app.services.profile.stages_service import (
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
                    NotificationRule.kind == NotificationRuleKind.NEW_POSTING_MATCH.value,
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
        "onboarding_path": (profile.basics or {}).get("onboarding_path"),
        "features": feature_flags(stage),
        "suggested_scoring_weights": stage_preset(stage),
        "effective_scoring_weights": stored or stage_preset(stage),
        "weights_overridden": bool(stored),
        "fit_stale": await _fit_stale(db, profile.user_id),
        "target_mode": bool(target_families),
        "target_families": sorted(set(target_families)),
        "notification_channels": available_channels(),
        "ai": (
            await ai_status(
                db,
                profile.user_id,
                setup_dismissed=bool((profile.preferences or {}).get("ai_setup_dismissed")),
            )
        ).payload(),
    }


@router.get("/locale", response_model=MeLocaleStateOut)
async def get_locale(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """The caller's effective UI locale and the supported registry."""
    from app.services.locale_service import (
        SUPPORTED_LOCALES,
        effective_locale,
        instance_default_locale,
    )

    locale = await effective_locale(db, user)
    return {
        "locale": locale,
        "supported": list(SUPPORTED_LOCALES),
        "source": "user" if user.locale else "instance",
        "instance_locale": await instance_default_locale(db),
    }


@router.put("/locale", response_model=MeLocaleStateOut)
async def put_locale(
    body: LocaleIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Persist the caller's UI locale; the SPA re-initialises i18next from it."""
    from app.services.locale_service import SUPPORTED_LOCALES, normalize_locale

    normalized = normalize_locale(body.locale)
    if normalized is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported locale: {body.locale}",
        )
    user.locale = normalized
    db.add(user)
    await db.commit()
    return {"locale": normalized, "supported": list(SUPPORTED_LOCALES), "source": "user"}


@router.get("/bootstrap", response_model=BootstrapOut)
async def bootstrap(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Stage + per-feature flags for the SPA shell."""
    from app.services.deps import get_profile_for_user

    profile = await get_profile_for_user(db, user.id)
    from app.services.locale_service import (
        SUPPORTED_LOCALES,
        effective_locale,
        instance_default_locale,
    )
    from app.services.scheduler.runner import SchedulerService

    await SchedulerService(db).ensure_user_schedules(user.id)
    payload = await _bootstrap_payload(db, profile)
    payload["locale"] = await effective_locale(db, user)
    payload["locale_source"] = "user" if user.locale else "instance"
    payload["instance_locale"] = await instance_default_locale(db)
    payload["supported_locales"] = list(SUPPORTED_LOCALES)
    return payload


@router.put("/stage", response_model=BootstrapOut)
async def put_stage(
    body: StageIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Switch stage (Settings): presets re-apply; fits refit async.

    The refit rides the queue (`fit_stale` in the bootstrap
    payload flags the in-flight window; the badge clears once the sweep
    stamps the new fit_version).
    """
    from app.models.enums import BackgroundJobType
    from app.services.deps import get_profile_for_user
    from app.services.job_worker import enqueue
    from app.services.profile.profile_service import ProfileService

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
    job = await enqueue(db, BackgroundJobType.FIT_REFIT.value, {}, user_id=user.id)
    payload = await _bootstrap_payload(db, profile)
    payload["refit_queued"] = True
    payload["refit_job_id"] = str(job.id)
    return payload


@router.put("/onboarding-path")
async def put_onboarding_path(
    body: OnboardingPathIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Store the start-path choice from the hero picker.

    Unlike stage: no presets, no refit, no field stripping — the path
    only scopes the wizard and the required-section nagging.
    """
    from app.services.deps import get_profile_for_user

    profile = await get_profile_for_user(db, user.id)
    basics = {**(profile.basics or {})}
    if body.path is None:
        basics.pop("onboarding_path", None)
    else:
        basics["onboarding_path"] = body.path.value
    profile.basics = basics
    db.add(profile)
    await db.commit()
    return await _bootstrap_payload(db, profile)


@router.put("/preferences/scoring")
async def put_scoring_weights(
    weights: dict,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Store fit-dimension weight sliders (1-5) and refit (deterministic only)."""
    from app.schemas.profile import ScoringWeights
    from app.services.deps import get_profile_for_user
    from app.services.postings.fit.service import FitService

    try:
        validated = ScoringWeights(**{k: int(v) for k, v in (weights or {}).items()})
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "weights must be integers 1-5 for skills, location, experience, education, interests",
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


@router.put("/preferences/ai-setup")
async def put_ai_setup_pref(
    body: AiSetupPrefsIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Store whether the caller skipped the first-run AI setup step.

    The skip rides a typed `profiles.preferences` key (schema is frozen —
    plan 113); the setup prompt itself keeps rendering until a provider is
    configured, so dismissing never hides the gap.
    """
    from app.services.deps import get_profile_for_user

    profile = await get_profile_for_user(db, user.id)
    profile.preferences = {
        **(profile.preferences or {}),
        "ai_setup_dismissed": bool(body.dismissed),
    }
    db.add(profile)
    await db.commit()
    return await _bootstrap_payload(db, profile)


@router.get("/followups", response_model=FollowupSurfaceOut)
async def get_followups(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> FollowupSurfaceOut:
    """Follow-up rules plus per-application state."""
    from app.services.postings.followups_service import list_followups

    return FollowupSurfaceOut(**await list_followups(db, user.id))


@router.patch("/followups", response_model=FollowupRuleOut)
async def patch_followup_rules(
    rules: FollowupRuleIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FollowupRuleOut:
    """Adjust the follow-up cadence and switches."""
    from app.services.postings.followups_service import update_rules

    return FollowupRuleOut(**await update_rules(db, user.id, rules.model_dump(exclude_unset=True)))


@router.post("/export", response_model=EnqueueResponse, status_code=202)
async def export_my_data(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> EnqueueResponse:
    """Queue a personal-data export; download via /background-jobs/{id}/download."""
    job_id = await request_export(db, user)
    return EnqueueResponse(job_id=job_id)


@router.get("/job-radar", response_model=RadarOut)
async def get_job_radar(
    profile_id: str = Depends(get_profile_id),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RadarOut:
    """The profile's saved job radar — defaults when never configured."""
    radar = await get_radar(db, UUID(profile_id))
    return RadarOut.model_validate(radar) if radar else RadarOut()


@router.put("/job-radar", response_model=RadarOut)
async def upsert_job_radar(
    data: RadarIn,
    profile_id: str = Depends(get_profile_id),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RadarOut:
    """Save the job radar (replace-all; omit a field = clear it).

    The match-digest schedule rides the save: an enabled radar with a
    non-off cadence provisions its per-user schedule, anything else
    removes it."""
    from app.services.postings.radar_service import cadence_trigger
    from app.services.scheduler.runner import SchedulerService

    radar = await upsert_radar(db, UUID(profile_id), data)
    trigger = cadence_trigger(radar.cadence) if radar.enabled else None
    await SchedulerService(db).set_radar_schedule(user.id, radar.id, trigger)
    return RadarOut.model_validate(radar)
