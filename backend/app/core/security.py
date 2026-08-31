from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import jwt

from app.core.config import settings


class AuthError(Exception):
    """Raised when authentication fails."""


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: UUID, token_version: int = 1) -> str:
    """Create a signed JWT access token for a user.

    `ver` carries the user's token_version so tokens die on revocation.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> tuple[UUID, int]:
    """Decode and validate a JWT; returns (user_id, token_version)."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid token") from exc
    sub = payload.get("sub")
    if not sub:
        raise AuthError("Invalid token payload")
    return UUID(sub), int(payload.get("ver", 0))
