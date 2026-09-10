from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AccountLockedError, ValidationError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user_model import Profile, User
from app.schemas.auth import RegisterIn
from app.schemas.profile import (
    DEFAULT_ACADEMICS,
    DEFAULT_BASICS,
    DEFAULT_CONSTRAINTS,
    DEFAULT_WORK_PREFERENCES,
)


class AuthService:
    """Registration and login flows."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(self, data: RegisterIn) -> tuple[User, str]:
        """Create a user + default profile; the first user becomes admin."""
        existing = await self.db.execute(
            select(User).where(User.email == data.email.lower())
        )
        if existing.scalars().first():
            raise ValidationError("Email already registered")
        count_rows = await self.db.execute(select(func.count(User.id)))
        is_first = (count_rows.scalar() or 0) == 0
        user = User(
            email=data.email.lower(),
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            is_admin=is_first,
        )
        self.db.add(user)
        await self.db.flush()
        self.db.add(
            Profile(
                user_id=user.id,
                basics=dict(DEFAULT_BASICS),
                academics=dict(DEFAULT_ACADEMICS),
                work_preferences=dict(DEFAULT_WORK_PREFERENCES),
                constraints=dict(DEFAULT_CONSTRAINTS),
            )
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user, create_access_token(user.id, user.token_version)

    async def login(self, email: str, password: str) -> tuple[User, str]:
        """Verify credentials; returns (user, token).

        Consecutive failures above LOCKOUT_THRESHOLD lock the account for
        LOCKOUT_MINUTES (brute-force protection).
        """
        result = await self.db.execute(select(User).where(User.email == email.lower()))
        user = result.scalars().first()
        if user is not None and user.locked_until is not None:
            locked_until = _as_aware(user.locked_until)
            if locked_until > datetime.now(timezone.utc):
                raise AccountLockedError(
                    "Account temporarily locked after repeated failed logins"
                )
            user.locked_until = None
            user.failed_login_attempts = 0
        if user is None or not verify_password(password, user.password_hash):
            if user is not None:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= settings.LOCKOUT_THRESHOLD:
                    user.locked_until = datetime.now(timezone.utc) + timedelta(
                        minutes=settings.LOCKOUT_MINUTES
                    )
                    user.failed_login_attempts = 0
                await self.db.commit()
            raise ValidationError("Invalid email or password")
        if not user.is_active:
            raise ValidationError("Account disabled")
        user.failed_login_attempts = 0
        await self.db.commit()
        return user, create_access_token(user.id, user.token_version)

    async def revoke_sessions(self, user: User) -> int:
        """Invalidate every outstanding token for the user; returns the version."""
        user.token_version += 1
        await self.db.commit()
        return user.token_version

    async def get_user(self, user_id: UUID) -> User | None:
        """Fetch a user by id."""
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalars().first()


def _as_aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; compare on the UTC clock regardless."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
