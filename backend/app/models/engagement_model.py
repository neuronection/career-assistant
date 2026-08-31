"""Engagement layer (Phase 24): search history + notification storage.

Notification *delivery* (fan-out, channels, preferences) is plan 36's
unified stack — this is the career-side event store the emitters write
through; plan 36 reshapes it without a compatibility path.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    TZDateTime,
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.models.enums import NotificationSeverity


class SearchHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One remembered catalog/rankings/universities search per user.

    Writes are debounced server-side (same query+filters within 30 min
    updates the row); `saved` marks a saved search for later reuse by
    alert rules (plan 29 schedules them).
    """

    __tablename__ = "search_history"
    __table_args__ = (
        Index("ix_search_history_user_saved", "user_id", "saved"),
        CheckConstraint(
            "scope IN ('catalog', 'rankings', 'universities')",
            name="scope_allowed",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False, default="")
    filters: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    # Canonical-JSON hash of `filters` (sorted keys, stable types) so the
    # debounce window is one indexed comparison on every dialect.
    filters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    saved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class NotificationKind(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The kind registry every emitter resolves through (plan 42 rule F).

    Seeded rows are system data; features add kinds with their phase. The
    `key` is the stable string space shared with plan 36's registry.
    """

    __tablename__ = "notification_kinds"

    key: Mapped[str] = mapped_column(
        String(60), unique=True, index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    group: Mapped[str] = mapped_column(String(40), nullable=False, default="career")
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NotificationSeverity.INFO.value
    )
    default_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Channel slots are plan 36's registry; `in_app` is the only live one.
    default_channels: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=lambda: ["in_app"]
    )
    mutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One emitted notification event for one user (immutable content)."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "uq_notifications_user_dedup_key",
            "user_id",
            "dedup_key",
            unique=True,
            sqlite_where=text("dedup_key IS NOT NULL"),
            postgresql_where=text("dedup_key IS NOT NULL"),
        ),
        Index("ix_notifications_user_read", "user_id", "read_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_kinds.id", ondelete="RESTRICT"), nullable=False
    )
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NotificationSeverity.INFO.value
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Typed extras: {job_id, family_key, link, score, actions_hint…}.
    payload: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    # Emit-time collapse: same key while the TTL is live ⇒ no new row.
    dedup_key: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    dedup_expires_at: Mapped[Optional[datetime]] = mapped_column(
        TZDateTime(), nullable=True
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)


class NotificationRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's alert rule; params validated against the rule kind.

    Defaults apply when no row exists: fit ≥ 7, max 5/day, 7-day per-job
    cooldown. One rule per (user, kind).
    """

    __tablename__ = "notification_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", name="uq_notification_rules_user_kind"),
        CheckConstraint(
            "kind IN ('fit_threshold', 'new_in_family')",
            name="kind_supported",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    params: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class NotificationPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user channel preferences (Phase 30; plan 36 extends per-kind).

    Defaults apply when no row exists: desktop channel on, no quiet
    hours. Dispatch guards (quiet hours) run here — the inbox row is
    always written regardless.
    """

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_notification_preferences_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    desktop_channel_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    quiet_hours: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
