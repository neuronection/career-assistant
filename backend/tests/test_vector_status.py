"""Retrieval status/health reads and the admin trigger (plan 50 §11, P1c).

The metadata reads are dialect-agnostic: counts, kinds, the latest coverage
snapshot (``never_reconciled`` is a state, not a zero), the last reindex job
and the physical index probe. Health reports the selected backend, the
extension version, capability caps and per-space detail on PostgreSQL,
sqlite-vec and the linear fallback.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine, event, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.background_job_model import BackgroundJob
from app.models.vector_model import (
    RetrievalCoverageSnapshot,
    VectorDocument,
    VectorRecord,
)
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services.vector_status import read_health, read_space_statuses
from app.storage import vector_contract as vc
from app.storage.vector_backends import sqlite_vec_available
from app.storage.vector_store import VectorStoreService
from tests.vector_harness import (
    DIM,
    Harness,
    backend_for,
    create_native_engine,
    create_space,
    drop_space,
    ensure_pgvector,
)

NATIVE_IS_POSTGRESQL = settings.database_url.startswith("postgresql")


def _foreign_keys_on(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _status_engine(tmp_path):
    """Vector metadata + jobs + coverage, without the whole app schema."""
    engine = create_engine(f"sqlite:///{tmp_path / 'vector-status.db'}", pool_pre_ping=True)
    event.listen(engine, "connect", _foreign_keys_on)
    metadata = MetaData()
    Table("profiles", metadata, Column("id", Uuid, primary_key=True))
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    for model in (
        VectorSpaceRow,
        VectorDocument,
        VectorRecord,
        RetrievalCoverageSnapshot,
        BackgroundJob,
    ):
        model.__table__.to_metadata(metadata)
    metadata.create_all(engine)
    return engine


@pytest.fixture
def status_engine(tmp_path) -> Iterator:
    engine = _status_engine(tmp_path)
    try:
        yield engine
    finally:
        engine.dispose()


def _snapshot(harness: Harness, **overrides) -> RetrievalCoverageSnapshot:
    values = {
        "space_id": uuid.UUID(harness.space.space_id or ""),
        "kind": "posting",
        "as_of": datetime.now(UTC),
        "total": 10,
        "embedded": 9,
        "missing": 1,
        "stale": 0,
        "failed": 0,
    }
    values.update(overrides)
    return RetrievalCoverageSnapshot(**values)


def _linear_harness(engine) -> Harness:
    harness = create_space(engine, backend_name=vc.BACKEND_LINEAR)
    harness.add_document("doc-a", kind="posting")
    harness.add_document("doc-b", kind="posting")
    harness.index("doc-a", (1.0, 0.0, 0.0, 0.0))
    harness.index("doc-b", (0.0, 1.0, 0.0, 0.0), view="body")
    return harness


def test_status_reports_counts_kinds_and_coverage(status_engine):
    harness = _linear_harness(status_engine)
    with Session(status_engine) as session:
        session.add(_snapshot(harness, ann_recall=0.98, ann_recall_k=10, probe_size=100))
        session.commit()
        statuses = read_space_statuses(session)

    assert len(statuses) == 1
    status = statuses[0]
    assert status["name"] == harness.space.name
    assert status["status"] == "active"
    assert status["backend"] == vc.BACKEND_LINEAR
    assert status["dim"] == DIM
    assert status["space_key"] == harness.space.key
    assert status["documents"] == 2
    assert status["records"] == 2
    assert status["documents_without_records"] == 0
    assert status["kinds"] == [{"kind": "posting", "documents": 2, "records": 2}]
    coverage = status["coverage"]
    assert coverage["source"] == "snapshot"
    assert (coverage["total"], coverage["embedded"], coverage["missing"]) == (10, 9, 1)
    assert coverage["percent"] == 90.0
    assert coverage["ann_recall"] == pytest.approx(0.98)
    assert status["physical"]["table_exists"] is False, "linear owns no physical table"
    assert status["physical"]["index_present"] is False
    drop_space(harness)


def test_status_reports_never_reconciled_instead_of_zero(status_engine):
    harness = _linear_harness(status_engine)
    with Session(status_engine) as session:
        status = read_space_statuses(session)[0]
    assert status["coverage"]["source"] == "never_reconciled"
    assert status["coverage"]["percent"] is None
    assert status["coverage"]["as_of"] is None
    drop_space(harness)


def test_status_flags_documents_without_records(status_engine):
    harness = _linear_harness(status_engine)
    harness.add_document("doc-c")
    with Session(status_engine) as session:
        status = read_space_statuses(session)[0]
    assert status["documents"] == 3
    assert status["documents_without_records"] == 1
    assert status["kinds"] == [{"kind": "posting", "documents": 3, "records": 2}]
    drop_space(harness)


def test_status_reports_the_last_vector_index_job(status_engine):
    harness = _linear_harness(status_engine)
    now = datetime.now(UTC)
    with Session(status_engine) as session:
        session.add(
            BackgroundJob(
                job_type="vector_index",
                status="succeeded",
                progress=100,
                stage="done",
                payload={"kind": "posting", "source_id": "x", "space": harness.space.name},
                result={"embedded": 2},
                attempts=1,
                max_attempts=1,
                finished_at=now,
            )
        )
        session.add(
            BackgroundJob(
                job_type="vector_index",
                status="failed",
                error="embed provider down",
                payload={"kind": "posting", "source_id": "y", "space": harness.space.name},
                attempts=2,
                max_attempts=2,
                finished_at=now - timedelta(minutes=5),
            )
        )
        session.commit()
        status = read_space_statuses(session)[0]
    assert status["last_reindex"]["job_id"]
    assert status["last_reindex"]["status"] == "succeeded"
    assert status["last_reindex"]["result"] == {"embedded": 2}
    assert status["last_error"] is None, "the latest run succeeded"
    drop_space(harness)


def test_status_reports_a_missing_physical_index(status_engine, tmp_path):
    engine = status_engine
    if NATIVE_IS_POSTGRESQL:
        engine = create_native_engine()
        if not ensure_pgvector(engine):
            pytest.skip("pgvector is not installed in this environment")
        selected = vc.BACKEND_PGVECTOR
    elif sqlite_vec_available(engine):
        selected = vc.BACKEND_SQLITE_VEC
    else:
        pytest.skip("sqlite-vec is not loadable in this environment")
    harness = create_space(engine, backend_name=selected)
    try:
        table = harness.space.index_table or ""
        with Session(engine) as session:
            session.execute(text(f"DROP TABLE {table}"))
            session.commit()
            status = next(
                entry
                for entry in read_space_statuses(session)
                if entry["space_id"] == harness.space.space_id
            )
            health = read_health(
                session,
                store=VectorStoreService(engine, backend=backend_for(engine, selected)),
            )
        entry = next(
            space for space in health["spaces"] if space["space_id"] == harness.space.space_id
        )
        assert status["physical"]["table_exists"] is False
        assert status["physical"]["index_present"] is False
        assert entry["ok"] is False
        assert "missing" in entry["detail"]
    finally:
        drop_space(harness)
        if engine is not status_engine:
            engine.dispose()


@pytest.mark.parametrize("backend_name", ["linear", "ann"])
def test_health_reports_the_selected_backend(tmp_path, backend_name):
    if backend_name == "ann":
        if NATIVE_IS_POSTGRESQL:
            engine = create_native_engine()
            if not ensure_pgvector(engine):
                engine.dispose()
                pytest.skip("pgvector is not installed in this environment")
            selected = vc.BACKEND_PGVECTOR
        else:
            engine = _status_engine(tmp_path)
            if not sqlite_vec_available(engine):
                engine.dispose()
                pytest.skip("sqlite-vec is not loadable in this environment")
            selected = vc.BACKEND_SQLITE_VEC
    else:
        engine = _status_engine(tmp_path)
        selected = vc.BACKEND_LINEAR
    try:
        harness = create_space(engine, backend_name=selected)
        harness.add_document("doc-a")
        harness.index("doc-a", (1.0, 0.0, 0.0, 0.0))
        store = VectorStoreService(engine, backend=backend_for(engine, selected))
        with Session(engine) as session:
            health = read_health(session, store=store)
        entry = next(
            space for space in health["spaces"] if space["space_id"] == harness.space.space_id
        )
        assert health["backend"] == selected
        assert entry["ok"] is True
        assert entry["detail"]
        if selected == vc.BACKEND_LINEAR:
            assert health["capabilities"]["ann"] is False
            assert health["semantic_available"] is False
        else:
            assert health["capabilities"]["ann"] is True
            assert health["extension"]["version"] is not None
            assert health["semantic_available"] is True
        drop_space(harness)
    finally:
        engine.dispose()


def test_health_reports_an_empty_store_honestly(status_engine):
    with Session(status_engine) as session:
        health = read_health(
            session,
            store=VectorStoreService(
                status_engine, backend=backend_for(status_engine, vc.BACKEND_LINEAR)
            ),
        )
    assert health["spaces"] == []
    assert health["ok"] is True
    assert health["detail"] == "no vector spaces provisioned"


def test_health_flags_a_broken_physical_index(status_engine):
    harness = create_space(status_engine, backend_name=vc.BACKEND_LINEAR)
    with Session(status_engine) as session:
        row = session.get(VectorSpaceRow, uuid.UUID(harness.space.space_id or ""))
        assert row is not None
        row.index_table = "vec_deadbeef"
        session.commit()
        health = read_health(
            session,
            store=VectorStoreService(
                status_engine, backend=backend_for(status_engine, vc.BACKEND_LINEAR)
            ),
        )
    assert health["ok"] is False
    assert health["spaces"][0]["ok"] is False
    assert "linear backend owns no index table" in health["spaces"][0]["detail"]
    with Session(status_engine) as session:
        row = session.get(VectorSpaceRow, uuid.UUID(harness.space.space_id or ""))
        assert row is not None
        row.index_table = None
        session.commit()
    drop_space(harness)
