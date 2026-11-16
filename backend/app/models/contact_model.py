"""Outreach contacts and their interaction log (plan 213 W1).

Flat, user-owned records: no enrichment, no scraping, no cadence. A
contact is a person around an application; an interaction is one logged
moment (a note, an email sent manually, a call). Application follow-ups
stay on `applications.next_followup_at`.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    TZDateTime,
    UUIDPrimaryKeyMixin,
)

CONTACT_SOURCES = ("manual", "application_migration", "import")
INTERACTION_KINDS = (
    "intro",
    "follow_up",
    "thank_you",
    "referral",
    "informational",
    "other",
)
INTERACTION_CHANNELS = ("email", "call", "meeting", "message", "other")


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One person in the user's outreach log."""

    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint(
            "source IN ('manual', 'application_migration', 'import')",
            name="source_allowed",
        ),
        Index(
            "uq_contacts_user_email_key",
            "user_id",
            "email_key",
            unique=True,
            postgresql_where=text("email_key IS NOT NULL"),
            sqlite_where=text("email_key IS NOT NULL"),
        ),
        Index("ix_contacts_user_last_contacted", "user_id", "last_contacted_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    org: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Normalized nullable key: partial unique index per user; empty emails
    # are allowed to repeat.
    email_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    profile_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    last_contacted_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")


class ContactInteraction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One logged outreach moment for a contact."""

    __tablename__ = "contact_interactions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('intro', 'follow_up', 'thank_you', 'referral', 'informational', 'other')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "channel IN ('email', 'call', 'meeting', 'message', 'other')",
            name="channel_allowed",
        ),
        Index("ix_contact_interactions_contact_at", "contact_id", "at"),
        Index("ix_contact_interactions_application", "application_id"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
