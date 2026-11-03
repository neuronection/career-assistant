"""Linear backend + service seam wall (plan 50 P1a/P1b).

The exact-scan fallback and the metadata-owning service: registration,
upsert/search/delete/count, deterministic tie-breaks, dimension and
content-hash guards, in-scan scope isolation (including an empty scope), the
writer guard at the service boundary, orphan/erasure hooks and the honest
factory/capability selection.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import replace

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.vector_model import VectorRecord
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.storage import vector_contract as vc
from app.storage.vector_backends import (
    LinearBackend,
    PgVectorBackend,
    ResolvedEmbedding,
    SqliteVecBackend,
    VectorBackendOverCap,
    VectorDocumentNotFound,
    VectorRecordIdentityMismatch,
    VectorSpaceMismatch,
    choose_backend,
    document_scope,
    filter_scope,
    pgvector_available,
    sqlite_vec_available,
)
from app.storage.vector_schema import index_table_name
from tests.vector_harness import (
    Harness,
    create_native_engine,
    create_space,
    drop_space,
)


@pytest.fixture
def engine() -> Iterator:
    native = create_native_engine()
    try:
        yield native
    finally:
        native.dispose()


@pytest.fixture
def linear(engine) -> Iterator[Harness]:
    harness = create_space(engine, backend_name=vc.BACKEND_LINEAR)
    harness.add_document("doc-a")
    harness.add_document("doc-b")
    try:
        yield harness
    finally:
        drop_space(harness)


def test_upsert_and_search_roundtrip(linear: Harness, engine):
    record_a = linear.index("doc-a", (1.0, 0.0, 0.0, 0.0))
    linear.index("doc-b", (0.0, 1.0, 0.0, 0.0))

    hits = linear.search((1.0, 0.0, 0.0, 0.0))
    assert [hit.document_id for hit in hits] == [
        str(linear.documents["doc-a"]),
        str(linear.documents["doc-b"]),
    ]
    assert hits[0].record_id == record_a.record_id, "the contract record id is the store id"
    assert hits[0].similarity == pytest.approx(1.0)
    assert hits[0].distance == pytest.approx(0.0)
    assert hits[0].backend == vc.BACKEND_LINEAR
    assert linear.service.count(linear.space) == 2


def test_search_ties_break_on_document_id_then_record_id(linear: Harness):
    linear.index("doc-b", (1.0, 0.0, 0.0, 0.0))
    linear.index("doc-a", (1.0, 0.0, 0.0, 0.0))

    hits = linear.search((1.0, 0.0, 0.0, 0.0))
    assert [hit.document_id for hit in hits] == sorted(
        str(value) for value in linear.documents.values()
    )


def test_write_with_wrong_dimension_is_refused(linear: Harness):
    record = linear.record("doc-a", (1.0, 0.0, 0.0))
    with pytest.raises(VectorSpaceMismatch):
        linear.service.upsert_document(
            linear.space, document_id=linear.documents["doc-a"], records=[record]
        )
    assert linear.service.count(linear.space) == 0


def test_query_with_wrong_dimension_is_ignored(linear: Harness):
    linear.index("doc-a", (1.0, 0.0, 0.0, 0.0))
    assert linear.search((1.0, 0.0, 0.0)) == []


def test_scope_safety_never_returns_an_excluded_document(linear: Harness):
    linear.index("doc-a", (1.0, 0.0, 0.0, 0.0))
    linear.index("doc-b", (1.0, 0.01, 0.0, 0.0))

    only_b = linear.search(
        (1.0, 0.0, 0.0, 0.0),
        scope=document_scope([str(linear.documents["doc-b"])]),
    )
    assert [hit.document_id for hit in only_b] == [str(linear.documents["doc-b"])]

    assert linear.search((1.0, 0.0, 0.0, 0.0), scope=document_scope([])) == [], (
        "an empty document scope admits nothing"
    )


def test_filter_scope_is_enforced_in_scan(engine):
    harness = create_space(engine, backend_name=vc.BACKEND_LINEAR)
    harness.add_document("doc-a", scope_type="user")
    harness.add_document("doc-b", scope_type="global")
    try:
        harness.index("doc-a", (1.0, 0.0, 0.0, 0.0))
        harness.index("doc-b", (1.0, 0.0, 0.0, 0.0))
        hits = harness.search((1.0, 0.0, 0.0, 0.0), scope=filter_scope(scope_types=["user"]))
        assert [hit.document_id for hit in hits] == [str(harness.documents["doc-a"])]

        assert harness.search((1.0, 0.0, 0.0, 0.0), scope=filter_scope(profile_ids=[])) == []
    finally:
        drop_space(harness)


def test_unknown_scope_kind_is_refused(linear: Harness):
    with pytest.raises(ValueError):
        linear.search(
            (1.0, 0.0, 0.0, 0.0),
            scope=vc.ScopeSpec(kind="raw-sql", predicate="1=1"),
        )


def test_upsert_updates_content_hash_in_place(linear: Harness, engine):
    record = linear.index("doc-a", (1.0, 0.0, 0.0, 0.0), content_hash="old")

    replacement = linear.record(
        "doc-a",
        (0.0, 1.0, 0.0, 0.0),
        content_hash="new",
        record_id=record.record_id,
    )
    linear.service.upsert_document(
        linear.space, document_id=linear.documents["doc-a"], records=[replacement]
    )

    assert linear.service.count(linear.space) == 1, "same (document, view, chunk) updates in place"
    hits = linear.search((0.0, 1.0, 0.0, 0.0))
    assert hits[0].similarity == pytest.approx(1.0)
    with Session(engine) as session:
        stored = session.scalars(
            select(VectorRecord).where(VectorRecord.document_id == linear.documents["doc-a"])
        ).one()
        assert stored.content_hash == "new"


def test_content_hash_dedupe_skips_unchanged_records(linear: Harness):
    record = linear.index("doc-a", (1.0, 0.0, 0.0, 0.0), content_hash="same")
    unchanged = linear.record(
        "doc-a", (1.0, 0.0, 0.0, 0.0), content_hash="same", record_id=record.record_id
    )
    changed = linear.record("doc-a", (0.0, 1.0, 0.0, 0.0), content_hash="different", view="body")
    assert linear.service.records_to_embed(
        linear.space, document_id=linear.documents["doc-a"], records=[unchanged, changed]
    ) == [changed]
    assert linear.service.existing_content_hashes(
        linear.space, document_id=linear.documents["doc-a"]
    ) == {("summary", 0): "same"}


def test_reupsert_removes_stale_views_and_chunks(linear: Harness):
    summary = linear.record("doc-a", (1.0, 0.0, 0.0, 0.0), view="summary")
    body = linear.record("doc-a", (0.0, 1.0, 0.0, 0.0), view="body", chunk_index=1)
    linear.index_many([summary, body])
    assert linear.service.count(linear.space) == 2

    linear.service.upsert_document(
        linear.space, document_id=linear.documents["doc-a"], records=[summary]
    )
    assert linear.service.count(linear.space) == 1, "the document is a rebuild unit"
    assert [hit.record_id for hit in linear.search((1.0, 0.0, 0.0, 0.0))] == [summary.record_id]
    with Session(linear.engine) as session:
        assert session.scalars(
            select(VectorRecord).where(VectorRecord.document_id == linear.documents["doc-a"])
        ).all() == [session.get(VectorRecord, uuid.UUID(summary.record_id))]


def test_upsert_requires_a_registered_document(linear: Harness):
    orphan = vc.IndexRecord(
        record_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        view="summary",
        chunk_index=0,
        embedding=(1.0, 0.0, 0.0, 0.0),
    )
    with pytest.raises(VectorDocumentNotFound):
        linear.service.upsert_document(
            linear.space, document_id=orphan.document_id, records=[orphan]
        )


def test_delete_document_clears_its_records(linear: Harness):
    linear.index("doc-a", (1.0, 0.0, 0.0, 0.0))
    linear.index("doc-b", (0.0, 1.0, 0.0, 0.0))

    assert linear.service.delete_document(linear.space, linear.documents["doc-a"]) is True
    assert linear.service.count(linear.space) == 1
    hits = linear.search((1.0, 0.0, 0.0, 0.0))
    assert [hit.document_id for hit in hits] == [str(linear.documents["doc-b"])]
    assert linear.service.delete_document(linear.space, linear.documents["doc-a"]) is False


def test_health_reports_the_linear_store_and_cap(linear: Harness, engine):
    linear.index("doc-a", (1.0, 0.0, 0.0, 0.0))
    health = linear.service.health(linear.space)
    assert health.ok is True
    assert "linear scan" in health.detail

    ann_space = create_space(engine, backend_name=vc.BACKEND_LINEAR)
    try:
        stale = replace(ann_space.space, index_table="vec_deadbeef")
        assert LinearBackend(engine).health(stale).ok is False, "linear owns no physical table"
    finally:
        drop_space(ann_space)


def test_factory_selects_linear_and_publishes_honest_caps(engine):
    backend = choose_backend(engine)
    if engine.dialect.name == "postgresql" and pgvector_available(engine):
        assert isinstance(backend, PgVectorBackend)
    elif engine.dialect.name == "sqlite" and sqlite_vec_available(engine):
        assert isinstance(backend, SqliteVecBackend)
    else:
        assert isinstance(backend, LinearBackend)
        assert backend.capabilities == vc.BACKEND_CAPS[vc.BACKEND_LINEAR]
        assert backend.capabilities.ann is False
        assert backend.capabilities.scope_enforcement == vc.ScopeEnforcement.IN_SCAN


def test_linear_backend_caps_are_published(engine):
    backend = LinearBackend(engine)
    assert backend.capabilities == vc.BACKEND_CAPS[vc.BACKEND_LINEAR]
    assert backend.capabilities.ann is False
    assert backend.capabilities.scope_enforcement == vc.ScopeEnforcement.IN_SCAN


def test_count_and_delete_cascade_through_the_space(linear: Harness, engine):
    linear.index_many(
        [
            linear.record("doc-a", (1.0, 0.0, 0.0, 0.0), view="summary"),
            linear.record("doc-a", (0.5, 0.5, 0.0, 0.0), view="body"),
        ]
    )
    assert linear.service.count(linear.space) == 2
    with Session(engine) as session:
        session.execute(
            delete(VectorSpaceRow).where(VectorSpaceRow.id == uuid.UUID(linear.space.space_id))
        )
        session.commit()
        remaining = session.scalar(
            select(VectorRecord)
            .where(VectorRecord.space_id == uuid.UUID(linear.space.space_id))
            .limit(1)
        )
        assert remaining is None, "space deletion cascades documents and records"


def test_index_table_name_is_derived_from_the_space_uuid():
    space_id = uuid.UUID("12345678-1234-4234-8234-123456789abc")
    assert index_table_name(space_id) == "vec_12345678"
    assert index_table_name(str(space_id)) == "vec_12345678"


def test_search_refuses_to_scan_beyond_the_linear_cap(linear: Harness):
    linear.index("doc-a", (1.0, 0.0, 0.0, 0.0))
    linear.index("doc-b", (0.0, 1.0, 0.0, 0.0))
    linear.service.backend.capabilities = vc.BackendCaps(
        ann=False,
        max_dim=3072,
        max_recommended_rows=1,
        scope_enforcement=vc.ScopeEnforcement.IN_SCAN,
    )
    with pytest.raises(VectorBackendOverCap) as raised:
        linear.search((1.0, 0.0, 0.0, 0.0))
    assert raised.value.degraded == vc.DegradedReason.OVER_CAP


def test_persisted_space_wins_over_a_stale_dto(linear: Harness):
    """The row is the only trusted model/dim source (plan 50 §3.1)."""
    stale = vc.VectorSpace(
        name=linear.space.name,
        provider=linear.space.provider,
        model=linear.space.model,
        dim=linear.space.dim * 2,
        space_id=linear.space.space_id,
    )
    with pytest.raises(VectorSpaceMismatch):
        linear.service.resolve_space(stale)
    with pytest.raises(VectorSpaceMismatch):
        linear.service.count(stale)


def test_writer_guard_runs_at_the_service_seam(linear: Harness):
    record = linear.record("doc-a", (1.0, 0.0, 0.0, 0.0))
    mismatch = ResolvedEmbedding(
        provider=linear.space.provider,
        model="text-embedding-3-large",
        dim=linear.space.dim,
    )
    with pytest.raises(VectorSpaceMismatch) as raised:
        linear.service.upsert_document(
            linear.space,
            document_id=linear.documents["doc-a"],
            records=[record],
            resolved=mismatch,
        )
    assert raised.value.degraded == vc.DegradedReason.SPACE_MISMATCH
    assert linear.service.count(linear.space) == 0


def test_record_identity_cannot_change_for_the_same_key(linear: Harness):
    original = linear.index("doc-a", (1.0, 0.0, 0.0, 0.0))
    moved = linear.record("doc-a", (1.0, 0.0, 0.0, 0.0))
    with pytest.raises(VectorRecordIdentityMismatch):
        linear.service.upsert_document(
            linear.space, document_id=linear.documents["doc-a"], records=[moved]
        )
    assert linear.service.count(linear.space) == 1
    assert original.record_id != moved.record_id


def test_orphan_sweep_and_scope_erasure(linear: Harness):
    linear.index("doc-a", (1.0, 0.0, 0.0, 0.0))
    linear.index("doc-b", (0.0, 1.0, 0.0, 0.0))

    assert linear.service.orphan_sweep(linear.space, lambda kind, source: True) == 0
    assert linear.service.count(linear.space) == 2

    assert (
        linear.service.orphan_sweep(linear.space, lambda kind, source: source.startswith("doc-a-"))
        == 1
    )
    assert linear.service.count(linear.space) == 1

    assert linear.service.delete_scope(linear.space, scope_type="tenant", scope_id=None) == 1
    assert linear.service.count(linear.space) == 0


def test_document_scope_rejects_a_bare_string():
    with pytest.raises(ValueError):
        document_scope("not-a-collection-of-ids")


def test_linear_provisioning_has_no_physical_table(linear: Harness):
    assert linear.space.index_table is None


def test_rowid_is_stable_positive_and_salted():
    from app.storage.vector_backends import rowid_for

    record_id = str(uuid.uuid4())
    first = rowid_for(record_id)
    assert first == rowid_for(record_id)
    assert 0 < first <= 0x7FFF_FFFF_FFFF_FFFF
    assert rowid_for(record_id, salt=1) != first


def test_factory_is_selected_once_per_process(engine):
    from app.storage.vector_backends import get_backend, reset_backend_cache

    reset_backend_cache()
    try:
        first = get_backend(engine)
        assert get_backend(engine) is first, "no per-request factory probes"
    finally:
        reset_backend_cache()


def test_active_space_resolves_the_read_path_pointer(linear: Harness):
    resolved = linear.service.active_space(linear.space.name)
    assert resolved.space_id == linear.space.space_id
    assert resolved.status == vc.SpaceStatus.ACTIVE


def test_text_ref_round_trips_and_stays_null_when_absent(linear: Harness, engine):
    from app.storage.vector_store import TextRef

    summary = linear.record("doc-a", (1.0, 0.0, 0.0, 0.0), view="summary")
    body = linear.record("doc-a", (0.0, 1.0, 0.0, 0.0), view="body")
    linear.service.upsert_document(
        linear.space,
        document_id=linear.documents["doc-a"],
        records=[summary, body],
        text_refs={
            ("summary", 0): TextRef(
                {"table": "job_postings", "id": str(linear.documents["doc-a"]), "field": "title"},
                1,
            )
        },
    )
    with Session(engine) as session:
        stored = {
            record.view: record
            for record in session.scalars(
                select(VectorRecord).where(VectorRecord.document_id == linear.documents["doc-a"])
            )
        }
    assert stored["summary"].text_ref == {
        "table": "job_postings",
        "id": str(linear.documents["doc-a"]),
        "field": "title",
    }
    assert stored["summary"].text_ref_schema_version == 1
    assert stored["body"].text_ref is None
    assert stored["body"].text_ref_schema_version is None

    changed = linear.record(
        "doc-a",
        (1.0, 0.0, 0.0, 0.0),
        view="summary",
        content_hash="changed",
        record_id=summary.record_id,
    )
    linear.service.upsert_document(
        linear.space, document_id=linear.documents["doc-a"], records=[changed], prune=False
    )
    with Session(engine) as session:
        assert session.get(VectorRecord, uuid.UUID(changed.record_id)).text_ref == {
            "table": "job_postings",
            "id": str(linear.documents["doc-a"]),
            "field": "title",
        }, "an upsert without text_refs leaves the pointer untouched"


def test_partial_upsert_keeps_unchanged_records_then_prunes_the_stale_key(linear: Harness):
    summary = linear.record("doc-a", (1.0, 0.0, 0.0, 0.0), view="summary")
    body = linear.record("doc-a", (0.0, 1.0, 0.0, 0.0), view="body", chunk_index=1)
    linear.index_many([summary, body])
    assert linear.service.count(linear.space) == 2

    updated = linear.record(
        "doc-a",
        (1.0, 0.0, 0.0, 0.0),
        view="summary",
        content_hash="new",
        record_id=summary.record_id,
    )
    partial = linear.service.upsert_document(
        linear.space,
        document_id=linear.documents["doc-a"],
        records=[updated],
        prune=False,
    )
    assert (partial.records, partial.written, partial.removed) == (1, 1, 0)
    assert linear.service.count(linear.space) == 2, "the unchanged body record survives"

    removed = linear.service.prune_records(
        linear.space,
        document_id=linear.documents["doc-a"],
        keep_keys=[("summary", 0)],
    )
    assert removed == 1
    assert linear.service.count(linear.space) == 1
    with Session(linear.engine) as session:
        assert {
            (record.view, record.chunk_index)
            for record in session.scalars(
                select(VectorRecord).where(VectorRecord.document_id == linear.documents["doc-a"])
            )
        } == {("summary", 0)}


def test_authoritative_upsert_reports_what_it_removed(linear: Harness):
    summary = linear.record("doc-a", (1.0, 0.0, 0.0, 0.0), view="summary")
    body = linear.record("doc-a", (0.0, 1.0, 0.0, 0.0), view="body")
    linear.index_many([summary, body])
    indexed = linear.service.upsert_document(
        linear.space, document_id=linear.documents["doc-a"], records=[summary]
    )
    assert indexed.removed == 1
    assert linear.service.count(linear.space) == 1
