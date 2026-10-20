"""Follow-up configuration + signed subscription tokens (plan 113).

`followup_rules` is the per-user follow-up cadence (116's settings UI);
`user_feed_tokens` carries hashed calendar/RSS subscription tokens so
rotation and revocation never need a migration.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    TZDateTime,
    UUIDPrimaryKeyMixin,
)
from app.models.enums import FeedTokenKind


class FollowupRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user follow-up cadence and channel overrides."""

    __tablename__ = "followup_rules"
    __table_args__ = (UniqueConstraint("user_id", name="uq_followup_rules_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Ordered ints: the +7d/+14d sweep generalizes without a migration.
    cadence_days: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=lambda: [7, 14]
    )
    milestone_checkins: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Per-kind channel routing: default | followup_due |
    # interview_checkin | offer_checkin.
    channels: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)


class UserFeedToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A hashed signed-subscription token (`.ics`, saved-search RSS)."""

    __tablename__ = "user_feed_tokens"
    __table_args__ = (
        CheckConstraint("kind IN ('ics', 'rss')", name="kind_allowed"),
        Index("ix_user_feed_tokens_user_kind", "user_id", "kind"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default=FeedTokenKind.ICS.value)
    # sha256 of the secret; the plaintext is shown once, never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # {} = everything visible to the user; {"saved_search_id": …} scopes it.
    scope: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_feed_tokens.id", ondelete="SET NULL"), nullable=True
    )
