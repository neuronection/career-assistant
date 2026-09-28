"""Per-user profile services (identity-auth §5/§6/§12).

Auto-provisioning rule (§6): a user is never without a profile — user
creation provisions Default in the same transaction, and deleting the
last profile re-provisions it. Exactly one `is_default` per user
(enforced here, study's `services/platform/profiles.py` pattern).

Mutating helpers flush; the caller's transaction commits (career's
request/unit-of-work style).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.profile_context import active_profile_id, active_user_id
from app.models.user_model import Profile


def _norm(value: str | UUID | None) -> UUID | None:
    """Canonicalize an id so comparisons never depend on input formatting."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _default_sections() -> dict:
    """The product JSON defaults every fresh profile starts with."""
    from app.schemas.profile import (
        DEFAULT_ACADEMICS,
        DEFAULT_BASICS,
        DEFAULT_CONSTRAINTS,
        DEFAULT_WORK_PREFERENCES,
    )

    return {
        "basics": dict(DEFAULT_BASICS),
        "academics": dict(DEFAULT_ACADEMICS),
        "work_preferences": dict(DEFAULT_WORK_PREFERENCES),
        "constraints": dict(DEFAULT_CONSTRAINTS),
    }


async def create_profile(
    db: AsyncSession,
    user_id: str | UUID,
    name: str,
    color: str | None = None,
    *,
    is_default: bool = False,
) -> Profile:
    profile = Profile(
        user_id=_norm(user_id),
        name=name.strip() or "Profile",
        color=color,
        is_default=is_default,
        **_default_sections(),
    )
    db.add(profile)
    await db.flush()
    return profile


async def get_owned_profile(
    db: AsyncSession, user_id: str | UUID, profile_id: str | UUID
) -> Profile | None:
    """The profile row when it exists AND belongs to the user (§7 —
    callers map `None` to a hidden 404)."""
    key = _norm(profile_id)
    if key is None:
        return None
    profile = await db.get(Profile, key)
    if profile is None or _norm(profile.user_id) != _norm(user_id):
        return None
    return profile


async def list_profiles(db: AsyncSession, user_id: str | UUID) -> list[Profile]:
    rows = await db.execute(
        select(Profile)
        .where(Profile.user_id == _norm(user_id))
        .order_by(Profile.created_at, Profile.id)
    )
    return list(rows.scalars().all())


async def get_or_create_default(db: AsyncSession, user_id: str | UUID) -> Profile:
    rows = await db.execute(
        select(Profile)
        .where(Profile.user_id == _norm(user_id), Profile.is_default.is_(True))
        .limit(1)
    )
    profile = rows.scalars().first()
    if profile is not None:
        return profile
    owned = await list_profiles(db, user_id)
    if owned:
        owned[0].is_default = True
        await db.flush()
        return owned[0]
    profile = await create_profile(db, user_id, "Default", is_default=True)
    await db.flush()
    return profile


async def ensure_default_profile(
    db: AsyncSession, user_id: str | UUID | None = None
) -> Profile:
    """The request's bound profile (§15, bound by the middleware), else
    the user's auto-provisioned Default profile.

    Background jobs run outside request context and pass the owning
    user explicitly; with neither, fall back to the oldest profile
    (single-user desktop instances have exactly one).
    """
    owner = _norm(user_id) or _norm(active_user_id())
    requested = _norm(active_profile_id())
    if requested is not None:
        profile = await db.get(Profile, requested)
        if profile is not None and (owner is None or _norm(profile.user_id) == owner):
            return profile
    if owner is not None:
        return await get_or_create_default(db, owner)
    rows = await db.execute(
        select(Profile).order_by(Profile.created_at, Profile.id).limit(1)
    )
    profile = rows.scalars().first()
    if profile is not None:
        return profile
    raise RuntimeError("no profile exists — profiles are provisioned with their user")


async def set_default_profile(
    db: AsyncSession, user_id: str | UUID, profile_id: str | UUID
) -> Profile | None:
    profile = await get_owned_profile(db, user_id, profile_id)
    if profile is None:
        return None
    for other in await list_profiles(db, user_id):
        other.is_default = other.id == profile.id
    await db.flush()
    return profile


async def delete_profile(
    db: AsyncSession, user_id: str | UUID, profile_id: str | UUID
) -> Profile | None:
    """Delete an owned profile (§12): profile-scoped rows cascade.

    Deleting the last profile re-provisions Default (§6); losing the
    default promotes the oldest remaining one. Returns None when the
    profile is unknown or outside the user's ownership (hidden-404).
    """
    profile = await get_owned_profile(db, user_id, profile_id)
    if profile is None:
        return None
    was_default = bool(profile.is_default)
    await _delete_photo_document(db, profile)
    await db.delete(profile)
    await db.flush()
    remaining = await list_profiles(db, user_id)
    if not remaining:
        await create_profile(db, user_id, "Default", is_default=True)
    elif was_default:
        remaining[0].is_default = True
    await db.flush()
    return profile


async def _delete_photo_document(db: AsyncSession, profile: Profile) -> None:
    """The profile photo is profile-scoped product data (§12 cascade):
    its `documents` row and uploaded file go with the profile."""
    if profile.photo_document_id is None:
        return
    from app.models.document_model import Document
    from app.services.document_service import DocumentService

    document = await db.get(Document, profile.photo_document_id)
    if document is None:
        return
    file_path = DocumentService.upload_file_path(document)
    if file_path is not None and file_path.is_file():
        try:
            file_path.unlink()
        except OSError:
            pass
    await db.delete(document)


async def touch_last_used(db: AsyncSession, profile_id: str | UUID) -> None:
    key = _norm(profile_id)
    if key is None:
        return
    profile = await db.get(Profile, key)
    if profile is not None:
        profile.last_used_at = datetime.now(UTC)
        await db.flush()


async def last_used_profile(db: AsyncSession, user_id: str | UUID) -> Profile | None:
    """Desktop fallback (§15): the user's most recently used profile."""
    rows = await db.execute(
        select(Profile)
        .where(Profile.user_id == _norm(user_id))
        .order_by(
            Profile.last_used_at.desc().nulls_last(), Profile.created_at, Profile.id
        )
        .limit(1)
    )
    return rows.scalars().first()
