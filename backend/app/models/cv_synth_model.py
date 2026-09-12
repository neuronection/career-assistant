"""Synthesized CV items: a user-level library of AI-written or manual
variants over context source items (plan 62).

A variant stores the *text*, its typed source refs (the plan-47
`{source_key, item_id}` shape), and a content hash of each source at
generation time — so staleness is detectable when the profile item
changes. Variants are user-level and reusable across CVs: matching is
deterministic (active → language → posting-scoped beats generic →
variant order), and a per-CV `synth_mode` decides whether the context
engine swaps them in. Nothing here writes the profile: these are CV
artifacts. Deleting a source item leaves rows `orphaned`, never
silently dropped.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class CvSynthItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One synthesized variant over one (or a few) profile item(s)."""

    __tablename__ = "cv_synth_items"
    __table_args__ = (
        CheckConstraint("scope IN ('item', 'summary')", name="scope_allowed"),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')", name="status_allowed"
        ),
        CheckConstraint("source IN ('ai', 'manual')", name="source_allowed"),
        CheckConstraint("variant_key <> ''", name="variant_key_present"),
        Index("ix_cv_synth_items_user_status", "user_id", "status"),
        Index("ix_cv_synth_items_user_set", "user_id", "source_set_hash"),
        Index("ix_cv_synth_items_user_posting", "user_id", "target_posting_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    variant_key: Mapped[str] = mapped_column(String(60), nullable=False)
    target_posting_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_postings.id", ondelete="SET NULL"), nullable=True
    )
    source_refs: Mapped[list] = mapped_column(StructuredJSON, nullable=False)
    source_state: Mapped[list] = mapped_column(StructuredJSON, nullable=False)
    source_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(StructuredJSON, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(StructuredJSON, nullable=False)
    voice: Mapped[dict] = mapped_column(StructuredJSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
