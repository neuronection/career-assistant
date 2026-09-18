"""HITL profile proposals (plan 77).

Every profile mutation proposed by the chatbot lands here first — a
detached card the user resolves (approve/reject). Applying goes through
the same services the REST forms use; the model never writes user data
directly. Cards are first-class data: they outlive the chat session that
produced them (SET NULL, never CASCADE) and expire after a TTL.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TZDateTime,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

_STATUS_ALLOWED = (
    "status IN ('pending', 'approved', 'rejected', 'conflict', 'expired', 'reverted')"
)
_ACTION_ALLOWED = "action IN ('create', 'update', 'delete')"
_KIND_ALLOWED = (
    "kind IN ('experience_item', 'education_item', 'certification', "
    "'profile_achievement', 'user_skill', 'profile_section', 'cv_synth', "
    "'cv_set_bullets')"
)
_SOURCE_ALLOWED = "source IN ('chat')"


class ProfileProposal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One proposed mutation over a profile entity, awaiting resolution."""

    __tablename__ = "profile_proposals"
    __table_args__ = (
        CheckConstraint(_STATUS_ALLOWED, name="status_allowed"),
        CheckConstraint(_ACTION_ALLOWED, name="action_allowed"),
        CheckConstraint(_KIND_ALLOWED, name="kind_allowed"),
        CheckConstraint(_SOURCE_ALLOWED, name="source_allowed"),
        Index("ix_profile_proposals_user_status", "user_id", "status", "created_at"),
        Index("ix_profile_proposals_entity", "user_id", "entity_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    # Target row for update/delete (None for create and section patches).
    # Plain UUID, no FK: the target table depends on `kind` (typed ref per
    # plan 42 — ownership is enforced by the kind handlers at load time).
    entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    entity_label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Typed patch in the REST schema shape; delete ops carry a FULL entity
    # snapshot (revert + conflict messaging).
    payload_json: Mapped[dict] = mapped_column(StructuredJSON, nullable=False)
    # Entity.updated_at snapshot at creation — mismatch at approve = conflict.
    base_updated_at: Mapped[Optional[datetime]] = mapped_column(
        TZDateTime(), nullable=True
    )
    # Field-level before/after rows, computed server-side at creation.
    diff_json: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="chat")
    # Lineage back to the chat turn and the audited model call. SET NULL:
    # proposals survive session/message deletion (first-class data).
    chat_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True
    )
    chat_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    ai_generation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("ai_generations.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)
    resolve_error: Mapped[str] = mapped_column(
        String(400), nullable=False, default="", server_default=""
    )
