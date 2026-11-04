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
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

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
from app.storage.tokenizer_contract import (
    ChunkConfig,
    TokenizerKind,
    TokenizerSource,
    TokenizerSpec,
)
from app.storage.vector_contract import (
    METRICS,
    V1_VIEWS,
    DegradedReason,
    SpaceStatus,
)
from app.storage.vector_contract import space_key as make_space_key
from app.storage.vector_contract import space_key_v2 as make_space_key_v2

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

_TOKENIZER_KINDS = tuple(member.value for member in TokenizerKind)
_TOKENIZER_GROUP_CHECK = (
    "(tokenizer_kind IS NULL AND tokenizer_identifier IS NULL "
    "AND tokenizer_revision IS NULL AND tokenizer_artifact_sha256 IS NULL "
    "AND tokenizer_exact IS NULL AND max_input_tokens IS NULL "
    "AND chunk_max_tokens IS NULL AND chunk_overlap_tokens IS NULL "
    "AND chunk_max_chars IS NULL) OR "
    "(tokenizer_kind IS NOT NULL AND tokenizer_identifier IS NOT NULL "
    "AND tokenizer_exact IS NOT NULL AND max_input_tokens IS NOT NULL "
    "AND chunk_max_tokens IS NOT NULL AND chunk_overlap_tokens IS NOT NULL "
    "AND chunk_max_chars IS NOT NULL)"
)
_TOKENIZER_KIND_CHECK = f"tokenizer_kind IS NULL OR tokenizer_kind IN ({_quoted(_TOKENIZER_KINDS)})"
_TOKENIZER_EXACT_CHECK = (
    "tokenizer_kind IS NULL OR "
    "(tokenizer_kind = 'heuristic' AND tokenizer_exact = false) OR "
    "(tokenizer_kind <> 'heuristic' AND tokenizer_exact = true)"
)
_TOKENIZER_PROVENANCE_CHECK = (
    "tokenizer_kind IS NULL OR "
    "(tokenizer_kind = 'heuristic' AND tokenizer_revision IS NULL "
    "AND tokenizer_artifact_sha256 IS NULL) OR "
    "(tokenizer_kind IN ('hf_tokenizers', 'sentencepiece') "
    "AND tokenizer_revision IS NOT NULL AND tokenizer_artifact_sha256 IS NOT NULL) OR "
    "(tokenizer_kind = 'tiktoken' AND tokenizer_artifact_sha256 IS NOT NULL)"
)
_TOKENIZER_BOUNDS_CHECK = (
    "tokenizer_kind IS NULL OR "
    "(max_input_tokens > 0 AND chunk_max_tokens >= 32 "
    "AND chunk_overlap_tokens >= 0 AND chunk_overlap_tokens * 2 < chunk_max_tokens "
    "AND chunk_max_chars > 0 AND chunk_max_tokens <= max_input_tokens)"
)
_TOKENIZER_CHUNKER_VERSION_CHECK = "tokenizer_kind IS NULL OR chunker_version = '2'"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def tokenizer_spec_from_columns(values: Mapping[str, Any]) -> TokenizerSpec | None:
    """Rebuild the pinned tokenizer from persisted scalar columns.

    ``None`` means a legacy v1 row (every tokenizer column NULL). The
    ``source`` is not part of the stored identity and is reconstructed as
    ``fallback`` for the heuristic and ``curated`` otherwise; the space key
    deliberately does not include it.
    """
    kind = values.get("tokenizer_kind")
    if kind is None:
        return None
    identifier = values.get("tokenizer_identifier")
    max_input_tokens = values.get("max_input_tokens")
    if identifier is None or max_input_tokens is None:  # pragma: no cover - CHECK guards
        raise ValueError("a tokenizer column set is incomplete")
    heuristic = str(kind) == TokenizerKind.HEURISTIC.value
    return TokenizerSpec(
        kind=str(kind),
        identifier=str(identifier),
        revision=(
            None
            if values.get("tokenizer_revision") is None
            else str(values.get("tokenizer_revision"))
        ),
        artifact_sha256=(
            None
            if values.get("tokenizer_artifact_sha256") is None
            else str(values.get("tokenizer_artifact_sha256"))
        ),
        exact=bool(values.get("tokenizer_exact")),
        max_input_tokens=int(max_input_tokens),
        source=(TokenizerSource.FALLBACK if heuristic else TokenizerSource.CURATED),
    )


def chunk_config_from_columns(values: Mapping[str, Any]) -> ChunkConfig | None:
    """Rebuild the token chunk configuration from persisted scalar columns."""
    if values.get("tokenizer_kind") is None:
        return None
    max_chunk_tokens = values.get("chunk_max_tokens")
    overlap_tokens = values.get("chunk_overlap_tokens")
    max_chars = values.get("chunk_max_chars")
    if max_chunk_tokens is None or overlap_tokens is None or max_chars is None:
        raise ValueError("a chunk config column set is incomplete")
    return ChunkConfig(
        max_chunk_tokens=int(max_chunk_tokens),
        overlap_tokens=int(overlap_tokens),
        max_chars=int(max_chars),
    )


def _computed_space_key(context) -> str:
    """Stamp a new row with the key of its configuration (once, at insert).

    A direct ORM insert may carry the flattened tokenizer/chunk columns; the
    default then computes the *v2* key, so a token-aware row can never be
    stamped with a legacy v1 key just because the caller omitted ``space_key``.
    """
    values = context.get_current_parameters()
    tokenizer = tokenizer_spec_from_columns(values)
    if tokenizer is None:
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
    chunk = chunk_config_from_columns(values)
    if chunk is None:  # pragma: no cover - the group CHECK rejects this earlier
        raise ValueError("a tokenizer column set needs the complete chunk columns")
    return make_space_key_v2(
        values["provider"],
        values["model"],
        int(values["dim"]),
        bool(values.get("normalize", True)),
        values.get("query_prefix"),
        values.get("document_prefix"),
        str(values.get("chunker_version") or "2"),
        str(values.get("composer_version") or "1"),
        tokenizer=tokenizer,
        chunk=chunk,
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
        CheckConstraint(_TOKENIZER_GROUP_CHECK, name="tokenizer_group_all_or_none"),
        CheckConstraint(_TOKENIZER_KIND_CHECK, name="tokenizer_kind_allowed"),
        CheckConstraint(_TOKENIZER_EXACT_CHECK, name="tokenizer_exact_matches_kind"),
        CheckConstraint(_TOKENIZER_PROVENANCE_CHECK, name="tokenizer_provenance_by_kind"),
        CheckConstraint(_TOKENIZER_BOUNDS_CHECK, name="tokenizer_chunk_bounds"),
        CheckConstraint(_TOKENIZER_CHUNKER_VERSION_CHECK, name="tokenizer_requires_chunker_v2"),
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
    # Token-aware identity (plan 52 T3b). All NULL on a legacy v1 row; the
    # full set is present on a v2 row and folded into ``space_key``.
    tokenizer_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tokenizer_identifier: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tokenizer_revision: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tokenizer_artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokenizer_exact: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    max_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_overlap_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_max_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
        CheckConstraint("token_count IS NULL OR token_count >= 0", name="token_count_non_negative"),
        CheckConstraint("token_start IS NULL OR token_start >= 0", name="token_start_non_negative"),
        CheckConstraint("token_end IS NULL OR token_end >= 0", name="token_end_non_negative"),
        CheckConstraint(
            "token_start IS NULL OR token_end IS NULL OR token_end >= token_start",
            name="token_range_ordered",
        ),
        CheckConstraint(
            "(token_count IS NULL AND token_start IS NULL AND token_end IS NULL) OR "
            "(token_count IS NOT NULL AND token_start IS NOT NULL AND token_end IS NOT NULL "
            "AND token_count = token_end - token_start)",
            name="token_fields_consistent",
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
    # Token offsets (plan 52 T3b): all NULL on a legacy char-chunked record,
    # all present on a token-aware record. ``token_count == token_end - token_start``.
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
