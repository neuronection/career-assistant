import uuid
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
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
    task_tier: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # The skill-pack version that governed this call.
    pack_key: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    pack_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Run linkage (opt-in, no FK): the multi-step flow this call served —
    # e.g. a background job id — so a run's ledger can be consulted per
    # run. Plain columns: the audit outlives deleted CVs/jobs/users and
    # budget math stays untouched.
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    run_stage: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


class AIBudget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Token budget with a hard stop.

    Scope axes are additive: ``task_type`` null = every task, ``user_id``
    null = every user. ``ai_generations`` is the consumption ledger —
    budgets sum audit rows in the active window and can never drift from
    what was actually spent.
    """

    __tablename__ = "ai_budgets"
    __table_args__ = (UniqueConstraint("name", name="uq_ai_budgets_name"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    task_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    window: Mapped[str] = mapped_column(String(10), nullable=False, default="day")
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
