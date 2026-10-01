"""Family-normative identity tables (identity-auth §5): `auth_sessions`,
`instance_settings`, `audit_events`.

Career owns these models (its one metadata/registry stays self-contained;
never import the kit's ORM classes — gotcha §5.11) and adapts them to
the `nx_auth` store protocols in `app/auth/stores.py`. `users` lives in
`app.models.user_model` next to its `profiles` product rows.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TZDateTime, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuthSession(UUIDPrimaryKeyMixin, Base):
    """Refresh families — rotation + reuse detection (§5 `auth_sessions`).

    One row per signed-in device ("family"). Stores sha256 of the current
    refresh `jti` — never raw tokens. `created_at` is a product addition
    (§5 allows additions): the device list shows when each family began.
    """

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_jti_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    client_label: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=_utcnow)


class InstanceSetting(Base):
    """Instance access-mode facts (§5 `instance_settings`) — written only
    at initialization (§4: DB authoritative, init-only, fail-closed)."""

    __tablename__ = "instance_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only auth/admin audit trail (§5 `audit_events`)."""

    __tablename__ = "audit_events"

    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(), nullable=False, default=_utcnow, index=True
    )


__all__ = ["AuditEvent", "AuthSession", "InstanceSetting"]
