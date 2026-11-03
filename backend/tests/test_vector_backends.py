"""Linear vector backend + factory wall (plan 50 P1a).

Covers the exact-scan fallback: upsert/search/delete/count, deterministic
tie-breaks, dimension safety, in-scan scope isolation (including an empty
scope), content-hash updates and the honest capability/factory selection.
The ANN adapters are P1b skeletons and are asserted to stay unselected.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.vector_model import VectorDocument, VectorRecord
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.storage import vector_contract as vc
from app.storage.vector_backends import (
    BackendNotImplemented,
    LinearBackend,
    PgVectorBackend,
    SqliteVecBackend,
    VectorBackendOverCap,
    VectorDocumentNotFound,
    VectorRecordIdentityMismatch,
    VectorSpaceMismatch,
    choose_backend,
    document_scope,
    filter_scope,
    index_table_name,
    pgvector_available,
    sqlite_vec_available,
)

DIM = 4


def _sync_url(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


def _sqlite_foreign_keys(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
def sync_engine():
    engine = create_engine(_sync_url(settings.database_url), pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_foreign_keys)
    try:
        yield engine
    finally:
        engine.dispose()


@dataclass(frozen=True)
class SeededSpace:
    row_id: uuid.UUID
    dto: vc.VectorSpace
    documents: dict[str, uuid.UUID]


@pytest.fixture
def space_factory(sync_engine):
    created: list[uuid.UUID] = []

    def make(
        *,
        documents: tuple[tuple[str, str], ...] = (("doc-a", "tenant"), ("doc-b", "tenant")),
        index_table: str | None = None,
        scope_type: str | None = None,
    ) -> SeededSpace:
        suffix = uuid.uuid4().hex[:10]
        with Session(sync_engine) as session:
            row = VectorSpaceRow(
                name=f"content-{suffix}",
                provider="openai",
                model="text-embedding-3-small",
                dim=DIM,
                index_table=index_table,
            )
            session.add(row)
            session.flush()
            docs: dict[str, uuid.UUID] = {}
            for name, doc_scope in documents:
                document = VectorDocument(
                    space_id=row.id,
                    kind="posting",
                    source_id=f"{name}-{suffix}",
                    scope_type=scope_type or doc_scope,
                    source_hash="0" * 64,
                    schema_version=1,
                )
                session.add(document)
                session.flush()
                docs[name] = document.id
            session.commit()
            created.append(row.id)
            dto = vc.VectorSpace(
                name=row.name,
                provider=row.provider,
                model=row.model,
                dim=row.dim,
                space_id=str(row.id),
            )
        return SeededSpace(row_id=row.id, dto=dto, documents=docs)

    try:
        yield make
    finally:
        with Session(sync_engine) as session:
            for row_id in created:
                session.execute(delete(VectorSpaceRow).where(VectorSpaceRow.id == row_id))
            session.commit()


def _record(
    seeded: SeededSpace,
    document: str,
    embedding: tuple[float, ...],
    *,
    view: str = "summary",
    chunk_index: int = 0,
    content_hash: str = "hash",
    record_id: str | None = None,
) -> vc.IndexRecord:
    return vc.IndexRecord(
        record_id=record_id or str(uuid.uuid4()),
        document_id=str(seeded.documents[document]),
        view=view,
        chunk_index=chunk_index,
        embedding=embedding,
        content_hash=content_hash,
    )


def test_upsert_and_search_roundtrip(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    record_a = _record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0))
    record_b = _record(seeded, "doc-b", (0.0, 1.0, 0.0, 0.0))
    backend.upsert(seeded.dto, [record_a, record_b])

    hits = backend.search(
        seeded.dto,
        [1.0, 0.0, 0.0, 0.0],
        views=("summary",),
        scope=vc.ScopeSpec(kind="all", predicate=None),
        limit=10,
    )
    assert [hit.document_id for hit in hits] == [
        str(seeded.documents["doc-a"]),
        str(seeded.documents["doc-b"]),
    ]
    assert hits[0].record_id == record_a.record_id, "the contract record id is the store id"
    assert hits[0].similarity == pytest.approx(1.0)
    assert hits[0].distance == pytest.approx(0.0)
    assert hits[0].backend == vc.BACKEND_LINEAR
    assert backend.count(seeded.dto) == 2


def test_search_ties_break_on_document_id_then_record_id(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    backend.upsert(
        seeded.dto,
        [
            _record(seeded, "doc-b", (1.0, 0.0, 0.0, 0.0)),
            _record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0)),
        ],
    )

    hits = backend.search(
        seeded.dto,
        [1.0, 0.0, 0.0, 0.0],
        views=("summary",),
        scope=vc.ScopeSpec(kind="all", predicate=None),
        limit=10,
    )
    assert [hit.document_id for hit in hits] == sorted(
        str(value) for value in seeded.documents.values()
    )


def test_write_with_wrong_dimension_is_refused(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    with pytest.raises(VectorSpaceMismatch):
        backend.upsert(seeded.dto, [_record(seeded, "doc-a", (1.0, 0.0, 0.0))])
    assert backend.count(seeded.dto) == 0


def test_query_with_wrong_dimension_is_ignored(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    backend.upsert(seeded.dto, [_record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0))])
    assert (
        backend.search(
            seeded.dto,
            [1.0, 0.0, 0.0],
            views=("summary",),
            scope=vc.ScopeSpec(kind="all", predicate=None),
            limit=10,
        )
        == []
    )


def test_scope_safety_never_returns_an_excluded_document(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    backend.upsert(
        seeded.dto,
        [
            _record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0)),
            _record(seeded, "doc-b", (1.0, 0.01, 0.0, 0.0)),
        ],
    )

    only_b = backend.search(
        seeded.dto,
        [1.0, 0.0, 0.0, 0.0],
        views=("summary",),
        scope=document_scope([str(seeded.documents["doc-b"])]),
        limit=10,
    )
    assert [hit.document_id for hit in only_b] == [str(seeded.documents["doc-b"])]

    assert (
        backend.search(
            seeded.dto,
            [1.0, 0.0, 0.0, 0.0],
            views=("summary",),
            scope=document_scope([]),
            limit=10,
        )
        == []
    ), "an empty document scope admits nothing"


def test_filter_scope_is_enforced_in_scan(sync_engine, space_factory):
    seeded = space_factory(documents=(("doc-a", "user"), ("doc-b", "global")))
    backend = LinearBackend(sync_engine)
    backend.upsert(
        seeded.dto,
        [
            _record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0)),
            _record(seeded, "doc-b", (1.0, 0.0, 0.0, 0.0)),
        ],
    )
    hits = backend.search(
        seeded.dto,
        [1.0, 0.0, 0.0, 0.0],
        views=("summary",),
        scope=filter_scope(scope_types=["user"]),
        limit=10,
    )
    assert [hit.document_id for hit in hits] == [str(seeded.documents["doc-a"])]

    assert (
        backend.search(
            seeded.dto,
            [1.0, 0.0, 0.0, 0.0],
            views=("summary",),
            scope=filter_scope(profile_ids=[]),
            limit=10,
        )
        == []
    )


def test_unknown_scope_kind_is_refused(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    with pytest.raises(ValueError):
        backend.search(
            seeded.dto,
            [1.0, 0.0, 0.0, 0.0],
            views=("summary",),
            scope=vc.ScopeSpec(kind="raw-sql", predicate="1=1"),
            limit=10,
        )


def test_upsert_updates_content_hash_in_place(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    record = _record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0), content_hash="old")
    backend.upsert(seeded.dto, [record])

    replacement = _record(
        seeded,
        "doc-a",
        (0.0, 1.0, 0.0, 0.0),
        content_hash="new",
        record_id=record.record_id,
    )
    backend.upsert(seeded.dto, [replacement])

    assert backend.count(seeded.dto) == 1, "same (document, view, chunk) updates in place"
    hits = backend.search(
        seeded.dto,
        [0.0, 1.0, 0.0, 0.0],
        views=("summary",),
        scope=vc.ScopeSpec(kind="all", predicate=None),
        limit=10,
    )
    assert hits[0].similarity == pytest.approx(1.0)
    with Session(sync_engine) as session:
        stored = session.scalars(
            select(VectorRecord).where(VectorRecord.document_id == seeded.documents["doc-a"])
        ).one()
        assert stored.content_hash == "new"


def test_upsert_requires_a_registered_document(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    orphan = vc.IndexRecord(
        record_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        view="summary",
        chunk_index=0,
        embedding=(1.0, 0.0, 0.0, 0.0),
    )
    with pytest.raises(VectorDocumentNotFound):
        backend.upsert(seeded.dto, [orphan])


def test_delete_document_clears_its_records(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    backend.upsert(
        seeded.dto,
        [
            _record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0)),
            _record(seeded, "doc-b", (0.0, 1.0, 0.0, 0.0)),
        ],
    )

    backend.delete_document(seeded.dto, str(seeded.documents["doc-a"]))
    assert backend.count(seeded.dto) == 1
    hits = backend.search(
        seeded.dto,
        [1.0, 0.0, 0.0, 0.0],
        views=("summary",),
        scope=vc.ScopeSpec(kind="all", predicate=None),
        limit=10,
    )
    assert [hit.document_id for hit in hits] == [str(seeded.documents["doc-b"])]


def test_health_reports_the_linear_store_and_cap(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    backend.upsert(seeded.dto, [_record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0))])
    health = backend.health(seeded.dto)
    assert health.ok is True
    assert "linear scan" in health.detail

    ann_seeded = space_factory(index_table="vec_deadbeef")
    assert backend.health(ann_seeded.dto).ok is False, "linear owns no physical table"


def test_factory_selects_linear_and_publishes_honest_caps(sync_engine):
    backend = choose_backend(sync_engine)
    assert isinstance(backend, LinearBackend)
    assert backend.capabilities == vc.BACKEND_CAPS[vc.BACKEND_LINEAR]
    assert backend.capabilities.ann is False
    assert backend.capabilities.scope_enforcement == vc.ScopeEnforcement.IN_SCAN


def test_factory_ann_branch_follows_the_environment_probe(sync_engine):
    dialect = sync_engine.dialect.name
    backend = choose_backend(sync_engine, ann_ready=True)
    if dialect == "postgresql" and pgvector_available(sync_engine):
        assert isinstance(backend, PgVectorBackend)
        assert backend.capabilities == vc.BACKEND_CAPS[vc.BACKEND_PGVECTOR]
    elif dialect == "sqlite" and sqlite_vec_available(sync_engine):
        assert isinstance(backend, SqliteVecBackend)
        assert backend.capabilities == vc.BACKEND_CAPS[vc.BACKEND_SQLITE_VEC]
    else:
        assert isinstance(backend, LinearBackend), "an unavailable ANN engine degrades to linear"


def test_ann_skeletons_refuse_instead_of_faking_results(sync_engine, space_factory):
    seeded = space_factory()
    for backend in (PgVectorBackend(sync_engine), SqliteVecBackend(sync_engine)):
        with pytest.raises(BackendNotImplemented):
            backend.health(seeded.dto)


def test_count_and_delete_cascade_through_the_space(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    backend.upsert(
        seeded.dto,
        [
            _record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0), view="summary"),
            _record(seeded, "doc-a", (0.5, 0.5, 0.0, 0.0), view="body"),
        ],
    )
    assert backend.count(seeded.dto) == 2
    with Session(sync_engine) as session:
        session.execute(delete(VectorSpaceRow).where(VectorSpaceRow.id == seeded.row_id))
        session.commit()
        remaining = session.scalar(
            select(VectorRecord).where(VectorRecord.space_id == seeded.row_id).limit(1)
        )
        assert remaining is None, "space deletion cascades documents and records"


def test_index_table_name_is_derived_from_the_space_uuid():
    space_id = uuid.UUID("12345678-1234-4234-8234-123456789abc")
    assert index_table_name(space_id) == "vec_12345678"
    assert index_table_name(str(space_id)) == "vec_12345678"


def test_search_refuses_to_scan_beyond_the_linear_cap(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    backend.upsert(
        seeded.dto,
        [
            _record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0)),
            _record(seeded, "doc-b", (0.0, 1.0, 0.0, 0.0)),
        ],
    )
    backend.capabilities = vc.BackendCaps(
        ann=False,
        max_dim=3072,
        max_recommended_rows=1,
        scope_enforcement=vc.ScopeEnforcement.IN_SCAN,
    )
    with pytest.raises(VectorBackendOverCap) as raised:
        backend.search(
            seeded.dto,
            [1.0, 0.0, 0.0, 0.0],
            views=("summary",),
            scope=vc.ScopeSpec(kind="all", predicate=None),
            limit=10,
        )
    assert raised.value.degraded == vc.DegradedReason.OVER_CAP


def test_persisted_space_wins_over_a_stale_dto(sync_engine, space_factory):
    """The row is the only trusted model/dim source (plan 50 §3.1)."""
    seeded = space_factory()
    stale = vc.VectorSpace(
        name=seeded.dto.name,
        provider=seeded.dto.provider,
        model=seeded.dto.model,
        dim=seeded.dto.dim * 2,
        space_id=str(seeded.row_id),
    )
    backend = LinearBackend(sync_engine)
    with pytest.raises(VectorSpaceMismatch):
        backend.count(stale)


def test_record_identity_cannot_change_for_the_same_key(sync_engine, space_factory):
    seeded = space_factory()
    backend = LinearBackend(sync_engine)
    original = _record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0))
    backend.upsert(seeded.dto, [original])

    moved = _record(seeded, "doc-a", (1.0, 0.0, 0.0, 0.0))
    with pytest.raises(VectorRecordIdentityMismatch):
        backend.upsert(seeded.dto, [moved])
    assert backend.count(seeded.dto) == 1


def test_document_scope_rejects_a_bare_string():
    with pytest.raises(ValueError):
        document_scope("not-a-collection-of-ids")
