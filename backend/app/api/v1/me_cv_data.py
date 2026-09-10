"""CV-data profile entity endpoints: education, certifications,
achievements, and the deterministic cv-readiness report."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.profile_entities import (
    CertificationIn,
    CertificationOut,
    CertificationPatch,
    CvReadiness,
    EducationItemIn,
    EducationItemOut,
    EducationItemPatch,
    ProfileAchievementIn,
    ProfileAchievementOut,
    ProfileAchievementPatch,
)
from app.services.deps import get_current_user
from app.services.profile_entities_service import ProfileEntitiesService

router = APIRouter(prefix="/me", tags=["me"])


def _service(db: AsyncSession) -> ProfileEntitiesService:
    return ProfileEntitiesService(db)


@router.get("/education", response_model=list[EducationItemOut])
async def list_education(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[EducationItemOut]:
    """The caller's education entries, newest first."""
    items = await _service(db).list_education(user.id)
    return [EducationItemOut.model_validate(i) for i in items]


@router.post("/education", response_model=EducationItemOut, status_code=201)
async def create_education(
    payload: EducationItemIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EducationItemOut:
    """Add an education entry."""
    item = await _service(db).create_education(user.id, payload)
    return EducationItemOut.model_validate(item)


@router.patch("/education/{item_id}", response_model=EducationItemOut)
async def update_education(
    item_id: uuid.UUID,
    payload: EducationItemPatch,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EducationItemOut:
    """Edit an education entry (cv_parse drafts activate the same way)."""
    item = await _service(db).update_education(item_id, user.id, payload)
    return EducationItemOut.model_validate(item)


@router.delete("/education/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_education(
    item_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an education entry."""
    await _service(db).delete_education(item_id, user.id)


@router.get("/certifications", response_model=list[CertificationOut])
async def list_certifications(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[CertificationOut]:
    """The caller's certifications and licenses."""
    items = await _service(db).list_certifications(user.id)
    return [CertificationOut.model_validate(i) for i in items]


@router.post("/certifications", response_model=CertificationOut, status_code=201)
async def create_certification(
    payload: CertificationIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CertificationOut:
    """Add a certification."""
    item = await _service(db).create_certification(user.id, payload)
    return CertificationOut.model_validate(item)


@router.patch("/certifications/{item_id}", response_model=CertificationOut)
async def update_certification(
    item_id: uuid.UUID,
    payload: CertificationPatch,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CertificationOut:
    """Edit a certification."""
    item = await _service(db).update_certification(item_id, user.id, payload)
    return CertificationOut.model_validate(item)


@router.delete("/certifications/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_certification(
    item_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a certification."""
    await _service(db).delete_certification(item_id, user.id)


@router.get("/achievements", response_model=list[ProfileAchievementOut])
async def list_achievements(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ProfileAchievementOut]:
    """The caller's awards, honors and publications."""
    items = await _service(db).list_achievements(user.id)
    return [ProfileAchievementOut.model_validate(i) for i in items]


@router.post("/achievements", response_model=ProfileAchievementOut, status_code=201)
async def create_achievement(
    payload: ProfileAchievementIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileAchievementOut:
    """Add an award, honor, publication or extracurricular highlight."""
    item = await _service(db).create_achievement(user.id, payload)
    return ProfileAchievementOut.model_validate(item)


@router.patch("/achievements/{item_id}", response_model=ProfileAchievementOut)
async def update_achievement(
    item_id: uuid.UUID,
    payload: ProfileAchievementPatch,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileAchievementOut:
    """Edit an achievement."""
    item = await _service(db).update_achievement(item_id, user.id, payload)
    return ProfileAchievementOut.model_validate(item)


@router.delete("/achievements/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_achievement(
    item_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an achievement."""
    await _service(db).delete_achievement(item_id, user.id)


@router.get("/cv-readiness", response_model=CvReadiness)
async def cv_readiness(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CvReadiness:
    """Deterministic CV-readiness report (section coverage)."""
    return await _service(db).readiness(user.id)
