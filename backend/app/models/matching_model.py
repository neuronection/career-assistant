import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TZDateTime,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class MatchInsight(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user evaluation of a job: AI score + reasons, user score + status."""

    __tablename__ = "match_insights"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_match_user_job"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    ai_score: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    ai_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ai_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ai_positives: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    ai_negatives: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    prerequisites: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    ai_model: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    ai_generated_at: Mapped[Optional[datetime]] = mapped_column(
        TZDateTime(), nullable=True
    )

    # Deterministic fit layer (Phase 22) — no AI cost, recomputed on save.
    fit_score: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    fit_breakdown: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
    fit_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    user_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Feed state (Phase 24): status stays semantic ("not for me, because…"),
    # these are pure curation/impression marks. Unread = seen_at IS NULL.
    seen_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)
    saved_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)
    hidden_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)
