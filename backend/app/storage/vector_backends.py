"""App-side vector backend adapters and the one-per-process factory
(plan 50 §4, P1a).

The shared contract (DTOs, protocol, cosine, capabilities) is the vendored
``app.storage.vector_contract`` module. This module owns the SQL: the
linear fallback implemented over ``vector_records.embedding`` now; the
pgvector and sqlite-vec adapters land in plan 50 P1b. The factory never
fakes ANN: when the extension/driver is absent — or the ANN adapters are
not enabled yet — it returns the linear backend and publishes its honest
capabilities.

The protocol is synchronous (one shape for all three engines); the async
service layer calls these adapters from a worker thread. Writes own one
short transaction per call.
"""

from __future__ import annotations

import logging
import uuid
from array import array
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, delete, false, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.vector_model import (
    INDEX_TABLE_PATTERN,
    VectorDocument,
    VectorRecord,
)
from app.models.vector_model import (
    VectorSpace as VectorSpaceRow,
)
from app.storage.vector_contract import (
    BACKEND_CAPS,
    BACKEND_LINEAR,
    BACKEND_PGVECTOR,
    BACKEND_SQLITE_VEC,
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

logger = logging.getLogger(__name__)

# The ANN adapters are P1b work. Until they ship, the factory selects the
# linear backend on every deployment even where pgvector/sqlite-vec loads —
# never expose a backend that would silently return approximate results it
# cannot produce.
ANN_READY = False

SCOPE_ALL = "all"
SCOPE_DOCUMENTS = "documents"
SCOPE_FILTERS = "filters"

_SCOPE_COLUMNS = {
    "document_ids": VectorRecord.document_id,
    "kinds": VectorDocument.kind,
    "scope_types": VectorDocument.scope_type,
    "scope_ids": VectorDocument.scope_id,
    "profile_ids": VectorDocument.profile_id,
}
_UUID_FILTERS = {"document_ids", "scope_ids", "profile_ids"}


class VectorBackendError(RuntimeError):
    """Base failure for the storage adapters."""


class VectorSpaceNotFound(VectorBackendError):
    """The requested space has no persisted row."""


class VectorDocumentNotFound(VectorBackendError):
    """An upsert referenced a document that is not registered in the space."""


class VectorRecordIdentityMismatch(VectorBackendError):
    """The contract record id changed for the same (document, view, chunk)."""


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


class BackendNotImplemented(VectorBackendError, NotImplementedError):
    """The ANN adapter is scheduled for plan 50 P1b."""


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


def index_table_name(space_id: str | uuid.UUID) -> str:
    """Derive the physical ANN table name from the space UUID (no DDL).

    The provisioning seam (migration or ``scripts/vector_spaces.py``, P1b)
    owns the ``CREATE TABLE``; this helper is the single naming rule the
    model CHECK, provisioning and tests share.
    """
    return f"{INDEX_TABLE_PATTERN}{uuid.UUID(str(space_id)).hex[:8]}"


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

    Recognized keys: ``document_ids``, ``kinds``, ``scope_types``,
    ``scope_ids``, ``profile_ids``.
    """
    unknown = set(filters) - set(_SCOPE_COLUMNS)
    if unknown:
        raise ValueError(f"unknown scope filter(s): {sorted(unknown)}")
    return ScopeSpec(kind=SCOPE_FILTERS, predicate=dict(filters))


def _pack(embedding: Sequence[float]) -> bytes:
    return array("f", (float(value) for value in embedding)).tobytes()


def _unpack(blob: bytes | None) -> tuple[float, ...]:
    if not blob:
        return ()
    values = array("f")
    values.frombytes(blob)
    return tuple(values)


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


class LinearBackend(VectorBackend):
    """Exact cosine scan over ``vector_records.embedding`` (plan 50 §2.3).

    The fallback store for deployments without pgvector/sqlite-vec: honest
    about its absence of ANN (``capabilities.ann is False``), capped at
    ``LINEAR_CAP_ROWS`` vectors, and deterministic — ties break on
    ``document_id`` then ``record_id``. Scope filters are applied inside the
    scan (SQL), so an excluded document can never be returned.
    """

    name = BACKEND_LINEAR
    capabilities: BackendCaps = BACKEND_CAPS[BACKEND_LINEAR]

    def __init__(self, bind: Engine | sessionmaker[Session]) -> None:
        self._session_factory: sessionmaker[Session] = (
            sessionmaker(bind=bind, expire_on_commit=False) if isinstance(bind, Engine) else bind
        )

    def _space_row(self, session: Session, space: VectorSpace) -> VectorSpaceRow:
        if space.space_id is not None:
            row = session.get(VectorSpaceRow, _as_uuid(space.space_id, field="space_id"))
            if row is None:
                raise VectorSpaceNotFound(f"vector space id {space.space_id!r} has no row")
        else:
            row = session.scalars(
                select(VectorSpaceRow)
                .where(
                    VectorSpaceRow.name == space.name,
                    VectorSpaceRow.status == str(space.status),
                )
                .order_by(VectorSpaceRow.created_at.desc())
                .limit(1)
            ).first()
            if row is None:
                raise VectorSpaceNotFound(f"vector space {space.name!r} has no row")
        self._assert_row_matches(space, row)
        return row

    @staticmethod
    def _assert_row_matches(space: VectorSpace, row: VectorSpaceRow) -> None:
        """The persisted space is the trusted configuration; a stale DTO is refused."""
        reason = writer_mismatch_reason(
            space,
            ResolvedEmbedding(
                provider=row.provider,
                model=row.model,
                dim=row.dim,
                normalize=row.normalize,
                query_prefix=row.query_prefix,
                document_prefix=row.document_prefix,
            ),
        )
        if reason is not None:
            raise VectorSpaceMismatch(f"space DTO disagrees with the persisted row — {reason}")
        if row.status != str(space.status):
            raise VectorSpaceMismatch(
                f"space status mismatch — row={row.status!r}, dto={str(space.status)!r}"
            )

    def ensure_space(self, space: VectorSpace) -> None:
        """Verify the metadata row; never issue DDL (provisioning is a job/migration)."""
        with self._session_factory() as session:
            self._space_row(session, space)

    def upsert(self, space: VectorSpace, records: Sequence[IndexRecord]) -> None:
        """Write records in place, one transaction per call.

        The unique ``(document_id, view, chunk_index)`` key is the update
        target: a changed content hash/embedding replaces the stored vector.
        A record whose dimension disagrees with the space is a writer bug and
        raises instead of writing an unscannable row.
        """
        if not records:
            return
        packed: list[tuple[IndexRecord, bytes]] = []
        for record in records:
            if len(record.embedding) != space.dim:
                raise VectorSpaceMismatch(
                    f"record {record.record_id} has dim {len(record.embedding)}, "
                    f"space {space.name!r} expects {space.dim}"
                )
            packed.append((record, _pack(record.embedding)))

        document_ids = {_as_uuid(record.document_id, field="document_id") for record, _ in packed}
        with self._session_factory() as session:
            space_row = self._space_row(session, space)
            documents = {
                document.id: document
                for document in session.scalars(
                    select(VectorDocument).where(
                        VectorDocument.id.in_(document_ids),
                        VectorDocument.space_id == space_row.id,
                    )
                )
            }
            missing = document_ids - set(documents)
            if missing:
                raise VectorDocumentNotFound(
                    f"{len(missing)} document(s) are not registered in space {space.name!r}"
                )
            for record, blob in packed:
                record_id = _as_uuid(record.record_id, field="record_id")
                document = documents[_as_uuid(record.document_id, field="document_id")]
                stored = session.scalars(
                    select(VectorRecord).where(
                        VectorRecord.document_id == document.id,
                        VectorRecord.view == record.view,
                        VectorRecord.chunk_index == record.chunk_index,
                    )
                ).first()
                if stored is None:
                    session.add(
                        VectorRecord(
                            id=record_id,
                            document_id=document.id,
                            space_id=space_row.id,
                            view=record.view,
                            chunk_index=record.chunk_index,
                            char_start=record.char_start,
                            char_end=record.char_end,
                            content_hash=record.content_hash,
                            embedding=blob,
                        )
                    )
                else:
                    if stored.id != record_id:
                        raise VectorRecordIdentityMismatch(
                            "record identity changed for "
                            f"({document.id}, {record.view}, {record.chunk_index})"
                        )
                    stored.space_id = space_row.id
                    stored.char_start = record.char_start
                    stored.char_end = record.char_end
                    stored.content_hash = record.content_hash
                    stored.embedding = blob
            session.commit()

    def delete_document(self, space: VectorSpace, document_id: str) -> None:
        """Delete this backend's records for one document.

        The metadata row is the service layer's (it cascades); the backend
        only clears the index entries it owns.
        """
        with self._session_factory() as session:
            space_row = self._space_row(session, space)
            session.execute(
                delete(VectorRecord).where(
                    VectorRecord.space_id == space_row.id,
                    VectorRecord.document_id == _as_uuid(document_id, field="document_id"),
                )
            )
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
        with self._session_factory() as session:
            space_row = self._space_row(session, space)
            statement = (
                select(VectorRecord, VectorDocument)
                .join(VectorDocument, VectorRecord.document_id == VectorDocument.id)
                .where(
                    VectorRecord.space_id == space_row.id,
                    VectorRecord.view.in_(list(views)),
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
        with self._session_factory() as session:
            space_row = self._space_row(session, space)
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(VectorRecord)
                    .where(VectorRecord.space_id == space_row.id)
                )
                or 0
            )

    def health(self, space: VectorSpace) -> BackendHealth:
        try:
            with self._session_factory() as session:
                space_row = self._space_row(session, space)
                records = int(
                    session.scalar(
                        select(func.count())
                        .select_from(VectorRecord)
                        .where(VectorRecord.space_id == space_row.id)
                    )
                    or 0
                )
                index_table = space_row.index_table
        except VectorBackendError as exc:
            return BackendHealth(ok=False, detail=str(exc))
        if index_table is not None:
            return BackendHealth(
                ok=False,
                detail=(
                    f"space {space.name!r} declares physical index {index_table!r}; "
                    "the linear backend owns no index table"
                ),
            )
        if records > self.capabilities.max_recommended_rows:
            return BackendHealth(
                ok=True,
                detail=(
                    f"over the linear cap: {records} vectors > "
                    f"{self.capabilities.max_recommended_rows} recommended"
                ),
            )
        return BackendHealth(ok=True, detail=f"linear scan, {records} vector(s)")


class PgVectorBackend(VectorBackend):
    """pgvector/HNSW adapter — plan 50 P1b (skeleton, never selected yet)."""

    name = BACKEND_PGVECTOR
    capabilities: BackendCaps = BACKEND_CAPS[BACKEND_PGVECTOR]

    def __init__(self, bind: Engine | sessionmaker[Session]) -> None:
        self._bind = bind

    def _todo(self) -> BackendNotImplemented:
        return BackendNotImplemented("PgVectorBackend ships with plan 50 P1b")

    def ensure_space(self, space: VectorSpace) -> None:
        raise self._todo()

    def upsert(self, space: VectorSpace, records: Sequence[IndexRecord]) -> None:
        raise self._todo()

    def delete_document(self, space: VectorSpace, document_id: str) -> None:
        raise self._todo()

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
        raise self._todo()

    def count(self, space: VectorSpace) -> int:
        raise self._todo()

    def health(self, space: VectorSpace) -> BackendHealth:
        raise self._todo()


class SqliteVecBackend(VectorBackend):
    """sqlite-vec ``vec0`` adapter — plan 50 P1b (skeleton, never selected yet)."""

    name = BACKEND_SQLITE_VEC
    capabilities: BackendCaps = BACKEND_CAPS[BACKEND_SQLITE_VEC]

    def __init__(self, bind: Engine | sessionmaker[Session]) -> None:
        self._bind = bind

    def _todo(self) -> BackendNotImplemented:
        return BackendNotImplemented("SqliteVecBackend ships with plan 50 P1b")

    def ensure_space(self, space: VectorSpace) -> None:
        raise self._todo()

    def upsert(self, space: VectorSpace, records: Sequence[IndexRecord]) -> None:
        raise self._todo()

    def delete_document(self, space: VectorSpace, document_id: str) -> None:
        raise self._todo()

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
        raise self._todo()

    def count(self, space: VectorSpace) -> int:
        raise self._todo()

    def health(self, space: VectorSpace) -> BackendHealth:
        raise self._todo()


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
    """True when ``vec_version()`` answers on a plain connection of this engine."""
    if bind.dialect.name != "sqlite":
        return False
    try:
        with bind.connect() as connection:
            connection.exec_driver_sql("SELECT vec_version()").scalar()
        return True
    except Exception:
        return False


def choose_backend(bind: Engine, *, ann_ready: bool = ANN_READY) -> VectorBackend:
    """Select the backend once per process, honestly degrading to linear.

    ``ann_ready`` is the P1b switch: until the pgvector/sqlite-vec adapters
    are implemented, no deployment selects them and the linear backend
    publishes ``ann=False``. Once enabled, the extension/driver probe decides
    — an unavailable ANN engine still yields the linear fallback.
    """
    dialect = bind.dialect.name
    if ann_ready and dialect == "postgresql" and pgvector_available(bind):
        return PgVectorBackend(bind)
    if ann_ready and dialect == "sqlite" and sqlite_vec_available(bind):
        return SqliteVecBackend(bind)
    return LinearBackend(bind)
