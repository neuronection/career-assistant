import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin


class BackgroundJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable queue entry for long-running AI work.

    Claim-based: the worker flips queued → running with a conditional UPDATE
    (rowcount decides the winner), so no dialect-specific locking is needed.
    """

    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_user_id", "user_id"),
        Index("ix_background_jobs_status_created", "status", "created_at"),
    )

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    result: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
