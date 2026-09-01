"""Instance-level key/value settings (plan 36).

Small curated store for values that are DB-only by repo discipline (no
env vars for feature config): VAPID keys, feature flags introduced by
later phases. Sensitive values are Fernet-encrypted via
``app.core.encryption`` before they land in `value`.
"""

from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin


class AppSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One named setting; `key` is the stable contract between modules."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    description: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
