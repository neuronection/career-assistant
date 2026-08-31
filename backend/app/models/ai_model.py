import uuid
from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin


class AIGeneration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Audit trail for every AI call made through the provider."""

    __tablename__ = "ai_generations"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="mock")
    model: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    prompt: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    output: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    error: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
