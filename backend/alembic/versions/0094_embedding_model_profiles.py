"""Plan 52 T2a — the embedding-model profile registry.

Creates ``embedding_model_profiles``: one row per admin-selected tokenizer
and limit profile, keyed by the provider class plus the model id. Curated
profiles stay in code; a row is the explicit override that wins over the
curated catalog and the conservative fallback. The table carries the
tokenizer identity (kind/identifier/revision/checksum/exact), the model
input limit, the per-request batch item/token limits and the default
``ChunkConfig`` preview (max chunk tokens, overlap, max chars).

No JSONB: every value is a typed scalar the resolver reads. No seed rows:
curated models ship in ``app/ai/tokenizers/registry.py`` so a migration
never invents model facts. Downgrade drops the table; the overrides are
rebuildable admin configuration, not audit data (the change itself is
already on ``audit_events`` as ``vector.model.changed``).
"""

import sqlalchemy as sa

from alembic import op

revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embedding_model_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider_class", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("tokenizer_kind", sa.String(length=30), nullable=False),
        sa.Column("tokenizer_identifier", sa.String(length=200), nullable=False),
        sa.Column("tokenizer_revision", sa.String(length=120), nullable=True),
        sa.Column("tokenizer_artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("tokenizer_exact", sa.Boolean(), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False),
        sa.Column("batch_max_items", sa.Integer(), nullable=False),
        sa.Column("batch_max_tokens", sa.Integer(), nullable=False),
        sa.Column("chunk_max_tokens", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap_tokens", sa.Integer(), nullable=False),
        sa.Column("chunk_max_chars", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('curated', 'admin', 'fallback')", name="source_allowed"),
        sa.CheckConstraint(
            "tokenizer_kind IN ('tiktoken', 'hf_tokenizers', 'sentencepiece', 'heuristic')",
            name="tokenizer_kind_allowed",
        ),
        sa.CheckConstraint("max_input_tokens > 0", name="max_input_positive"),
        sa.CheckConstraint("batch_max_items > 0", name="batch_items_positive"),
        sa.CheckConstraint("batch_max_tokens > 0", name="batch_tokens_positive"),
        sa.CheckConstraint("chunk_max_tokens >= 32", name="chunk_tokens_floor"),
        sa.CheckConstraint("chunk_overlap_tokens >= 0", name="chunk_overlap_non_negative"),
        sa.CheckConstraint(
            "chunk_overlap_tokens * 2 < chunk_max_tokens", name="chunk_overlap_bounded"
        ),
        sa.CheckConstraint("chunk_max_chars > 0", name="chunk_chars_positive"),
        sa.CheckConstraint("chunk_max_tokens <= max_input_tokens", name="chunk_fits_input"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "provider_class", "model_name", name="uq_embedding_model_profiles_scope"
        ),
    )
    op.create_index(
        "ix_embedding_model_profiles_provider",
        "embedding_model_profiles",
        ["provider_class"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_embedding_model_profiles_provider",
        table_name="embedding_model_profiles",
    )
    op.drop_table("embedding_model_profiles")
