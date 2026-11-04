"""Vector-retrieval store (plan 50 P1): spaces, documents, records and
the two bounded operational rollups plan 51's read surface consumes.

The portable metadata lives here on both dialects. The physical vector
payload belongs to a backend-specific index (pgvector table, sqlite-vec
``vec0`` table, or — when neither is available — the nullable
``vector_records.embedding`` BLOB used by the linear scan). Source text is
never stored: ``text_ref`` is a pointer validated at the service boundary.

The vocabulary of the space lifecycle, degradation reasons and views comes
from the vendored family contract (``app/storage/vector_contract.py``) so
the DB CHECKs and the contract can never drift apart.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    TZDateTime,
    UUIDPrimaryKeyMixin,
)
from app.models.enums.retrieval import VectorScopeType
from app.storage.vector_contract import (
    METRICS,
    V1_VIEWS,
    DegradedReason,
    SpaceStatus,
)
from app.storage.vector_contract import space_key as make_space_key

# Index tables are named from the space UUID by the provisioning seam:
# ``vec_`` + 8 lowercase hex characters. The DB CHECK pins the portable
# shape; the exact hex validation lives in the provisioning seam.
INDEX_TABLE_PATTERN = "vec_"
INDEX_TABLE_LENGTH = 12


def _quoted(values: Iterable[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


_SPACE_STATUS_CHECK = f"status IN ({_quoted(member.value for member in SpaceStatus)})"
_METRIC_CHECK = f"metric IN ({_quoted(METRICS)})"
_SCOPE_TYPE_CHECK = f"scope_type IN ({_quoted(member.value for member in VectorScopeType)})"
_VIEW_CHECK = f"view IN ({_quoted(V1_VIEWS)})"
_DEGRADED_REASON_CHECK = (
    "degraded_reason IS NULL OR "
    f"degraded_reason IN ({_quoted(member.value for member in DegradedReason)})"
)
_INDEX_TABLE_CHECK = (
    "index_table IS NULL OR "
    f"(index_table LIKE '{INDEX_TABLE_PATTERN}%' "
    f"AND length(index_table) = {INDEX_TABLE_LENGTH})"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _computed_space_key(context) -> str:
    """Stamp a new row with the v1 key of its configuration (once, at insert)."""
    values = context.get_current_parameters()
    return make_space_key(
        values["provider"],
        values["model"],
        int(values["dim"]),
        bool(values.get("normalize", True)),
        values.get("query_prefix"),
        values.get("document_prefix"),
        str(values.get("chunker_version") or "1"),
        str(values.get("composer_version") or "1"),
    )


class VectorSpace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A versioned embedding configuration (plan 50 §3.1).

    One ``active`` row per ``name`` is enforced by a partial unique index;
    a model/dimension change creates a ``building`` space and runs the
    cutover instead of rewriting a column. ``index_table`` is ``NULL``
    while the linear backend is active.

    Retention: operational, derived configuration. A retired space is kept
    only for its purge grace period and is then dropped by an audited ops
    action — never pruned silently. Deleting a space cascades its documents
    and records.
    """

    __tablename__ = "vector_spaces"
    __table_args__ = (
        CheckConstraint(_SPACE_STATUS_CHECK, name="status_allowed"),
        CheckConstraint(_METRIC_CHECK, name="metric_allowed"),
        CheckConstraint("dim > 0", name="dim_positive"),
        CheckConstraint(_INDEX_TABLE_CHECK, name="index_table_shape"),
        UniqueConstraint("index_table", name="uq_vector_spaces_index_table"),
        Index(
            "uq_vector_spaces_name_active",
            "name",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_vector_spaces_name", "name"),
    )

    name: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    metric: Mapped[str] = mapped_column(
        String(10), nullable=False, default=METRICS[0], server_default=METRICS[0]
    )
    normalize: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    chunker_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1", server_default="1"
    )
    composer_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1", server_default="1"
    )
    query_prefix: Mapped[str | None] = mapped_column(String(80), nullable=True)
    document_prefix: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Persisted identity: stamped once at creation and never recomputed across
    # tokenizer/chunker versions. Remap/cutover compares this value verbatim.
    space_key: Mapped[str] = mapped_column(String(64), nullable=False, default=_computed_space_key)
    # Physical ANN table; NULL while the linear backend is the store.
    index_table: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default=SpaceStatus.ACTIVE.value,
        server_default=SpaceStatus.ACTIVE.value,
    )
    backfill_done: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backfill_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class VectorDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One source entity in a space (plan 50 §3.2).

    ``kind`` + ``source_id`` are the polymorphic source handle
    (``posting``, ``job``, ``material``, ``skill``, ``profile``,
    ``chat_summary``, ``template``); there is deliberately no FK to a
    source table, so the writer's delete hook and the orphan sweep own
    erasure. ``source_id`` is canonicalized once by the writer.

    Retention: operational, derived. Hard-deleted with its source (or by a
    user/tenant erasure that filters on the scope columns); the document is
    a rebuild unit, never a record of its own.
    """

    __tablename__ = "vector_documents"
    __table_args__ = (
        UniqueConstraint("space_id", "kind", "source_id", name="uq_vector_documents_source"),
        CheckConstraint(_SCOPE_TYPE_CHECK, name="scope_type_allowed"),
        Index("ix_vector_documents_space_scope", "space_id", "scope_type", "scope_id"),
        Index("ix_vector_documents_space_profile", "space_id", "profile_id"),
        Index("ix_vector_documents_space_kind", "space_id", "kind"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vector_spaces.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(12), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True
    )
    # sha256 of every composed view text, using the contract's hash rule.
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)


class VectorRecord(UUIDPrimaryKeyMixin, Base):
    """One embeddable unit — a named view or a chunk of one (plan 50 §3.3).

    ``text_ref`` points at the source (``{table, id, field}`` +
    ``text_ref_schema_version``); raw text is never copied here.
    ``embedding`` holds the float32 vector only when the linear backend is
    active (the single copy in that deployment); pgvector and sqlite-vec
    leave it ``NULL``.

    Retention: operational, derived. Hard-deleted with its document; a
    reindex replaces records in place by the unique
    ``(document_id, view, chunk_index)`` key.
    """

    __tablename__ = "vector_records"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "view", "chunk_index", name="uq_vector_records_document_view_chunk"
        ),
        CheckConstraint(_VIEW_CHECK, name="view_allowed"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        CheckConstraint(
            "char_start IS NULL OR char_end IS NULL OR char_end >= char_start",
            name="char_range_ordered",
        ),
        Index("ix_vector_records_space_view", "space_id", "view"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vector_documents.id", ondelete="CASCADE"), nullable=False
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vector_spaces.id", ondelete="CASCADE"), nullable=False
    )
    view: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text_ref: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    text_ref_schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=_utcnow)


class RetrievalQueryRollup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bounded query-health rollup (plan 51 §3.1, created by plan 50 P1).

    Dimensions are ``(space_id, kind, view, degraded_reason, bucket_start,
    bucket_width)``; measures are counts, zero-result count, the candidate
    sum and a versioned latency-histogram payload. ``view`` and
    ``degraded_reason`` are ``NULL`` when the dimension does not apply, so
    the uniqueness key coalesces them in its index.

    Retention: operational aggregate, not an audit ledger — TTL 30 days,
    pruned explicitly by the telemetry flush job. Losing a row loses a
    measurement, never a record.
    """

    __tablename__ = "retrieval_query_rollups"
    __table_args__ = (
        Index(
            "uq_retrieval_query_rollups_dims",
            "space_id",
            "kind",
            text("COALESCE(view, '')"),
            text("COALESCE(degraded_reason, '')"),
            "bucket_start",
            "bucket_width",
            unique=True,
        ),
        CheckConstraint(_DEGRADED_REASON_CHECK, name="degraded_reason_allowed"),
        CheckConstraint("bucket_width > 0", name="bucket_width_positive"),
        CheckConstraint("count >= 0", name="count_non_negative"),
        CheckConstraint("zero_results >= 0 AND zero_results <= count", name="zero_results_range"),
        CheckConstraint("candidates_sum >= 0", name="candidates_sum_non_negative"),
        Index("ix_retrieval_query_rollups_space_bucket", "space_id", "bucket_start"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vector_spaces.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    view: Mapped[str | None] = mapped_column(String(32), nullable=True)
    degraded_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    bucket_start: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    bucket_width: Mapped[int] = mapped_column(Integer, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    zero_results: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    candidates_sum: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    latency_buckets: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    latency_bucket_schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RetrievalCoverageSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-kind coverage and sampled ANN recall at a point in time.

    Written by the reconcile pass and the periodic maintenance probe, never
    by a dashboard request; ``ann_recall``/``ann_recall_k``/``probe_size``
    stay ``NULL`` when recall was not sampled ("not sampled" is a real
    state, not a zero).

    Retention: operational, TTL 90 days, pruned explicitly by the
    maintenance job.
    """

    __tablename__ = "retrieval_coverage_snapshots"
    __table_args__ = (
        UniqueConstraint("space_id", "kind", "as_of", name="uq_retrieval_coverage_point"),
        CheckConstraint(
            "total >= 0 AND missing >= 0 AND stale >= 0 AND failed >= 0 AND embedded >= 0",
            name="coverage_counts_non_negative",
        ),
        CheckConstraint(
            "ann_recall IS NULL OR (ann_recall >= 0 AND ann_recall <= 1)", name="ann_recall_range"
        ),
        CheckConstraint("ann_recall_k IS NULL OR ann_recall_k > 0", name="ann_recall_k_positive"),
        CheckConstraint("probe_size IS NULL OR probe_size >= 0", name="probe_size_non_negative"),
        Index("ix_retrieval_coverage_snapshots_space_kind", "space_id", "kind", "as_of"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vector_spaces.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    as_of: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    missing: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    stale: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    failed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    embedded: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    ann_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    ann_recall_k: Mapped[int | None] = mapped_column(Integer, nullable=True)
    probe_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
