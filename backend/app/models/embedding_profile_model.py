import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EmbeddingModelProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An admin override for one embedding model's tokenizer/limits profile.

    The key is the provider class plus the model id (``provider_class`` +
    ``model_name``), never a substring of the model name. Curated profiles
    live in code (``app/ai/tokenizers/registry.py``); a row here is the
    explicit admin selection that wins over the curated catalog. ``source``
    is closed to the contract vocabulary so a later curated sync can persist
    its rows without a shape change; this slice writes ``admin`` only.
    """

    __tablename__ = "embedding_model_profiles"
    __table_args__ = (
        UniqueConstraint("provider_class", "model_name", name="uq_embedding_model_profiles_scope"),
        CheckConstraint("source IN ('curated', 'admin', 'fallback')", name="source_allowed"),
        CheckConstraint(
            "tokenizer_kind IN ('tiktoken', 'hf_tokenizers', 'sentencepiece', 'heuristic')",
            name="tokenizer_kind_allowed",
        ),
        CheckConstraint("max_input_tokens > 0", name="max_input_positive"),
        CheckConstraint("batch_max_items > 0", name="batch_items_positive"),
        CheckConstraint("batch_max_tokens > 0", name="batch_tokens_positive"),
        CheckConstraint("chunk_max_tokens >= 32", name="chunk_tokens_floor"),
        CheckConstraint("chunk_overlap_tokens >= 0", name="chunk_overlap_non_negative"),
        CheckConstraint(
            "chunk_overlap_tokens * 2 < chunk_max_tokens", name="chunk_overlap_bounded"
        ),
        CheckConstraint("chunk_max_chars > 0", name="chunk_chars_positive"),
        CheckConstraint("chunk_max_tokens <= max_input_tokens", name="chunk_fits_input"),
    )

    provider_class: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tokenizer_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    tokenizer_identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    tokenizer_revision: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tokenizer_artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokenizer_exact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_max_items: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_overlap_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_max_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="admin")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
