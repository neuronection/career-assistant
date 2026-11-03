"""Plan 50 P1a — the portable vector-retrieval store.

Creates the five metadata/telemetry tables the family retrieval contract
needs on both dialects:

* ``vector_spaces`` — one row per versioned embedding configuration
  (partial unique index: one ``active`` space per name);
* ``vector_documents`` — polymorphic source entities in a space;
* ``vector_records`` — one embeddable unit (a view or a chunk); the
  ``embedding`` BLOB stays ``NULL`` under pgvector/sqlite-vec and is the
  single vector copy while the linear backend is active;
* ``retrieval_query_rollups`` / ``retrieval_coverage_snapshots`` — the
  bounded, TTL-retained aggregates plan 51's status read consumes.

No physical ``vec_*`` table is created here: provisioning is a job/migration
step (plan 50 §3.4, P1b), and Alembic must never emit DDL for one. The
downgrade drops the tables and their indexes; the store is derived data and
is rebuilt by a reindex.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

_STATUS_CHECK = "status IN ('active', 'building', 'retired')"
_METRIC_CHECK = "metric IN ('cosine')"
_SCOPE_TYPE_CHECK = "scope_type IN ('user', 'tenant', 'global')"
_VIEW_CHECK = "view IN ('summary', 'requirements', 'responsibilities', 'skills', 'body')"
_DEGRADED_REASON_CHECK = (
    "degraded_reason IS NULL OR degraded_reason IN ("
    "'provider_unassigned', 'embed_failed', 'index_missing', "
    "'space_mismatch', 'over_cap')"
)
_INDEX_TABLE_CHECK = (
    "index_table IS NULL OR (index_table LIKE 'vec_%' AND length(index_table) = 12)"
)


def upgrade() -> None:
    op.create_table(
        "vector_spaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(length=10), nullable=False, server_default="cosine"),
        sa.Column("normalize", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("chunker_version", sa.String(length=20), nullable=False, server_default="1"),
        sa.Column("composer_version", sa.String(length=20), nullable=False, server_default="1"),
        sa.Column("query_prefix", sa.String(length=80), nullable=True),
        sa.Column("document_prefix", sa.String(length=80), nullable=True),
        sa.Column("index_table", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="active"),
        sa.Column("backfill_done", sa.Integer(), nullable=True),
        sa.Column("backfill_total", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_STATUS_CHECK, name="status_allowed"),
        sa.CheckConstraint(_METRIC_CHECK, name="metric_allowed"),
        sa.CheckConstraint("dim > 0", name="dim_positive"),
        sa.CheckConstraint(_INDEX_TABLE_CHECK, name="index_table_shape"),
        sa.UniqueConstraint("index_table", name="uq_vector_spaces_index_table"),
    )
    op.create_index("ix_vector_spaces_name", "vector_spaces", ["name"])
    op.create_index(
        "uq_vector_spaces_name_active",
        "vector_spaces",
        ["name"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "vector_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=12), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("profile_id", sa.Uuid(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_SCOPE_TYPE_CHECK, name="scope_type_allowed"),
        sa.ForeignKeyConstraint(["space_id"], ["vector_spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("space_id", "kind", "source_id", name="uq_vector_documents_source"),
    )
    op.create_index(
        "ix_vector_documents_space_scope",
        "vector_documents",
        ["space_id", "scope_type", "scope_id"],
    )
    op.create_index(
        "ix_vector_documents_space_profile", "vector_documents", ["space_id", "profile_id"]
    )
    op.create_index("ix_vector_documents_space_kind", "vector_documents", ["space_id", "kind"])

    op.create_table(
        "vector_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("view", sa.String(length=32), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("text_ref", _JSON, nullable=True),
        sa.Column("text_ref_schema_version", sa.Integer(), nullable=True),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_VIEW_CHECK, name="view_allowed"),
        sa.CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        sa.CheckConstraint(
            "char_start IS NULL OR char_end IS NULL OR char_end >= char_start",
            name="char_range_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["vector_documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["space_id"], ["vector_spaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "document_id", "view", "chunk_index", name="uq_vector_records_document_view_chunk"
        ),
    )
    op.create_index("ix_vector_records_space_view", "vector_records", ["space_id", "view"])

    op.create_table(
        "retrieval_query_rollups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("view", sa.String(length=32), nullable=True),
        sa.Column("degraded_reason", sa.String(length=24), nullable=True),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_width", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("zero_results", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_sum", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_buckets", _JSON, nullable=True),
        sa.Column("latency_bucket_schema_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_DEGRADED_REASON_CHECK, name="degraded_reason_allowed"),
        sa.CheckConstraint("bucket_width > 0", name="bucket_width_positive"),
        sa.CheckConstraint("count >= 0", name="count_non_negative"),
        sa.CheckConstraint(
            "zero_results >= 0 AND zero_results <= count", name="zero_results_range"
        ),
        sa.CheckConstraint("candidates_sum >= 0", name="candidates_sum_non_negative"),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["vector_spaces.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "uq_retrieval_query_rollups_dims",
        "retrieval_query_rollups",
        [
            "space_id",
            "kind",
            sa.text("COALESCE(view, '')"),
            sa.text("COALESCE(degraded_reason, '')"),
            "bucket_start",
            "bucket_width",
        ],
        unique=True,
    )
    op.create_index(
        "ix_retrieval_query_rollups_space_bucket",
        "retrieval_query_rollups",
        ["space_id", "bucket_start"],
    )

    op.create_table(
        "retrieval_coverage_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stale", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ann_recall", sa.Float(), nullable=True),
        sa.Column("ann_recall_k", sa.Integer(), nullable=True),
        sa.Column("probe_size", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "total >= 0 AND missing >= 0 AND stale >= 0 AND failed >= 0 AND embedded >= 0",
            name="coverage_counts_non_negative",
        ),
        sa.CheckConstraint(
            "ann_recall IS NULL OR (ann_recall >= 0 AND ann_recall <= 1)",
            name="ann_recall_range",
        ),
        sa.CheckConstraint(
            "ann_recall_k IS NULL OR ann_recall_k > 0", name="ann_recall_k_positive"
        ),
        sa.CheckConstraint("probe_size IS NULL OR probe_size >= 0", name="probe_size_non_negative"),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["vector_spaces.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("space_id", "kind", "as_of", name="uq_retrieval_coverage_point"),
    )
    op.create_index(
        "ix_retrieval_coverage_snapshots_space_kind",
        "retrieval_coverage_snapshots",
        ["space_id", "kind", "as_of"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_retrieval_coverage_snapshots_space_kind",
        table_name="retrieval_coverage_snapshots",
    )
    op.drop_table("retrieval_coverage_snapshots")

    op.drop_index("ix_retrieval_query_rollups_space_bucket", table_name="retrieval_query_rollups")
    op.drop_index("uq_retrieval_query_rollups_dims", table_name="retrieval_query_rollups")
    op.drop_table("retrieval_query_rollups")

    op.drop_index("ix_vector_records_space_view", table_name="vector_records")
    op.drop_table("vector_records")

    op.drop_index("ix_vector_documents_space_kind", table_name="vector_documents")
    op.drop_index("ix_vector_documents_space_profile", table_name="vector_documents")
    op.drop_index("ix_vector_documents_space_scope", table_name="vector_documents")
    op.drop_table("vector_documents")

    op.drop_index("uq_vector_spaces_name_active", table_name="vector_spaces")
    op.drop_index("ix_vector_spaces_name", table_name="vector_spaces")
    op.drop_table("vector_spaces")
