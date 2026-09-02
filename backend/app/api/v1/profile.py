from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AINotConfiguredError, DomainError
from app.schemas.profile import ProfileSectionUpdate
from app.services.deps import get_current_user
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


async def _profile_out(db, profile) -> dict:
    """Serialise a profile with derived fields (interests from joins)."""
    from app.schemas.profile import (
        AcademicsSection,
        BasicSection,
        ConstraintsSection,
        PreferencesSection,
        WorkPreferencesSection,
    )
    from app.services.experience_service import ExperienceService
    from app.services.profile_service import ProfileService
    from app.services.stages_service import effective_stage

    service = ProfileService(db)
    interests = await service.interest_rows(profile.user_id)
    stage, stage_source = effective_stage(
        profile.basics or {}, await ExperienceService(db).stage_dicts(profile.user_id)
    )
    return {
        "basics": BasicSection.model_validate(profile.basics or {}),
        "academics": AcademicsSection.model_validate(profile.academics or {}),
        "career_stage": stage.value,
        "stage_source": stage_source,
        "interests": ProfileService.interests_out(interests),
        "hobbies": profile.hobbies or [],
        "likes": profile.likes or [],
        "dislikes": profile.dislikes or [],
        "aspirations": profile.aspirations or [],
        "work_preferences": WorkPreferencesSection.model_validate(
            profile.work_preferences or {}
        ),
        "preferences": PreferencesSection.model_validate(
            profile.preferences or {}
        ).model_dump(mode="json"),
        "constraints": ConstraintsSection.model_validate(profile.constraints or {}),
        "ai_summary": profile.ai_summary,
    }


@router.get("")
async def get_profile(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """The caller's structured profile (+ completeness)."""
    service = ProfileService(db)
    profile = await service.get(user.id)
    interests_count = len(await service.interest_rows(user.id))
    return {
        **await _profile_out(db, profile),
        "completeness": service.completeness(profile, interests_count),
    }


@router.put("")
async def update_profile(
    data: ProfileSectionUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Merge validated section updates into the profile."""
    service = ProfileService(db)
    profile = await service.update(user.id, data)
    interests_count = len(await service.interest_rows(user.id))
    return {
        **await _profile_out(db, profile),
        "completeness": service.completeness(profile, interests_count),
    }


@router.post("/ai-analyze")
async def ai_analyze(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Run the AI profile analyst and store the structured summary."""
    service = ProfileService(db)
    profile = await service.get(user.id)
    try:
        profile = await service.ai_analyze(user.id, profile)
    except AINotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    interests_count = len(await service.interest_rows(user.id))
    return {
        "ai_summary": profile.ai_summary,
        "completeness": service.completeness(profile, interests_count),
    }
