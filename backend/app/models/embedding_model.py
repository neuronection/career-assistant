"""Semantic-search embeddings store.

One row per embedded entity (postings, catalog families, assessment
templates, chat summaries). The vector is stored as packed JSONB floats
— the single source of truth on every dialect (Postgres AND SQLite, the
 cross-dialect rule). pgvector acceleration is provisioned
best-effort by the migration but not yet read: catalog scale makes
Python-side cosine fine, and one retrieval path beats two.
"""

import uuid

from sqlalchemy import Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class AIEmbedding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Latest embedding for one entity (content_hash dedupe)."""

    __tablename__ = "ai_embeddings"
    __table_args__ = (
        UniqueConstraint("entity_kind", "entity_id", name="uq_ai_embeddings_entity"),
        Index("ix_ai_embeddings_kind_dim", "entity_kind", "dim"),
    )

    entity_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # sha256 of the normalized embedded text — a stale hash means
    # re-embed before the stored vector is trusted.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list] = mapped_column(StructuredJSON, nullable=False)
