"""Demand history (Phase 20): point-in-time market snapshots.

`growth_service.market_snapshot()` recomputes from the live postings
window on every call — this table persists periodic captures so trends
survive posting expiry. Analytics only, never a fit input or
demand-rule factor. One snapshot per scope per day (unique); scope is
a typed XOR: family_key for family scope, job_id FK for job
scope, `scope_key` carries the non-unique-participant key so the
per-day unique works on both dialects (NULLs are distinct in SQL
unique constraints).
"""

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    TZDateTime,
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class MarketSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One captured market snapshot for a family or job scope."""

    __tablename__ = "market_snapshots"
    __table_args__ = (
        CheckConstraint(
            "(scope_kind = 'family' AND family_key IS NOT NULL AND job_id IS NULL)"
            " OR (scope_kind = 'job' AND job_id IS NOT NULL AND family_key IS NULL)",
            name="scope_shape",
        ),
        UniqueConstraint(
            "scope_kind",
            "scope_key",
            "capture_date",
            name="uq_market_snapshots_scope_day",
        ),
        Index("ix_market_snapshots_job", "job_id"),
    )

    scope_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(120), nullable=False)
    family_key: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True
    )
    capture_date: Mapped[date] = mapped_column(Date, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    payload: Mapped[dict] = mapped_column(StructuredJSON, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    thin_sample: Mapped[bool] = mapped_column(Boolean, nullable=False)
