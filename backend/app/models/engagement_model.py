"""Engagement layer (Phases 24 + 36): search history + notification stack.

Plan 36's three-concern split: `notifications` holds immutable *events*,
`notification_recipients` the per-user *inbox state*, and
`notification_deliveries` the per-channel *dispatch log*. Every emitter
funnels through NotificationService.emit — no feature writes rows directly.
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
from app.models.enums import (
    DeliveryStatus,
    NotificationSeverity,
    NotificationStatus,
)


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
            "scope IN ('catalog', 'rankings', 'universities', 'postings')",
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
    # Channel slots are plan 36's registry; `in_app` is the only always-on one.
    default_channels: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=lambda: ["in_app"]
    )
    mutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Deep link into the owning feature's settings (preferences UI one click away).
    manage_url: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One emitted notification *event* (immutable, recipient-agnostic).

    `dedup_key` collapses emits while its TTL is live; emitters embed the
    recipient scope in the key (e.g. ``fit-threshold:{user}:{job}:{bucket}``)
    so the event-level partial unique index stays per-user. `source_ref` is
    the typed pointer ({posting_ref | job_id | run_id | goal_id …}) the
    inbox threads by — one career item, one thread.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "uq_notifications_dedup_key",
            "dedup_key",
            unique=True,
            sqlite_where=text("dedup_key IS NOT NULL"),
            postgresql_where=text("dedup_key IS NOT NULL"),
        ),
        Index("ix_notifications_kind_created", "kind_id", "created_at"),
    )

    kind_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_kinds.id", ondelete="RESTRICT"), nullable=False
    )
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NotificationSeverity.INFO.value
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Typed extras: {job_id, family_key, link, score, actions[], source_ref…}.
    payload: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    source_ref: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
    # Emit-time collapse: same key while the TTL is live ⇒ no new event.
    dedup_key: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    dedup_expires_at: Mapped[Optional[datetime]] = mapped_column(
        TZDateTime(), nullable=True
    )


class NotificationRecipient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Inbox state per (event, recipient) — the row the center renders."""

    __tablename__ = "notification_recipients"
    __table_args__ = (
        UniqueConstraint(
            "notification_id", "user_id", name="uq_notification_recipients_pair"
        ),
        Index("ix_notification_recipients_user_status", "user_id", "status"),
        CheckConstraint(
            "status IN ('unread', 'read', 'dismissed')",
            name="status_allowed",
        ),
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=NotificationStatus.UNREAD.value,
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        TZDateTime(), nullable=True
    )


class NotificationDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Channel dispatch log per (event, recipient, channel) — answers "did
    the desktop toast fire?" without guessing."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "notification_id",
            "user_id",
            "channel",
            name="uq_notification_deliveries_triple",
        ),
        Index(
            "ix_notification_deliveries_user_channel",
            "user_id",
            "channel",
            "created_at",
        ),
        CheckConstraint(
            "channel IN ('in_app', 'desktop', 'browser')",
            name="channel_allowed",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'delivered', 'failed')",
            name="status_allowed",
        ),
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DeliveryStatus.PENDING.value,
    )
    error: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    subscription_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("notification_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )


class NotificationSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A browser push subscription (web mode; VAPID, plan 36).

    One row per user device; `endpoint_hash` (canonical sha256 of the
    endpoint URL) carries the uniqueness so re-subscribes upsert cleanly.
    """

    __tablename__ = "notification_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_notification_subs_device"),
        Index(
            "uq_notification_subs_endpoint",
            "endpoint_hash",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[str] = mapped_column(String(120), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(1000), nullable=False)
    endpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(200), nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class NotificationKindPref(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user × per-kind preference (enable/disable + channel override).

    NULL fields fall back to the kind row's defaults, so new kinds light up
    sanely without per-user seeding.
    """

    __tablename__ = "notification_kind_prefs"
    __table_args__ = (
        UniqueConstraint("user_id", "kind_id", name="uq_notification_kind_prefs"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_kinds.id", ondelete="RESTRICT"), nullable=False
    )
    enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    channels: Mapped[Optional[list]] = mapped_column(StructuredJSON, nullable=True)


class NotificationRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's alert rule; params validated against the rule kind.

    Defaults apply when no row exists: fit ≥ 7, max 5/day, 7-day per-job
    cooldown. One rule per (user, kind).
    """

    __tablename__ = "notification_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", name="uq_notification_rules_user_kind"),
        CheckConstraint(
            "kind IN ('fit_threshold', 'new_in_family', 'new_posting_match')",
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
