"""App-side vector backend adapters and the one-per-process factory
(plan 50 §4, P1b).

The shared contract (DTOs, protocol, cosine, capabilities) is the vendored
``app.storage.vector_contract`` module. This module owns the SQL for the
three engines:

* :class:`LinearBackend` — exact cosine over ``vector_records.embedding``;
* :class:`PgVectorBackend` — one HNSW table per space, scope joined into the
  ANN query, ``ef_search``/iterative scan tuned per query;
* :class:`SqliteVecBackend` — a ``vec0`` table plus the ``vector_entry_ids``
  rowid map, over-fetch then bounded post-filter.

Metadata (``vector_spaces``/``vector_documents``/``vector_records``) belongs
to :class:`app.storage.vector_store.VectorStoreService`. The session-bound
``*_index`` hooks below let the service write metadata and the physical index
in one transaction without any backend writing metadata itself. The public
``upsert``/``delete_document`` methods are the contract shape for standalone
use and wrap the same hooks in their own short transaction.

The factory selects the engine once per process; it never fakes ANN. If the
extension/driver is absent the linear backend is returned and publishes
``ann=False``.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from array import array
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, bindparam, false, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.vector_model import VectorDocument, VectorRecord
from app.storage.vector_contract import (
    BACKEND_CAPS,
    BACKEND_LINEAR,
    BACKEND_PGVECTOR,
    BACKEND_SQLITE_VEC,
    CANDIDATE_MULTIPLIER,
    EF_SEARCH_DEFAULT,
    EXACT_SCAN_THRESHOLD,
    BackendCaps,
    BackendHealth,
    DegradedReason,
    IndexHit,
    IndexRecord,
    ScopeSpec,
    VectorBackend,
    VectorSpace,
    cosine,
    normalize_text,
)
from app.storage.vector_schema import validate_index_table

logger = logging.getLogger(__name__)

SCOPE_ALL = "all"
SCOPE_DOCUMENTS = "documents"
SCOPE_FILTERS = "filters"

_SCOPE_COLUMNS = {
    "document_ids": VectorRecord.document_id,
    "kinds": VectorDocument.kind,
    "source_ids": VectorDocument.source_id,
    "scope_types": VectorDocument.scope_type,
    "scope_ids": VectorDocument.scope_id,
    "profile_ids": VectorDocument.profile_id,
}
_SCOPE_SQL = {
    "document_ids": "r.document_id",
    "kinds": "d.kind",
    "source_ids": "d.source_id",
    "scope_types": "d.scope_type",
    "scope_ids": "d.scope_id",
    "profile_ids": "d.profile_id",
}
_UUID_FILTERS = {"document_ids", "scope_ids", "profile_ids"}


class VectorBackendError(RuntimeError):
    """Base failure for the storage adapters."""


class VectorSpaceNotFound(VectorBackendError):
    """The requested space has no persisted row."""


class VectorDocumentNotFound(VectorBackendError):
    """An upsert referenced a document that is not registered in the space."""


class VectorRecordNotFound(VectorBackendError):
    """An upsert referenced a record that has no metadata row."""


class VectorRecordIdentityMismatch(VectorBackendError):
    """The contract record id changed for the same (document, view, chunk)."""


class VectorIndexMissing(VectorBackendError):
    """The physical index (or its extension/driver) is absent or unusable."""


class VectorSpaceMismatch(VectorBackendError, ValueError):
    """A resolved embedding configuration does not match the target space.

    The degradation vocabulary pins this condition to
    :attr:`DegradedReason.SPACE_MISMATCH`; a writer must refuse (or retarget
    to a ``building`` space), never embed mixed vectors silently.
    """

    degraded = DegradedReason.SPACE_MISMATCH


class VectorBackendOverCap(VectorBackendError):
    """The scoped candidate count exceeds the backend's honest row cap.

    The service layer maps this to ``DegradedReason.OVER_CAP`` and serves the
    lexical path; scanning past the cap is never attempted silently.
    """

    degraded = DegradedReason.OVER_CAP


class VectorRowidCollision(VectorBackendError):
    """A sqlite-vec rowid already belongs to a different record id."""


@dataclass(frozen=True)
class ResolvedEmbedding:
    """What the provider/model resolver produced for this write.

    The writer guard compares this to the target space; vectors alone are
    not evidence of which model produced them (plan 50 §4, blocker 6).
    """

    provider: str
    model: str
    dim: int
    normalize: bool = True
    query_prefix: str | None = None
    document_prefix: str | None = None


def _prefix_value(value: str | None) -> str:
    return normalize_text(value or "")


def writer_mismatch_reason(space: VectorSpace, resolved: ResolvedEmbedding) -> str | None:
    """Return the first field that disagrees, or ``None`` when the write is safe."""
    checks: tuple[tuple[str, Any, Any], ...] = (
        ("provider", normalize_text(space.provider), normalize_text(resolved.provider)),
        ("model", normalize_text(space.model), normalize_text(resolved.model)),
        ("dim", space.dim, resolved.dim),
        ("normalize", space.normalize, resolved.normalize),
        ("query_prefix", _prefix_value(space.query_prefix), _prefix_value(resolved.query_prefix)),
        (
            "document_prefix",
            _prefix_value(space.document_prefix),
            _prefix_value(resolved.document_prefix),
        ),
    )
    for field, expected, actual in checks:
        if expected != actual:
            return f"{field}: space={expected!r}, resolved={actual!r}"
    return None


def assert_writer_matches_space(space: VectorSpace, resolved: ResolvedEmbedding) -> None:
    """Refuse a write whose resolved model/dim/prefixes differ from the space."""
    reason = writer_mismatch_reason(space, resolved)
    if reason is not None:
        raise VectorSpaceMismatch(f"writer/space mismatch — {reason}")


def document_scope(document_ids: Collection[str]) -> ScopeSpec:
    """A hard filter admitting exactly ``document_ids`` (an empty set admits none)."""
    if isinstance(document_ids, (str, bytes)):
        raise ValueError("document_scope takes a collection of ids, not a single string")
    return ScopeSpec(
        kind=SCOPE_DOCUMENTS,
        predicate=frozenset(str(value) for value in document_ids),
    )


def filter_scope(**filters: Collection[str]) -> ScopeSpec:
    """A hard filter over document columns; an empty collection admits nothing.

    Recognized keys: ``document_ids``, ``kinds``, ``source_ids``,
    ``scope_types``, ``scope_ids``, ``profile_ids``. ``source_ids`` filters the
    product's own entity ids (a posting UUID, a user UUID for a profile), so a
    caller can bound a search to the rows it already holds without resolving
    their document ids first.
    """
    unknown = set(filters) - set(_SCOPE_COLUMNS)
    if unknown:
        raise ValueError(f"unknown scope filter(s): {sorted(unknown)}")
    return ScopeSpec(kind=SCOPE_FILTERS, predicate=dict(filters))


def rowid_for(record_id: str | uuid.UUID, *, salt: int = 0) -> int:
    """The study rowid rule: a positive signed 64-bit BLAKE2b of the id."""
    payload = str(record_id).encode("utf-8")
    if salt:
        payload += f":{salt}".encode()
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big") & (
        0x7FFF_FFFF_FFFF_FFFF
    )


def _pack(embedding: Sequence[float]) -> bytes:
    return array("f", (float(value) for value in embedding)).tobytes()


def _unpack(blob: bytes | None) -> tuple[float, ...]:
    if not blob:
        return ()
    values = array("f")
    values.frombytes(blob)
    return tuple(values)


def _vector_literal(embedding: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in embedding) + "]"


def _parse_pg_vector(value: str) -> tuple[float, ...]:
    """Inverse of :func:`_vector_literal` for a pgvector text cast."""
    body = (value or "").strip().strip("[]")
    if not body:
        return ()
    return tuple(float(part) for part in body.split(","))


def _as_uuid(value: Any, *, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise VectorBackendError(f"invalid {field}: {value!r}") from exc


def _as_values(name: str, value: Any) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Collection):
        raise ValueError(f"scope filter {name} must be a collection, not {type(value).__name__}")
    return tuple(value)


def _scope_clauses(scope: ScopeSpec) -> list[Any] | None:
    """Compile the opaque scope into in-scan WHERE clauses (never post-filter)."""
    if not isinstance(scope, ScopeSpec):
        raise TypeError("scope must be a contract ScopeSpec")
    if scope.kind == SCOPE_ALL:
        if scope.predicate not in (None, {}):
            raise ValueError("the 'all' scope takes no predicate")
        return None
    if scope.kind == SCOPE_DOCUMENTS:
        values = _as_values("document_ids", scope.predicate)
        if not values:
            return [false()]
        return [
            VectorRecord.document_id.in_([_as_uuid(value, field="document_id") for value in values])
        ]
    if scope.kind == SCOPE_FILTERS:
        if not isinstance(scope.predicate, Mapping):
            raise ValueError("the 'filters' scope takes a mapping")
        unknown = set(scope.predicate) - set(_SCOPE_COLUMNS)
        if unknown:
            raise ValueError(f"unknown scope filter(s): {sorted(unknown)}")
        clauses: list[Any] = []
        for name, raw in scope.predicate.items():
            values = _as_values(name, raw)
            if not values:
                return [false()]
            bound = (
                [_as_uuid(value, field=name) for value in values]
                if name in _UUID_FILTERS
                else list(values)
            )
            clauses.append(_SCOPE_COLUMNS[name].in_(bound))
        if not clauses:
            raise ValueError("the 'filters' scope must carry at least one filter")
        return clauses
    raise ValueError(f"unsupported scope kind: {scope.kind!r}")


def _scope_sql(scope: ScopeSpec) -> tuple[str, list[Any], dict[str, Any]]:
    """The PostgreSQL form of the scope: SQL text, expanding binds, values."""
    if not isinstance(scope, ScopeSpec):
        raise TypeError("scope must be a contract ScopeSpec")
    if scope.kind == SCOPE_ALL:
        if scope.predicate not in (None, {}):
            raise ValueError("the 'all' scope takes no predicate")
        return "", [], {}
    if scope.kind == SCOPE_DOCUMENTS:
        values = _as_values("document_ids", scope.predicate)
        if not values:
            return "AND 1=0", [], {}
        return (
            "AND r.document_id IN :document_ids",
            [bindparam("document_ids", expanding=True)],
            {"document_ids": [_as_uuid(value, field="document_id") for value in values]},
        )
    if scope.kind == SCOPE_FILTERS:
        if not isinstance(scope.predicate, Mapping):
            raise ValueError("the 'filters' scope takes a mapping")
        unknown = set(scope.predicate) - set(_SCOPE_SQL)
        if unknown:
            raise ValueError(f"unknown scope filter(s): {sorted(unknown)}")
        fragments: list[str] = []
        params: list[Any] = []
        values_by_name: dict[str, Any] = {}
        for name, raw in scope.predicate.items():
            values = _as_values(name, raw)
            if not values:
                return "AND 1=0", [], {}
            bound = (
                [_as_uuid(value, field=name) for value in values]
                if name in _UUID_FILTERS
                else list(values)
            )
            fragments.append(f"AND {_SCOPE_SQL[name]} IN :{name}")
            params.append(bindparam(name, expanding=True))
            values_by_name[name] = bound
        if not fragments:
            raise ValueError("the 'filters' scope must carry at least one filter")
        return " ".join(fragments), params, values_by_name
    raise ValueError(f"unsupported scope kind: {scope.kind!r}")


def _make_sessionmaker(bind: Engine | sessionmaker[Session]) -> sessionmaker[Session]:
    return sessionmaker(bind=bind, expire_on_commit=False) if isinstance(bind, Engine) else bind


class SessionBackedBackend:
    """Shared transaction ownership; subclasses implement the index hooks."""

    name: str
    capabilities: BackendCaps

    def __init__(self, bind: Engine | sessionmaker[Session]) -> None:
        self._session_factory = _make_sessionmaker(bind)

    @staticmethod
    def _space_id(space: VectorSpace) -> uuid.UUID:
        if space.space_id is None:
            raise VectorSpaceNotFound(
                f"vector space {space.name!r} has no space_id — "
                "resolve it through VectorStoreService"
            )
        return _as_uuid(space.space_id, field="space_id")

    def _index_table(self, space: VectorSpace) -> str:
        if space.index_table is None:
            raise VectorIndexMissing(
                f"space {space.name!r} has no physical index; provision it first"
            )
        return validate_index_table(space.index_table)

    def ensure_space(self, space: VectorSpace) -> None:
        raise NotImplementedError

    def upsert_index(
        self, session: Session, space: VectorSpace, records: Sequence[IndexRecord]
    ) -> None:
        raise NotImplementedError

    def delete_document_index(self, session: Session, space: VectorSpace, document_id: str) -> None:
        raise NotImplementedError

    def delete_record_ids_index(
        self, session: Session, space: VectorSpace, record_ids: Sequence[uuid.UUID]
    ) -> None:
        """Delete stale records from the physical index (metadata is the service's)."""
        raise NotImplementedError

    def fetch_vectors(
        self, space: VectorSpace, record_ids: Sequence[uuid.UUID]
    ) -> dict[str, tuple[float, ...]]:
        """Read stored vectors back by record id (the read path's query source).

        ``similar_documents`` needs a document's own vectors as the query, and
        they live in the physical index under pgvector/sqlite-vec while the
        metadata column is ``NULL``. Returning them through the backend keeps
        one storage seam; ids the backend does not hold are simply absent.
        """
        if not record_ids:
            return {}
        with self._session_factory() as session:
            return self._fetch_vectors(session, space, record_ids)

    def _fetch_vectors(
        self, session: Session, space: VectorSpace, record_ids: Sequence[uuid.UUID]
    ) -> dict[str, tuple[float, ...]]:
        raise NotImplementedError

    def upsert(self, space: VectorSpace, records: Sequence[IndexRecord]) -> None:
        """Write index rows in one short transaction (contract shape)."""
        if not records:
            return
        with self._session_factory() as session:
            self.upsert_index(session, space, records)
            session.commit()

    def delete_document(self, space: VectorSpace, document_id: str) -> None:
        """Delete this backend's index rows for one document."""
        with self._session_factory() as session:
            self.delete_document_index(session, space, document_id)
            session.commit()

    def search(
        self,
        space: VectorSpace,
        query: Sequence[float],
        *,
        views: Sequence[str],
        scope: ScopeSpec,
        limit: int,
        ef_search: int | None = None,
    ) -> list[IndexHit]:
        raise NotImplementedError

    def count(self, space: VectorSpace) -> int:
        raise NotImplementedError

    def health(self, space: VectorSpace) -> BackendHealth:
        raise NotImplementedError


class LinearBackend(SessionBackedBackend, VectorBackend):
    """Exact cosine scan over ``vector_records.embedding`` (plan 50 §2.3).

    The fallback store for deployments without pgvector/sqlite-vec: honest
    about its absence of ANN (``capabilities.ann is False``), capped at
    ``LINEAR_CAP_ROWS`` vectors, and deterministic — ties break on
    ``document_id`` then ``record_id``. Scope filters are applied inside the
    scan (SQL), so an excluded document can never be returned.
    """

    name = BACKEND_LINEAR
    capabilities = BACKEND_CAPS[BACKEND_LINEAR]

    def _assert_linear(self, space: VectorSpace) -> None:
        if space.index_table is not None:
            raise VectorSpaceMismatch(
                f"space {space.name!r} declares physical index {space.index_table!r}; "
                "the linear backend owns no index table"
            )

    def ensure_space(self, space: VectorSpace) -> None:
        self._space_id(space)
        self._assert_linear(space)

    def upsert_index(
        self, session: Session, space: VectorSpace, records: Sequence[IndexRecord]
    ) -> None:
        """Write only the embedding column — metadata rows are the service's."""
        self._assert_linear(space)
        space_id = self._space_id(space)
        for record in records:
            if len(record.embedding) != space.dim:
                raise VectorSpaceMismatch(
                    f"record {record.record_id} has dim {len(record.embedding)}, "
                    f"space {space.name!r} expects {space.dim}"
                )
        record_ids = [_as_uuid(record.record_id, field="record_id") for record in records]
        stored = {
            row.id: row
            for row in session.scalars(
                select(VectorRecord).where(
                    VectorRecord.id.in_(record_ids),
                    VectorRecord.space_id == space_id,
                )
            )
        }
        for record in records:
            row = stored.get(_as_uuid(record.record_id, field="record_id"))
            if row is None:
                raise VectorRecordNotFound(
                    f"record {record.record_id} has no metadata row in space {space.name!r}"
                )
            row.embedding = _pack(record.embedding)

    def delete_document_index(self, session: Session, space: VectorSpace, document_id: str) -> None:
        """No separate index: the record rows (and their embeddings) cascade."""
        del session, space, document_id

    def delete_record_ids_index(
        self, session: Session, space: VectorSpace, record_ids: Sequence[uuid.UUID]
    ) -> None:
        """No separate index: deleting the metadata rows removes their embeddings."""
        del session, space, record_ids

    def _fetch_vectors(
        self, session: Session, space: VectorSpace, record_ids: Sequence[uuid.UUID]
    ) -> dict[str, tuple[float, ...]]:
        """The BLOB column is the only copy under the linear backend."""
        rows = session.execute(
            select(VectorRecord.id, VectorRecord.embedding).where(
                VectorRecord.space_id == self._space_id(space),
                VectorRecord.id.in_(list(record_ids)),
                VectorRecord.embedding.is_not(None),
            )
        )
        return {str(record_id): _unpack(blob) for record_id, blob in rows}

    def search(
        self,
        space: VectorSpace,
        query: Sequence[float],
        *,
        views: Sequence[str],
        scope: ScopeSpec,
        limit: int,
        ef_search: int | None = None,
    ) -> list[IndexHit]:
        """Exact top-``limit`` over the scoped records of the requested views."""
        del ef_search  # no ANN knobs on the exact scan
        if limit <= 0 or not views or not query:
            return []
        if len(query) != space.dim:
            logger.warning(
                "linear search query dim %s != space %r dim %s — refusing",
                len(query),
                space.name,
                space.dim,
            )
            return []
        self._assert_linear(space)
        space_id = self._space_id(space)
        with self._session_factory() as session:
            statement = (
                select(VectorRecord, VectorDocument)
                .join(VectorDocument, VectorRecord.document_id == VectorDocument.id)
                .where(
                    VectorRecord.space_id == space_id,
                    VectorRecord.view.in_(list(views)),
                    VectorRecord.embedding.is_not(None),
                )
            )
            scope_clauses = _scope_clauses(scope)
            if scope_clauses is not None:
                statement = statement.where(*scope_clauses)
            scoped_count = int(
                session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            )
            if scoped_count > self.capabilities.max_recommended_rows:
                raise VectorBackendOverCap(
                    f"{scoped_count} scoped candidates exceed the linear cap "
                    f"({self.capabilities.max_recommended_rows}) — serve lexical instead"
                )
            hits: list[IndexHit] = []
            for record, document in session.execute(statement):
                stored = _unpack(record.embedding)
                if len(stored) != len(query):
                    continue
                similarity = cosine(query, stored)
                hits.append(
                    IndexHit(
                        record_id=str(record.id),
                        document_id=str(document.id),
                        view=record.view,
                        distance=1.0 - similarity,
                        similarity=similarity,
                        backend=self.name,
                    )
                )
        hits.sort(key=lambda hit: (-hit.similarity, hit.document_id, hit.record_id))
        return hits[:limit]

    def count(self, space: VectorSpace) -> int:
        self._assert_linear(space)
        space_id = self._space_id(space)
        with self._session_factory() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(VectorRecord)
                    .where(
                        VectorRecord.space_id == space_id,
                        VectorRecord.embedding.is_not(None),
                    )
                )
                or 0
            )

    def health(self, space: VectorSpace) -> BackendHealth:
        try:
            self._assert_linear(space)
            records = self.count(space)
        except VectorBackendError as exc:
            return BackendHealth(ok=False, detail=str(exc))
        if records > self.capabilities.max_recommended_rows:
            return BackendHealth(
                ok=True,
                detail=(
                    f"over the linear cap: {records} vectors > "
                    f"{self.capabilities.max_recommended_rows} recommended"
                ),
            )
        return BackendHealth(ok=True, detail=f"linear scan, {records} vector(s)")


def _version_tuple(version: str | None) -> tuple[int, ...]:
    if not version:
        return ()
    parts: list[int] = []
    for part in version.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


class PgVectorBackend(SessionBackedBackend, VectorBackend):
    """pgvector/HNSW adapter (plan 50 §3.4, §4).

    The scope predicate is part of the ANN query's WHERE clause (never a
    Python post-filter); ``hnsw.ef_search`` and ``hnsw.iterative_scan`` are
    set per query with ``SET LOCAL``. At or below
    ``EXACT_SCAN_THRESHOLD`` scoped candidates the scan is forced exact so
    small installs and parity tests stay deterministic.
    """

    name = BACKEND_PGVECTOR
    capabilities = BACKEND_CAPS[BACKEND_PGVECTOR]

    def __init__(self, bind: Engine | sessionmaker[Session]) -> None:
        super().__init__(bind)
        self._extension_version: str | None = None
        self._version_probed = False

    def _probe_version(self, session: Session) -> str | None:
        if not self._version_probed:
            version = session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
            if version is not None:
                self._extension_version = str(version)
                self._version_probed = True
        return self._extension_version

    def _require_extension(self, session: Session) -> str:
        version = self._probe_version(session)
        if version is None:
            raise VectorIndexMissing(
                "pgvector is not installed — semantic search is unavailable on PostgreSQL"
            )
        return str(version)

    @staticmethod
    def _table_dim(session: Session, table: str) -> int | None:
        declared = session.execute(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) "
                "FROM pg_attribute a "
                "WHERE a.attrelid = CAST(:table AS regclass) "
                "AND a.attname = 'embedding' AND NOT a.attisdropped"
            ),
            {"table": table},
        ).scalar()
        if declared is None:
            return None
        prefix = "vector("
        text_value = str(declared)
        if not text_value.startswith(prefix) or not text_value.endswith(")"):
            raise VectorIndexMissing(f"index {table!r} has unexpected embedding type {declared!r}")
        return int(text_value[len(prefix) : -1])

    def ensure_space(self, space: VectorSpace) -> None:
        table = self._index_table(space)
        with self._session_factory() as session:
            self._require_extension(session)
            if not session.execute(
                text("SELECT to_regclass(CAST(:table AS text))"), {"table": table}
            ).scalar():
                raise VectorIndexMissing(
                    f"index table {table!r} does not exist; provision it first"
                )
            declared = self._table_dim(session, table)
            if declared != space.dim:
                raise VectorSpaceMismatch(
                    f"index {table!r} is vector({declared}), space {space.name!r} expects "
                    f"vector({space.dim})"
                )

    def upsert_index(
        self, session: Session, space: VectorSpace, records: Sequence[IndexRecord]
    ) -> None:
        table = self._index_table(space)
        self._require_extension(session)
        for record in records:
            if len(record.embedding) != space.dim:
                raise VectorSpaceMismatch(
                    f"record {record.record_id} has dim {len(record.embedding)}, "
                    f"space {space.name!r} expects {space.dim}"
                )
        statement = text(
            f"INSERT INTO {table} (record_id, embedding) "
            "VALUES (:record_id, CAST(:embedding AS vector)) "
            "ON CONFLICT (record_id) DO UPDATE SET embedding = EXCLUDED.embedding"
        )
        for record in records:
            session.execute(
                statement,
                {
                    "record_id": _as_uuid(record.record_id, field="record_id"),
                    "embedding": _vector_literal(record.embedding),
                },
            )

    def delete_document_index(self, session: Session, space: VectorSpace, document_id: str) -> None:
        table = self._index_table(space)
        session.execute(
            text(
                f"DELETE FROM {table} WHERE record_id IN ("
                "SELECT id FROM vector_records "
                "WHERE document_id = :document_id AND space_id = :space_id)"
            ),
            {
                "document_id": _as_uuid(document_id, field="document_id"),
                "space_id": self._space_id(space),
            },
        )

    def delete_record_ids_index(
        self, session: Session, space: VectorSpace, record_ids: Sequence[uuid.UUID]
    ) -> None:
        if not record_ids:
            return
        table = self._index_table(space)
        session.execute(
            text(f"DELETE FROM {table} WHERE record_id IN :record_ids").bindparams(
                bindparam("record_ids", expanding=True)
            ),
            {"record_ids": list(record_ids)},
        )

    def _scoped_count(
        self, session: Session, space: VectorSpace, views: Sequence[str], scope: ScopeSpec
    ) -> int:
        statement = (
            select(func.count())
            .select_from(VectorRecord)
            .join(VectorDocument, VectorRecord.document_id == VectorDocument.id)
            .where(
                VectorRecord.space_id == self._space_id(space),
                VectorRecord.view.in_(list(views)),
            )
        )
        clauses = _scope_clauses(scope)
        if clauses is not None:
            statement = statement.where(*clauses)
        return int(session.scalar(statement) or 0)

    def _fetch_vectors(
        self, session: Session, space: VectorSpace, record_ids: Sequence[uuid.UUID]
    ) -> dict[str, tuple[float, ...]]:
        """The HNSW table is the only copy; the vector casts back through text."""
        table = self._index_table(space)
        rows = session.execute(
            text(
                f"SELECT record_id, CAST(embedding AS text) AS embedding FROM {table} "
                "WHERE record_id IN :record_ids"
            ).bindparams(bindparam("record_ids", expanding=True)),
            {"record_ids": list(record_ids)},
        )
        return {str(row.record_id): _parse_pg_vector(str(row.embedding)) for row in rows}

    def _set_tuning(self, session: Session, version: str, ef_search: int) -> None:
        session.execute(text("SELECT CAST('[1]' AS vector)"))
        session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
        if _version_tuple(version) >= (0, 8, 0):
            session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))

    def search(
        self,
        space: VectorSpace,
        query: Sequence[float],
        *,
        views: Sequence[str],
        scope: ScopeSpec,
        limit: int,
        ef_search: int | None = None,
    ) -> list[IndexHit]:
        if limit <= 0 or not views or not query:
            return []
        if len(query) != space.dim:
            logger.warning(
                "pgvector search query dim %s != space %r dim %s — refusing",
                len(query),
                space.name,
                space.dim,
            )
            return []
        table = self._index_table(space)
        scope_sql, scope_params, scope_values = _scope_sql(scope)
        with self._session_factory() as session:
            version = self._require_extension(session)
            if not session.execute(
                text("SELECT to_regclass(CAST(:table AS text))"), {"table": table}
            ).scalar():
                raise VectorIndexMissing(f"index table {table!r} does not exist")
            scoped_count = self._scoped_count(session, space, views, scope)
            if scoped_count > self.capabilities.max_recommended_rows:
                raise VectorBackendOverCap(
                    f"{scoped_count} scoped candidates exceed the pgvector cap "
                    f"({self.capabilities.max_recommended_rows}) — serve lexical instead"
                )
            if scoped_count == 0:
                return []
            exact = scoped_count <= EXACT_SCAN_THRESHOLD
            self._set_tuning(session, version, max(int(ef_search or EF_SEARCH_DEFAULT), 1))
            if exact:
                session.execute(text("SET LOCAL enable_indexscan = off"))
                session.execute(text("SET LOCAL enable_bitmapscan = off"))
                scan_limit = min(limit, scoped_count)
            else:
                scan_limit = min(max(limit * CANDIDATE_MULTIPLIER, limit), scoped_count)
            statement = text(
                f"""
                SELECT v.record_id AS record_id,
                       r.document_id AS document_id,
                       r.view AS view,
                       (v.embedding <=> CAST(:query AS vector)) AS distance
                FROM {table} v
                JOIN vector_records r ON r.id = v.record_id
                JOIN vector_documents d ON d.id = r.document_id
                WHERE r.space_id = :space_id
                  AND r.view IN :views
                  {scope_sql}
                ORDER BY distance ASC
                LIMIT :limit
                """
            ).bindparams(bindparam("views", expanding=True), *scope_params)
            rows = session.execute(
                statement,
                {
                    "query": _vector_literal(query),
                    "space_id": self._space_id(space),
                    "views": list(views),
                    "limit": scan_limit,
                    **scope_values,
                },
            ).all()
        hits = [
            IndexHit(
                record_id=str(row.record_id),
                document_id=str(row.document_id),
                view=str(row.view),
                distance=float(row.distance),
                similarity=1.0 - float(row.distance),
                backend=self.name,
            )
            for row in rows
        ]
        hits.sort(key=lambda hit: (hit.distance, hit.document_id, hit.record_id))
        return hits[:limit]

    def count(self, space: VectorSpace) -> int:
        table = self._index_table(space)
        with self._session_factory() as session:
            self._require_extension(session)
            return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)

    def health(self, space: VectorSpace) -> BackendHealth:
        table = space.index_table
        if table is None:
            return BackendHealth(ok=False, detail="space has no physical index (linear backend)")
        try:
            validate_index_table(table)
            with self._session_factory() as session:
                version = self._probe_version(session)
                if version is None:
                    return BackendHealth(ok=False, detail="pgvector extension is not installed")
                if not session.execute(
                    text("SELECT to_regclass(CAST(:table AS text))"), {"table": table}
                ).scalar():
                    return BackendHealth(ok=False, detail=f"index table {table!r} is missing")
                declared = self._table_dim(session, table)
                if declared != space.dim:
                    return BackendHealth(
                        ok=False,
                        detail=(
                            f"index {table!r} is vector({declared}), expected vector({space.dim})"
                        ),
                    )
                index_present = (
                    session.execute(
                        text(
                            "SELECT 1 FROM pg_indexes WHERE tablename = :table "
                            "AND indexname = :index"
                        ),
                        {"table": table, "index": f"ix_{table}_hnsw"},
                    ).scalar()
                    is not None
                )
                rows = int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
        except VectorBackendError as exc:
            return BackendHealth(ok=False, detail=str(exc))
        except Exception as exc:  # pragma: no cover - a broken DB is not "healthy"
            return BackendHealth(ok=False, detail=f"pgvector health probe failed: {exc}")
        if not index_present:
            return BackendHealth(ok=False, detail=f"index {table!r} has no HNSW cosine index")
        return BackendHealth(
            ok=True,
            detail=f"pgvector {version}, {table} vector({space.dim}), {rows} row(s)",
        )


class SqliteVecBackend(SessionBackedBackend, VectorBackend):
    """sqlite-vec ``vec0`` adapter (plan 50 §3.4, §4).

    Uses a per-record rowid map so hydration is one indexed lookup. Scope is
    over-fetched then post-filtered against metadata; the safety invariant
    holds after truncation because the allowed-record set comes from SQL,
    never from the ANN result itself.

    vec0 is a brute-force scan, so it can answer *exactly* when the whole
    index is requested. When the metadata scoped candidate count is at or
    below ``EXACT_SCAN_THRESHOLD`` the adapter asks for all rows and takes
    the top ``limit`` after filtering — deterministic and exact, matching
    the PostgreSQL path's rule (the threshold applies to the scoped count,
    not the space size) with a single query. Above it the bounded
    over-fetch resumes: ``k`` expands until the limit is met or the index
    is exhausted, so scope safety still holds, but a selective query can
    cost several scans instead of one.
    """

    name = BACKEND_SQLITE_VEC
    capabilities = BACKEND_CAPS[BACKEND_SQLITE_VEC]

    @staticmethod
    def _load(session: Session) -> Any:
        try:
            import sqlite_vec
        except ImportError as exc:  # pragma: no cover - desktop extra absent
            raise VectorIndexMissing("sqlite-vec is not installed") from exc
        try:
            raw = session.connection().connection.driver_connection
            if raw is None:
                raise VectorIndexMissing("sqlite connection has no driver connection")
            raw.enable_load_extension(True)
            sqlite_vec.load(raw)
            session.connection().exec_driver_sql("SELECT vec_version()").scalar()
        except Exception as exc:
            raise VectorIndexMissing(f"sqlite-vec could not be loaded: {exc}") from exc
        return sqlite_vec

    @staticmethod
    def _table_dim(session: Session, table: str) -> int | None:
        sql = session.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
            {"name": table},
        ).scalar()
        if sql is None:
            return None
        marker = "float["
        text_value = str(sql)
        start = text_value.find(marker)
        if start < 0:
            raise VectorIndexMissing(f"index {table!r} has no float[dim] embedding column")
        end = text_value.find("]", start)
        return int(text_value[start + len(marker) : end])

    def ensure_space(self, space: VectorSpace) -> None:
        table = self._index_table(space)
        with self._session_factory() as session:
            self._load(session)
            declared = self._table_dim(session, table)
            if declared is None:
                raise VectorIndexMissing(
                    f"index table {table!r} does not exist; provision it first"
                )
            if declared != space.dim:
                raise VectorSpaceMismatch(
                    f"index {table!r} is float[{declared}], space {space.name!r} expects "
                    f"float[{space.dim}]"
                )
            if not session.execute(
                text(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'vector_entry_ids'"
                )
            ).scalar():
                raise VectorIndexMissing("the vector_entry_ids rowid map is missing")

    def upsert_index(
        self, session: Session, space: VectorSpace, records: Sequence[IndexRecord]
    ) -> None:
        sqlite_vec = self._load(session)
        table = self._index_table(space)
        for record in records:
            if len(record.embedding) != space.dim:
                raise VectorSpaceMismatch(
                    f"record {record.record_id} has dim {len(record.embedding)}, "
                    f"space {space.name!r} expects {space.dim}"
                )
            record_id = str(_as_uuid(record.record_id, field="record_id"))
            rowid = rowid_for(record_id)
            mapped = session.execute(
                text("SELECT record_id FROM vector_entry_ids WHERE record_rowid = :rowid"),
                {"rowid": rowid},
            ).scalar()
            if mapped is not None and str(mapped) != record_id:
                raise VectorRowidCollision(
                    f"rowid {rowid} already maps to record {mapped!r}, not {record_id!r}"
                )
            if mapped is None:
                session.execute(
                    text(
                        "INSERT INTO vector_entry_ids (record_rowid, record_id) "
                        "VALUES (:rowid, :record_id)"
                    ),
                    {"rowid": rowid, "record_id": record_id},
                )
            payload = sqlite_vec.serialize_float32(list(record.embedding))
            present = session.execute(
                text(f"SELECT 1 FROM {table} WHERE record_rowid = :rowid"), {"rowid": rowid}
            ).scalar()
            if present is None:
                session.execute(
                    text(
                        f"INSERT INTO {table} (record_rowid, embedding) VALUES (:rowid, :embedding)"
                    ),
                    {"rowid": rowid, "embedding": payload},
                )
            else:
                session.execute(
                    text(f"UPDATE {table} SET embedding = :embedding WHERE record_rowid = :rowid"),
                    {"rowid": rowid, "embedding": payload},
                )

    def delete_document_index(self, session: Session, space: VectorSpace, document_id: str) -> None:
        self._load(session)
        table = self._index_table(space)
        record_ids = [
            str(value)
            for value in session.scalars(
                select(VectorRecord.id).where(
                    VectorRecord.document_id == _as_uuid(document_id, field="document_id"),
                    VectorRecord.space_id == self._space_id(space),
                )
            )
        ]
        if not record_ids:
            return
        rowids = [rowid_for(value) for value in record_ids]
        for start in range(0, len(rowids), 500):
            chunk = rowids[start : start + 500]
            session.execute(
                text(f"DELETE FROM {table} WHERE record_rowid IN :rowids").bindparams(
                    bindparam("rowids", expanding=True)
                ),
                {"rowids": chunk},
            )
            session.execute(
                text("DELETE FROM vector_entry_ids WHERE record_rowid IN :rowids").bindparams(
                    bindparam("rowids", expanding=True)
                ),
                {"rowids": chunk},
            )

    def delete_record_ids_index(
        self, session: Session, space: VectorSpace, record_ids: Sequence[uuid.UUID]
    ) -> None:
        if not record_ids:
            return
        self._load(session)
        table = self._index_table(space)
        rowids = [rowid_for(value) for value in record_ids]
        for start in range(0, len(rowids), 500):
            chunk = rowids[start : start + 500]
            session.execute(
                text(f"DELETE FROM {table} WHERE record_rowid IN :rowids").bindparams(
                    bindparam("rowids", expanding=True)
                ),
                {"rowids": chunk},
            )
            session.execute(
                text("DELETE FROM vector_entry_ids WHERE record_rowid IN :rowids").bindparams(
                    bindparam("rowids", expanding=True)
                ),
                {"rowids": chunk},
            )

    def _scoped_count(
        self, session: Session, space: VectorSpace, views: Sequence[str], scope: ScopeSpec
    ) -> int:
        statement = (
            select(func.count())
            .select_from(VectorRecord)
            .join(VectorDocument, VectorRecord.document_id == VectorDocument.id)
            .where(
                VectorRecord.space_id == self._space_id(space),
                VectorRecord.view.in_(list(views)),
            )
        )
        clauses = _scope_clauses(scope)
        if clauses is not None:
            statement = statement.where(*clauses)
        return int(session.scalar(statement) or 0)

    def _fetch_vectors(
        self, session: Session, space: VectorSpace, record_ids: Sequence[uuid.UUID]
    ) -> dict[str, tuple[float, ...]]:
        """Read the vec0 payload back through the rowid map."""
        self._load(session)
        table = self._index_table(space)
        rowids = [rowid_for(str(record_id)) for record_id in record_ids]
        mapped = {
            int(row.record_rowid): str(row.record_id)
            for row in session.execute(
                text(
                    "SELECT record_rowid, record_id FROM vector_entry_ids "
                    "WHERE record_rowid IN :rowids"
                ).bindparams(bindparam("rowids", expanding=True)),
                {"rowids": rowids},
            )
        }
        if not mapped:
            return {}
        rows = session.execute(
            text(
                f"SELECT record_rowid, embedding FROM {table} WHERE record_rowid IN :rowids"
            ).bindparams(bindparam("rowids", expanding=True)),
            {"rowids": list(mapped)},
        )
        return {
            mapped[int(row.record_rowid)]: _unpack(row.embedding)
            for row in rows
            if int(row.record_rowid) in mapped
        }

    def _allowed_records(
        self,
        session: Session,
        space: VectorSpace,
        record_ids: Sequence[uuid.UUID],
        views: Sequence[str],
        scope: ScopeSpec,
    ) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
        if not record_ids:
            return {}
        statement = (
            select(VectorRecord.id, VectorRecord.document_id, VectorRecord.view)
            .join(VectorDocument, VectorRecord.document_id == VectorDocument.id)
            .where(
                VectorRecord.id.in_(list(record_ids)),
                VectorRecord.space_id == self._space_id(space),
                VectorRecord.view.in_(list(views)),
            )
        )
        clauses = _scope_clauses(scope)
        if clauses is not None:
            statement = statement.where(*clauses)
        return {row[0]: (row[1], row[2]) for row in session.execute(statement)}

    def search(
        self,
        space: VectorSpace,
        query: Sequence[float],
        *,
        views: Sequence[str],
        scope: ScopeSpec,
        limit: int,
        ef_search: int | None = None,
    ) -> list[IndexHit]:
        del ef_search  # vec0 has no per-query ef_search knob
        if limit <= 0 or not views or not query:
            return []
        if len(query) != space.dim:
            logger.warning(
                "sqlite-vec search query dim %s != space %r dim %s — refusing",
                len(query),
                space.name,
                space.dim,
            )
            return []
        table = self._index_table(space)
        with self._session_factory() as session:
            sqlite_vec = self._load(session)
            total = int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
            if total == 0:
                return []
            if total > self.capabilities.max_recommended_rows:
                raise VectorBackendOverCap(
                    f"{total} vectors exceed the sqlite-vec cap "
                    f"({self.capabilities.max_recommended_rows}) — serve lexical instead"
                )
            payload = sqlite_vec.serialize_float32(list(query))
            scoped_count = self._scoped_count(session, space, views, scope)
            if scoped_count == 0:
                return []
            exact = scoped_count <= EXACT_SCAN_THRESHOLD
            k = total if exact else min(max(limit * CANDIDATE_MULTIPLIER, limit), total)
            hits: list[IndexHit] = []
            while True:
                rows = session.execute(
                    text(
                        f"SELECT record_rowid, distance FROM {table} "
                        "WHERE embedding MATCH :query AND k = :k"
                    ),
                    {"query": payload, "k": k},
                ).all()
                rowids = [int(row.record_rowid) for row in rows]
                mapped = (
                    {
                        int(row.record_rowid): str(row.record_id)
                        for row in session.execute(
                            text(
                                "SELECT record_rowid, record_id FROM vector_entry_ids "
                                "WHERE record_rowid IN :rowids"
                            ).bindparams(bindparam("rowids", expanding=True)),
                            {"rowids": rowids},
                        )
                    }
                    if rowids
                    else {}
                )
                record_ids = [_as_uuid(value, field="record_id") for value in mapped.values()]
                allowed = self._allowed_records(session, space, record_ids, views, scope)
                by_id = {str(key): value for key, value in allowed.items()}
                hits = []
                for row in rows:
                    record_id = mapped.get(int(row.record_rowid))
                    if record_id is None or record_id not in by_id:
                        continue
                    document_id, view = by_id[record_id]
                    distance = float(row.distance)
                    hits.append(
                        IndexHit(
                            record_id=record_id,
                            document_id=str(document_id),
                            view=view,
                            distance=distance,
                            similarity=1.0 - distance,
                            backend=self.name,
                        )
                    )
                if len(hits) >= limit or k >= total:
                    break
                k = min(k * 2, total)
            if len(hits) < limit and k >= total:
                logger.info(
                    "sqlite-vec scope post-filter returned %s of %s requested hit(s) for space %r",
                    len(hits),
                    limit,
                    space.name,
                )
        hits.sort(key=lambda hit: (hit.distance, hit.document_id, hit.record_id))
        return hits[:limit]

    def count(self, space: VectorSpace) -> int:
        table = self._index_table(space)
        with self._session_factory() as session:
            self._load(session)
            return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)

    def health(self, space: VectorSpace) -> BackendHealth:
        table = space.index_table
        if table is None:
            return BackendHealth(ok=False, detail="space has no physical index (linear backend)")
        try:
            validate_index_table(table)
            with self._session_factory() as session:
                self._load(session)
                declared = self._table_dim(session, table)
                if declared is None:
                    return BackendHealth(ok=False, detail=f"index table {table!r} is missing")
                if declared != space.dim:
                    return BackendHealth(
                        ok=False,
                        detail=(
                            f"index {table!r} is float[{declared}], expected float[{space.dim}]"
                        ),
                    )
                if not session.execute(
                    text(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                        "AND name = 'vector_entry_ids'"
                    )
                ).scalar():
                    return BackendHealth(
                        ok=False, detail="the vector_entry_ids rowid map is missing"
                    )
                rows = int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
                version = session.connection().exec_driver_sql("SELECT vec_version()").scalar()
        except VectorBackendError as exc:
            return BackendHealth(ok=False, detail=str(exc))
        except Exception as exc:  # pragma: no cover - a broken DB is not "healthy"
            return BackendHealth(ok=False, detail=f"sqlite-vec health probe failed: {exc}")
        return BackendHealth(
            ok=True,
            detail=f"sqlite-vec {version}, {table} float[{space.dim}], {rows} row(s)",
        )


def pgvector_available(bind: Engine) -> bool:
    """True when the connected PostgreSQL instance has the ``vector`` extension."""
    if bind.dialect.name != "postgresql":
        return False
    try:
        with bind.connect() as connection:
            return (
                connection.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                ).scalar()
                is not None
            )
    except Exception:  # pragma: no cover - a broken probe means "not available"
        logger.warning("pgvector availability probe failed", exc_info=True)
        return False


def sqlite_vec_available(bind: Engine) -> bool:
    """True when ``vec_version()`` answers after a defensive extension load."""
    if bind.dialect.name != "sqlite":
        return False
    try:
        import sqlite_vec

        with bind.connect() as connection:
            raw = connection.connection.driver_connection
            if raw is None:
                return False
            raw.enable_load_extension(True)
            sqlite_vec.load(raw)
            connection.exec_driver_sql("SELECT vec_version()").scalar()
        return True
    except Exception:
        return False


def choose_backend(bind: Engine) -> VectorBackend:
    """Select the backend once, honestly degrading to linear.

    No deployment ever receives an ANN backend whose extension/driver probe
    failed; the linear fallback publishes ``ann=False``.
    """
    dialect = bind.dialect.name
    if dialect == "postgresql" and pgvector_available(bind):
        return PgVectorBackend(bind)
    if dialect == "sqlite" and sqlite_vec_available(bind):
        return SqliteVecBackend(bind)
    return LinearBackend(bind)


_backend_cache: dict[int, VectorBackend] = {}


def get_backend(bind: Engine) -> VectorBackend:
    """One backend per process (keyed by engine identity), no per-request probes."""
    key = id(bind)
    backend = _backend_cache.get(key)
    if backend is None:
        backend = choose_backend(bind)
        _backend_cache[key] = backend
    return backend


def reset_backend_cache() -> None:
    """Test hook: forget cached selections (engines are process-scoped in prod)."""
    _backend_cache.clear()


__all__ = [
    "LinearBackend",
    "PgVectorBackend",
    "ResolvedEmbedding",
    "SessionBackedBackend",
    "SqliteVecBackend",
    "VectorBackendError",
    "VectorBackendOverCap",
    "VectorDocumentNotFound",
    "VectorIndexMissing",
    "VectorRecordIdentityMismatch",
    "VectorRecordNotFound",
    "VectorRowidCollision",
    "VectorSpaceMismatch",
    "VectorSpaceNotFound",
    "assert_writer_matches_space",
    "choose_backend",
    "document_scope",
    "filter_scope",
    "get_backend",
    "pgvector_available",
    "reset_backend_cache",
    "rowid_for",
    "sqlite_vec_available",
    "writer_mismatch_reason",
]
