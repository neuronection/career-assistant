import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.schemas.taxonomy import (
    InterestTagOut,
    SkillOut,
    SkillUpdateIn,
    TagCreateIn,
    TagUpdateIn,
)
from app.services.deps import get_current_user, require_admin
from app.services.taxonomy_service import ReferenceCountError, TaxonomyService

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("/interests", response_model=list[InterestTagOut])
async def interests(
    category: str | None = Query(default=None),
    kind: str | None = Query(default=None, pattern="^(topic|industry)$"),
    include_deprecated: bool = Query(default=True),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InterestTagOut]:
    """Interest taxonomy (optionally by category/kind; deprecated hidden on demand)."""
    rows = await TaxonomyService(db).interests(
        category, kind=kind, include_deprecated=include_deprecated
    )
    return [InterestTagOut.model_validate(r) for r in rows]


@router.get("/skills", response_model=list[SkillOut])
async def skills(
    category: str | None = Query(default=None),
    include_deprecated: bool = Query(default=True),
    include_proposed: bool = Query(default=False),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SkillOut]:
    """Skill ontology (admin surfaces see every lifecycle row on demand)."""
    if include_deprecated and include_proposed:
        status_filter = None
    elif include_proposed:
        statuses = {"proposed", "active"}
        rows = await TaxonomyService(db).skills(category=category, status=None)
        return [SkillOut.model_validate(r) for r in rows if r.status in statuses]
    elif include_deprecated:
        statuses = {"deprecated", "active"}
        rows = await TaxonomyService(db).skills(category=category, status=None)
        return [SkillOut.model_validate(r) for r in rows if r.status in statuses]
    else:
        status_filter = "active"
    rows = await TaxonomyService(db).skills(category=category, status=status_filter)
    return [SkillOut.model_validate(r) for r in rows]


@router.post("/interests", response_model=InterestTagOut, status_code=201)
async def create_interest(
    data: TagCreateIn,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InterestTagOut:
    """Create an interest tag (admin; key becomes the stable slug)."""
    try:
        tag = await TaxonomyService(db).create_interest(data.model_dump())
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return InterestTagOut.model_validate(tag)


@router.post("/skills", response_model=SkillOut, status_code=201)
async def create_skill(
    data: TagCreateIn,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SkillOut:
    """Create a skill (admin; key becomes the stable slug, active on create)."""
    try:
        tag = await TaxonomyService(db).create_skill(data.model_dump())
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return SkillOut.model_validate(tag)


@router.put("/interests/{tag_id}", response_model=InterestTagOut)
async def update_interest(
    tag_id: uuid.UUID,
    data: TagUpdateIn,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InterestTagOut:
    """Edit an interest tag (admin; key immutable, deprecate instead of delete)."""
    try:
        tag = await TaxonomyService(db).update_interest(
            tag_id, data.model_dump(exclude_none=False)
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return InterestTagOut.model_validate(tag)


@router.put("/skills/{skill_id}", response_model=SkillOut)
async def update_skill(
    skill_id: uuid.UUID,
    data: SkillUpdateIn,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SkillOut:
    """Edit a skill (admin; key immutable, lifecycle via status)."""
    try:
        skill = await TaxonomyService(db).update_skill(
            skill_id, data.model_dump(exclude_none=False)
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return SkillOut.model_validate(skill)


@router.delete("/interests/{tag_id}")
async def delete_interest(
    tag_id: uuid.UUID,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete an unreferenced interest tag (admin); 409 when referenced."""
    try:
        return await TaxonomyService(db).delete_interest(tag_id)
    except ReferenceCountError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "job_refs": exc.job_refs,
                "profile_refs": exc.profile_refs,
            },
        ) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: uuid.UUID,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete an unreferenced skill (admin); 409 when referenced."""
    try:
        return await TaxonomyService(db).delete_skill(skill_id)
    except ReferenceCountError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "job_refs": exc.job_refs,
                "profile_refs": exc.profile_refs,
            },
        ) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
