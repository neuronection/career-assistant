from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AINotConfiguredError, DomainError
from app.schemas.competency import (
    CompetenciesOut,
    CompetencyEvidenceOut,
    CompetencyOut,
)
from app.schemas.discipline import DegreeRoleMatchOut, DegreeRolesOut
from app.schemas.profile import ProfileSectionUpdate
from app.services.deps import get_current_user, get_profile_id
from app.services.profile.profile_service import ProfileService

# §15 profile-scoped: the middleware-bound profile is the request's
# scope (`get_profile_id` re-checks it; ownership was validated there).
router = APIRouter(prefix="/profile", tags=["profile"], dependencies=[Depends(get_profile_id)])


async def _profile_out(db, profile) -> dict:
    """Serialise a profile with derived fields (interests from joins)."""
    from app.schemas.profile import (
        AcademicsSection,
        BasicSection,
        ConstraintsSection,
        PreferencesSection,
        WorkPreferencesSection,
    )
    from app.services.profile.experience_service import ExperienceService
    from app.services.profile.profile_service import ProfileService
    from app.services.profile.stages_service import effective_stage

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
        "work_preferences": WorkPreferencesSection.model_validate(profile.work_preferences or {}),
        "preferences": PreferencesSection.model_validate(profile.preferences or {}).model_dump(
            mode="json"
        ),
        "constraints": ConstraintsSection.model_validate(profile.constraints or {}),
        "ai_summary": profile.ai_summary,
    }


async def _required_sections(db, profile) -> set[str]:
    """Required checks for the caller's start path."""
    from app.services.profile.experience_service import ExperienceService
    from app.services.profile.stages_service import (
        effective_stage,
        feature_flags,
        required_sections,
    )

    stage, _source = effective_stage(
        profile.basics or {}, await ExperienceService(db).stage_dicts(profile.user_id)
    )
    return required_sections((profile.basics or {}).get("onboarding_path"), feature_flags(stage))


@router.get("")
async def get_profile(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """The caller's structured profile (+ completeness)."""
    service = ProfileService(db)
    profile = await service.get(user.id)
    interests_count = len(await service.interest_rows(user.id))
    return {
        **await _profile_out(db, profile),
        "completeness": service.completeness(
            profile,
            interests_count,
            required=await _required_sections(db, profile),
        ),
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
        "completeness": service.completeness(
            profile,
            interests_count,
            required=await _required_sections(db, profile),
        ),
    }


@router.post("/ai-analyze")
async def ai_analyze(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
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
        "completeness": service.completeness(
            profile,
            interests_count,
            required=await _required_sections(db, profile),
        ),
    }


class JsonResumeImportIn(BaseModel):
    resume: dict
    apply: bool = False

    @field_validator("resume")
    @classmethod
    def _bounded_resume(cls, value: dict) -> dict:
        import json as _json

        from app.services.profile.json_resume_service import MAX_IMPORT_BYTES

        if len(_json.dumps(value)) > MAX_IMPORT_BYTES:
            raise ValueError(f"resume exceeds the {MAX_IMPORT_BYTES}-byte import cap")
        return value


@router.get("/degree-roles", response_model=DegreeRolesOut)
async def degree_roles(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DegreeRolesOut:
    """Deterministic programme/focus-subject -> family suggestions."""
    from app.services.profile.discipline_service import degree_matches

    matches = await degree_matches(db, user.id)
    return DegreeRolesOut(
        matches=[
            DegreeRoleMatchOut(
                family_key=match.family_key,
                family_title=match.family_title,
                matched_terms=list(match.matched_terms),
                reason=match.reason,
                depth=match.depth,
            )
            for match in matches
        ]
    )


@router.get("/competencies", response_model=CompetenciesOut)
async def competencies(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CompetenciesOut:
    """Evidence-derived NACE competencies; no self-rating or score."""
    from app.services.profile.competency_service import user_competencies

    rows = await user_competencies(db, user.id)
    return CompetenciesOut(
        competencies=[
            CompetencyOut(
                key=row["key"],
                evidence=[
                    CompetencyEvidenceOut(
                        id=item["id"],
                        kind=item["kind"],
                        label=item["label"],
                        quote=item["quote"],
                    )
                    for item in row["evidence"]
                ],
            )
            for row in rows
        ]
    )


@router.get("/export/jsonresume")
async def export_json_resume(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    from app.services.profile.json_resume_service import export_resume

    return await export_resume(db, user.id)


@router.post("/import/jsonresume")
async def import_json_resume(
    payload: JsonResumeImportIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.profile.json_resume_service import import_resume

    return await import_resume(db, user.id, payload.resume, apply=payload.apply)
