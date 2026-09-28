"""Profile CRUD (identity-auth §12) — `/api/v1/profiles`.

List own / create / PATCH (rename, set Default, color) / DELETE.
Foreign or unknown ids hide behind 404 (§7). Deleting the last profile
re-provisions Default (§6); profile-scoped rows cascade (§12).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.deps import get_current_user
from app.services import profiles_service

router = APIRouter(prefix="/profiles", tags=["profiles"])


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str | None = Field(default=None, max_length=16)


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    color: str | None = Field(default=None, max_length=16)
    is_default: bool | None = None


class ProfileOut(BaseModel):
    id: str
    name: str
    color: str | None = None
    is_default: bool


def _out(profile) -> ProfileOut:
    return ProfileOut(
        id=str(profile.id),
        name=profile.name,
        color=profile.color,
        is_default=bool(profile.is_default),
    )


@router.get("", response_model=list[ProfileOut])
async def get_profiles(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ProfileOut]:
    return [_out(p) for p in await profiles_service.list_profiles(db, user.id)]


@router.post("", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
async def add_profile(
    body: ProfileIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileOut:
    profile = await profiles_service.create_profile(db, user.id, body.name, body.color)
    await db.commit()
    return _out(profile)


@router.patch("/{profile_id}", response_model=ProfileOut)
async def patch_profile(
    profile_id: str,
    body: ProfilePatch,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileOut:
    profile = await profiles_service.get_owned_profile(db, user.id, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "profile not found")
    if body.name is not None:
        profile.name = body.name.strip() or "Profile"
    if body.color is not None or "color" in body.model_fields_set:
        profile.color = body.color
    if body.is_default:
        await profiles_service.set_default_profile(db, user.id, profile_id)
    await db.commit()
    return _out(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_profile(
    profile_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an owned profile (identity-auth §12): profile-scoped rows
    cascade; deleting the last profile re-provisions Default."""
    if await profiles_service.delete_profile(db, user.id, profile_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "profile not found")
    await db.commit()
