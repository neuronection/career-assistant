from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import AuthError, decode_access_token
from app.models.user_model import Profile, User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the Authorization header."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        user_id, token_version = decode_access_token(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if token_version != user.token_version:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Token revoked; sign in again"
        )
    return user


async def get_profile_for_user(db: AsyncSession, user_id: UUID) -> Profile:
    """Fetch (creating if absent) the profile for a user."""
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalars().first()
    if profile is None:
        profile = Profile(user_id=user_id)
        db.add(profile)
        await db.flush()
    return profile


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Guard for global (system-scope) AI settings management."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user
