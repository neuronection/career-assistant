"""Scheduler (Phase 29): one robust engine for everything periodic.

Layering rule: the scheduler decides WHEN, the plan-12 queue decides
WHAT/HOW — a tick only enqueues `background_jobs` rows; no business
logic lives here. payload_hash is computed in Python (canonical JSON,
plan 42 hash policy) so the (kind, owner, payload_hash) uniqueness is
real on every dialect."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Schedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One periodic task; trigger params + task payload are typed JSONB."""

    __tablename__ = "schedules"
    __table_args__ = (
        UniqueConstraint(
            "kind",
            "owner_user_id",
            "payload_hash",
            name="uq_schedules_kind_owner_payload",
        ),
        CheckConstraint(
            "kind IN ('system_source_sync', 'system_digest', "
            "'system_demand_import', 'system_refit_sweep', "
            "'user_saved_search', 'user_checkin')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "misfire_policy IN ('asap', 'skip', 'next_slot')",
            name="misfire_allowed",
        ),
        CheckConstraint(
            "task IS NULL OR task IN ('posting_sync', 'digest', "
            "'saved_search_run', 'fit_refit')",
            name="task_allowed",
        ),
        Index("ix_schedules_next_run", "next_run_at"),
    )

    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # BackgroundJobType value; NULL for banner-only kinds (user_checkin).
    task: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    trigger: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    payload: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    last_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    misfire_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="asap"
    )
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
