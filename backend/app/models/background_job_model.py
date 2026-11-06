import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    TZDateTime,
    UUIDPrimaryKeyMixin,
)

# The DB-level single-active-run and request-replay invariants (plan 51 Q1a,
# contract ``BACKGROUND_JOB_SEAMS``): partial unique indexes over the active
# statuses only, so terminal rows never block a retry.
ACTIVE_JOB_STATUSES = ("queued", "running")
_ACTIVE_JOB_STATUS_SQL = "status IN ('queued', 'running')"
_IDEMPOTENCY_WHERE = text(f"idempotency_key IS NOT NULL AND {_ACTIVE_JOB_STATUS_SQL}")
_LOCK_KEY_WHERE = text(f"lock_key IS NOT NULL AND {_ACTIVE_JOB_STATUS_SQL}")


class BackgroundJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable queue entry for long-running AI work.

    Claim-based: the worker flips queued → running with a conditional UPDATE
    (rowcount decides the winner), so no dialect-specific locking is needed.

    ``idempotency_key`` and ``lock_key`` are nullable; the two partial unique
    indexes enforce the family contract's request-replay and
    one-active-run-per-space invariants at the database. The runtime that
    allocates them lands in plan 51 Q1b.
    """

    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_user_id", "user_id"),
        Index("ix_background_jobs_status_created", "status", "created_at"),
        Index(
            "uq_background_jobs_idempotency_active",
            "job_type",
            "idempotency_key",
            unique=True,
            postgresql_where=_IDEMPOTENCY_WHERE,
            sqlite_where=_IDEMPOTENCY_WHERE,
        ),
        Index(
            "uq_background_jobs_lock_key_active",
            "lock_key",
            unique=True,
            postgresql_where=_LOCK_KEY_WHERE,
            sqlite_where=_LOCK_KEY_WHERE,
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    progress_detail: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False)
    requeue_of: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lock_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
