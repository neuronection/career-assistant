from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AccountLockedError, DomainError
from app.core.ratelimit import limiter
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from app.services.auth_service import AuthService
from app.services.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(data: RegisterIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    """Create an account and return a bearer token."""
    try:
        _, token = await AuthService(db).register(data)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return TokenOut(access_token=token)


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    """Exchange credentials for a bearer token (rate limited per IP + email)."""
    retry_after = (
        limiter.check("auth_email", data.email.lower())
        if settings.RATE_LIMIT_ENABLED
        else None
    )
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many login attempts for this account",
            headers={"Retry-After": str(retry_after)},
        )
    try:
        _, token = await AuthService(db).login(data.email, data.password)
    except AccountLockedError as exc:
        raise HTTPException(status.HTTP_423_LOCKED, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return TokenOut(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(user=Depends(get_current_user)) -> UserOut:
    """Current authenticated user."""
    return UserOut.model_validate(user)


@router.post("/revoke-sessions")
async def revoke_sessions(
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Invalidate every outstanding token for the caller ("sign out everywhere")."""
    version = await AuthService(db).revoke_sessions(user)
    return {"revoked": True, "token_version": version}
