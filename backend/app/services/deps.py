"""Shared API dependencies built on the family auth-kit.

Identity verification happens in exactly one place — the kit's
`SessionAuthMiddleware` / `nx_auth.deps` (token + instance rules + live
user row, identity-auth §4/§8). These dependencies map the verified
`Principal` onto career's ORM rows for the existing handlers; the
dependency names are the family surface (§12): `get_current_user`,
`require_admin`.
"""

from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from nx_auth import get_current_user as get_current_principal
from nx_auth.principal import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.profile_context import active_profile_id
from app.models.user_model import Profile, User


async def get_current_user(
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> User:
    """The authenticated user's row for handlers that need the ORM object."""
    try:
        user_id = UUID(principal.user_id)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated") from None
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


def get_profile_id(
    request: Request,
    x_profile_id: str | None = Header(default=None),
) -> str:
    """The request's bound profile (identity-auth §15, family dep surface).

    `ProfileBindingMiddleware` validated ownership already — trust its
    context, never the raw header.
    """
    del request, x_profile_id
    profile_id = active_profile_id()
    if profile_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Profile-Id required")
    return profile_id


async def get_profile_for_user(db: AsyncSession, user_id: UUID) -> Profile:
    """The user's active profile row — §15 bound, §6 fallback.

    Request-scoped callers get the profile the middleware bound for the
    request (ownership validated there); everything else (background
    jobs, account surfaces) resolves the auto-provisioned Default
    profile. Fetch-or-create keeps the pre-P3b contract for callers.
    """
    from app.services.profiles_service import ensure_default_profile

    return await ensure_default_profile(db, user_id)


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Guard for global (system-scope) settings management."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user
