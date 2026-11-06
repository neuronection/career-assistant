"""pgvector and sqlite-vec adapters through the service seam (plan 50 §4,
P1b).

Small deterministic corpus: exact-vs-ANN top-k parity, cross-dialect parity,
scope safety after over-fetch/ANN, delete/count/health, the honest cap and
the sqlite rowid collision guard.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.storage import vector_backends as vb
from app.storage import vector_contract as vc
from app.storage.vector_backends import (
    VectorBackendOverCap,
    VectorRowidCollision,
    sqlite_vec_available,
)
from app.storage.vector_provisioning import provision_space, space_status
from tests.vector_harness import (
    DIM,
    Harness,
    create_native_engine,
    create_space,
    create_sqlite_engine,
    drop_space,
    ensure_pgvector,
)

VECTORS = {
    "a": (1.0, 0.0, 0.0, 0.0),
    "b": (0.9, 0.1, 0.0, 0.0),
    "c": (0.7, 0.3, 0.0, 0.0),
    "d": (0.5, 0.5, 0.0, 0.0),
    "e": (0.2, 0.9, 0.0, 0.0),
    "f": (0.1, 0.9, 0.1, 0.0),
}
QUERY = (1.0, 0.0, 0.0, 0.0)
NAMESPACE = uuid.UUID("4f9e6d1e-2b5a-4b0c-9f2e-6f7c8d9a0b1c")
RECORD_IDS = {name: str(uuid.uuid5(NAMESPACE, f"record-{name}")) for name in VECTORS}


NATIVE_IS_POSTGRESQL = settings.database_url.startswith("postgresql")


@pytest.fixture(params=["native", "sqlite"] if NATIVE_IS_POSTGRESQL else ["sqlite"])
def ann_engine(request, tmp_path) -> Iterator:
    if request.param == "sqlite":
        engine = create_sqlite_engine(tmp_path / "vector-ann.db")
        if not sqlite_vec_available(engine):
            engine.dispose()
            pytest.skip("sqlite-vec is not loadable in this environment")
    else:
        engine = create_native_engine()
        if engine.dialect.name != "postgresql" or not ensure_pgvector(engine):
            engine.dispose()
            pytest.skip("pgvector is not installed in this environment")
    try:
        yield engine
    finally:
        engine.dispose()


def _corpus(engine, *, scopes: tuple[str, ...] = ()) -> Harness:
    harness = create_space(engine)
    for name in VECTORS:
        scope = scopes[list(VECTORS).index(name)] if scopes else "tenant"
        harness.add_document(name, scope_type=scope)
    harness.index_many(
        [harness.record(name, VECTORS[name], record_id=RECORD_IDS[name]) for name in VECTORS]
    )
    return harness


def _expected_top_k(k: int) -> list[str]:
    scored = sorted(
        ((name, vc.cosine(QUERY, VECTORS[name])) for name in VECTORS),
        key=lambda row: -row[1],
    )
    return [RECORD_IDS[name] for name, _ in scored[:k]]


def test_ann_upsert_search_count_delete_and_health(ann_engine):
    harness = _corpus(ann_engine)
    try:
        assert harness.service.count(harness.space) == len(VECTORS)
        hits = harness.search(QUERY, limit=3)
        assert [hit.record_id for hit in hits] == _expected_top_k(3)
        assert all(hit.backend == harness.backend_name for hit in hits)
        assert hits[0].similarity == pytest.approx(1.0)
        assert hits[0].distance == pytest.approx(0.0)
        assert hits[1].similarity > hits[2].similarity

        health = harness.service.health(harness.space)
        assert health.ok is True
        assert "pgvector" in health.detail or "sqlite-vec" in health.detail

        assert harness.service.delete_document(harness.space, harness.documents["a"])
        assert harness.service.count(harness.space) == len(VECTORS) - 1
        assert RECORD_IDS["a"] not in {hit.record_id for hit in harness.search(QUERY, limit=10)}
    finally:
        drop_space(harness)


def test_ann_ensure_space_confirms_the_physical_index(ann_engine):
    harness = _corpus(ann_engine)
    try:
        assert harness.service.ensure_space(harness.space).space_id == harness.space.space_id
        with Session(ann_engine) as session:
            status = space_status(session, harness.space)
        assert status.table_exists is True
        assert status.table_dim == DIM
        assert status.row_count == len(VECTORS)
        assert status.index_present is True
    finally:
        drop_space(harness)


def test_pg_and_sqlite_exact_topk_parity(tmp_path):
    pg_engine = create_native_engine()
    sqlite_engine = create_sqlite_engine(tmp_path / "vector-parity.db")
    try:
        if pg_engine.dialect.name != "postgresql" or not ensure_pgvector(pg_engine):
            pytest.skip("pgvector is not installed in this environment")
        if not sqlite_vec_available(sqlite_engine):
            pytest.skip("sqlite-vec is not loadable in this environment")
        pg_harness = _corpus(pg_engine)
        sqlite_harness = _corpus(sqlite_engine)
        try:
            pg_hits = pg_harness.search(QUERY, limit=4)
            sqlite_hits = sqlite_harness.search(QUERY, limit=4)
            assert [hit.record_id for hit in pg_hits] == [hit.record_id for hit in sqlite_hits]
            assert [hit.record_id for hit in pg_hits] == _expected_top_k(4)
            for pg_hit, sqlite_hit in zip(pg_hits, sqlite_hits, strict=True):
                assert pg_hit.similarity == pytest.approx(sqlite_hit.similarity, abs=1e-6)
        finally:
            drop_space(pg_harness)
            drop_space(sqlite_harness)
    finally:
        pg_engine.dispose()
        sqlite_engine.dispose()


@pytest.mark.parametrize("ann_path", [False, True])
def test_scope_safety_holds_under_ann_and_over_fetch(ann_engine, monkeypatch, ann_path):
    scopes = ("user", "user", "global", "global", "global", "global")
    harness = _corpus(ann_engine, scopes=scopes)
    try:
        if ann_path:
            monkeypatch.setattr(vb, "EXACT_SCAN_THRESHOLD", 1)
            monkeypatch.setattr(vb, "CANDIDATE_MULTIPLIER", 1)
        hits = harness.search(QUERY, scope=vb.filter_scope(scope_types=["user"]), limit=2)
        assert [hit.document_id for hit in hits] == [
            str(harness.documents["a"]),
            str(harness.documents["b"]),
        ]
        assert harness.search(QUERY, scope=vb.filter_scope(scope_types=["global"]), limit=2)
        assert harness.search(QUERY, scope=vb.document_scope([]), limit=2) == [], (
            "an empty scope admits nothing"
        )
        only_c = harness.search(
            QUERY, scope=vb.document_scope([str(harness.documents["c"])]), limit=10
        )
        assert [hit.document_id for hit in only_c] == [str(harness.documents["c"])]
        assert all(
            hit.document_id
            not in {
                str(harness.documents["c"]),
                str(harness.documents["d"]),
                str(harness.documents["e"]),
                str(harness.documents["f"]),
            }
            for hit in hits
        )
    finally:
        drop_space(harness)


def test_scope_safety_under_sqlite_over_fetch_truncation(ann_engine, monkeypatch):
    if ann_engine.dialect.name != "sqlite":
        pytest.skip("over-fetch expansion is the sqlite-vec path")
    scopes = ("user", "user", "global", "global", "global", "global")
    harness = _corpus(ann_engine, scopes=scopes)
    try:
        monkeypatch.setattr(vb, "CANDIDATE_MULTIPLIER", 1)
        hits = harness.search(QUERY, scope=vb.filter_scope(scope_types=["user"]), limit=1)
        assert [hit.document_id for hit in hits] == [str(harness.documents["a"])]
    finally:
        drop_space(harness)


def test_search_raises_over_cap_instead_of_scanning(ann_engine, monkeypatch):
    harness = _corpus(ann_engine)
    try:
        monkeypatch.setattr(
            harness.service.backend,
            "capabilities",
            vc.BackendCaps(
                ann=True,
                max_dim=3072,
                max_recommended_rows=1,
                scope_enforcement=vc.ScopeEnforcement.PRE_JOIN,
            ),
        )
        with pytest.raises(VectorBackendOverCap) as raised:
            harness.search(QUERY, limit=1)
        assert raised.value.degraded == vc.DegradedReason.OVER_CAP
    finally:
        drop_space(harness)


def test_health_is_honest_when_the_index_disappears(ann_engine):
    harness = _corpus(ann_engine)
    table = harness.space.index_table
    try:
        with Session(ann_engine) as session:
            session.execute(text(f"DROP TABLE {table}"))
            session.commit()
        assert harness.service.health(harness.space).ok is False
    finally:
        drop_space(harness)


def test_sqlite_rowid_collision_fails_loudly(ann_engine):
    if ann_engine.dialect.name != "sqlite":
        pytest.skip("rowid map is sqlite-vec only")
    harness = _corpus(ann_engine)
    try:
        new_record_id = str(uuid.uuid4())
        rowid = vb.rowid_for(new_record_id)
        other = str(uuid.uuid4())
        with Session(ann_engine) as session:
            session.execute(
                text(
                    "INSERT INTO vector_entry_ids (record_rowid, record_id) "
                    "VALUES (:rowid, :record_id)"
                ),
                {"rowid": rowid, "record_id": other},
            )
            session.commit()
        record = harness.record("a", (0.1, 0.1, 0.1, 0.1), record_id=new_record_id, view="body")
        with pytest.raises(VectorRowidCollision):
            harness.service.upsert_document(
                harness.space, document_id=harness.documents["a"], records=[record]
            )
    finally:
        drop_space(harness)


def test_ann_provisioning_refuses_a_wrong_dimension_space(ann_engine):
    from app.models.vector_model import VectorSpace as VectorSpaceRow
    from app.storage.vector_provisioning import VectorDimensionMismatch

    harness = _corpus(ann_engine)
    try:
        with Session(ann_engine) as session:
            row = session.get(VectorSpaceRow, uuid.UUID(harness.space.space_id or ""))
            row.dim = DIM + 4
            session.commit()
            with pytest.raises(VectorDimensionMismatch):
                provision_space(session, row)
            session.rollback()
            row = session.get(VectorSpaceRow, uuid.UUID(harness.space.space_id or ""))
            row.dim = DIM
            session.commit()
    finally:
        drop_space(harness)


def test_ann_orphan_sweep_clears_the_physical_index(ann_engine):
    harness = _corpus(ann_engine)
    try:
        assert harness.service.orphan_sweep(harness.space, lambda kind, source: False) == len(
            VECTORS
        )
        assert harness.service.count(harness.space) == 0
        assert harness.search(QUERY, limit=5) == []
        assert harness.service.health(harness.space).ok is True
    finally:
        drop_space(harness)


def test_ann_recall_gate_against_the_exact_order(ann_engine, monkeypatch):
    import hashlib

    harness = create_space(ann_engine, dim=8)
    vectors: dict[str, tuple[float, ...]] = {}
    records = []
    try:
        for index in range(64):
            name = f"recall-{index}"
            harness.add_document(name)
            record_id = str(uuid.uuid5(NAMESPACE, f"recall-{index}"))
            vector = tuple(
                int.from_bytes(hashlib.sha256(f"seed-{index}-{axis}".encode()).digest()[:4], "big")
                / 2**31
                - 1.0
                for axis in range(8)
            )
            vectors[record_id] = vector
            records.append(harness.record(name, vector, record_id=record_id))
        harness.index_many(records)
        query = vectors[str(uuid.uuid5(NAMESPACE, "recall-0"))]
        exact = sorted(vectors, key=lambda rid: -vc.cosine(query, vectors[rid]))[:10]
        monkeypatch.setattr(vb, "EXACT_SCAN_THRESHOLD", 1)
        hits = harness.search(query, limit=10, ef_search=100)
        recall = len({hit.record_id for hit in hits} & set(exact)) / 10
        assert recall >= 0.95, f"ANN recall@10 was {recall:.2f}"
    finally:
        drop_space(harness)


def test_sqlite_scoped_exact_scan_matches_the_exact_order(ann_engine, monkeypatch):
    if ann_engine.dialect.name != "sqlite":
        pytest.skip("exact-vs-overfetch is the sqlite-vec path")
    harness = _corpus(ann_engine)
    try:
        monkeypatch.setattr(vb, "CANDIDATE_MULTIPLIER", 1)
        allowed = str(harness.documents["f"])
        hits = harness.search(QUERY, scope=vb.document_scope([allowed]), limit=1)
        assert [hit.document_id for hit in hits] == [allowed], (
            "a scoped query below the exact threshold is exact, not a truncation"
        )

        monkeypatch.setattr(vb, "EXACT_SCAN_THRESHOLD", 0)
        bounded = harness.search(QUERY, scope=vb.document_scope([allowed]), limit=1)
        assert [hit.document_id for hit in bounded] == [allowed], (
            "above the threshold the bounded over-fetch expansion still converges on "
            "the exact set (it costs more queries, it does not lose the scope)"
        )
    finally:
        drop_space(harness)
