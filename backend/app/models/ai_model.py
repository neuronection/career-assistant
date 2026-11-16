import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin

# Caller-supplied retrieval tags documented by the vendored family contract
# (``retrieval_ops.AI_GENERATIONS_METADATA``). The column is JSON because the
# tag set is keep-open; the sibling version makes an incompatible change
# explicit. It never carries prompt/document text.
AI_GENERATION_METADATA_SCHEMA_VERSION = 1


class AIGeneration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Audit trail for every AI call made through the provider.

    ``metadata_json`` (DB column ``metadata``) is the caller-supplied
    retrieval seam: an embedding call may tag ``space_id``/``kind``/``view``/
    ``chunk_index``/``document_id`` (registered documents only)/``phase``/
    ``documents`` (the batch's document span) the way it already passes
    ``run_id``/``run_stage``. The gateway writes only what the caller handed
    it — it never invents tags — and retrieval DTOs never select ``prompt``
    or this payload's free text.
    """

    __tablename__ = "ai_generations"
    __table_args__ = (
        Index("ix_ai_generations_created_at", "created_at"),
        CheckConstraint(
            "usage_source IN ('provider', 'estimated', 'partial', 'unknown')",
            name="usage_source_allowed",
        ),
        CheckConstraint(
            "price_source IN ('user', 'builtin', 'local', 'unknown')",
            name="price_source_allowed",
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="mock")
    model: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    provider_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cost_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    usage_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default="unknown"
    )
    estimate_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    price_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default="unknown"
    )
    price_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    output: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    error: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    task_tier: Mapped[str | None] = mapped_column(String(10), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The skill-pack version that governed this call.
    pack_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    pack_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Run linkage (opt-in, no FK): the multi-step flow this call served —
    # e.g. a background job id — so a run's ledger can be consulted per
    # run. Plain columns: the audit outlives deleted CVs/jobs/users and
    # budget math stays untouched.
    run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    run_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Caller-supplied retrieval tags (plan 51 Q1a): space_id/kind/view/
    # chunk_index, never text. ``metadata`` is a reserved declarative name, so
    # the mapped attribute is ``metadata_json`` and the column keeps the
    # family name.
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        StructuredJSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    metadata_schema_version: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=AI_GENERATION_METADATA_SCHEMA_VERSION,
        server_default=str(AI_GENERATION_METADATA_SCHEMA_VERSION),
    )


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
    task_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    window: Mapped[str] = mapped_column(String(10), nullable=False, default="day")
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AIPriceOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """System-scoped model price override (plan 58 P2)."""

    __tablename__ = "ai_price_overrides"
    __table_args__ = (
        UniqueConstraint(
            "provider_key",
            "provider_ref",
            "model",
            "match",
            name="uq_ai_price_overrides_scope",
        ),
        CheckConstraint("match IN ('exact', 'prefix')", name="match_allowed"),
        CheckConstraint(
            "metering IN ('tokens', 'input_only', 'output_only')",
            name="metering_allowed",
        ),
    )

    provider_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_ref: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    match: Mapped[str] = mapped_column(
        String(10), nullable=False, default="exact", server_default="exact"
    )
    input_micros_per_million: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    output_micros_per_million: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    metering: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tokens", server_default="tokens"
    )
