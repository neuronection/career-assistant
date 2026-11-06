"""Physical index provisioning on both dialects (plan 50 §3.4, P1b).

Table/index/rowid-map creation, idempotency, the exact ``vec_<8 hex>``
validation the DB CHECK cannot express, dimension-mismatch refusal and the
linear (no physical table) path.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.storage import vector_contract as vc
from app.storage.vector_provisioning import (
    VectorDimensionMismatch,
    VectorProvisioningError,
    provision_space,
    space_status,
)
from app.storage.vector_schema import INDEX_TABLE_RE, index_table_name
from tests.vector_harness import (
    column_type,
    create_native_engine,
    create_sqlite_engine,
    table_exists,
)

DIM = 4


@pytest.fixture(params=["native", "sqlite"])
def engine(request, tmp_path) -> Iterator:
    if request.param == "sqlite":
        candidate = create_sqlite_engine(tmp_path / "vector-provision.db")
    else:
        candidate = create_native_engine()
    try:
        yield candidate
    finally:
        candidate.dispose()


def _new_space(engine, *, dim: int = DIM) -> uuid.UUID:
    with Session(engine) as session:
        row = VectorSpaceRow(
            name=f"provision-{uuid.uuid4().hex[:10]}",
            provider="openai",
            model="text-embedding-3-small",
            dim=dim,
        )
        session.add(row)
        session.commit()
        return row.id


def _drop(engine, space_id: uuid.UUID) -> None:
    with Session(engine) as session:
        row = session.get(VectorSpaceRow, space_id)
        if row is None:
            return
        table = row.index_table
        if table is not None:
            session.execute(text(f"DROP TABLE IF EXISTS {table}"))
        session.delete(row)
        session.commit()


def test_provision_creates_the_index_idempotently(engine):
    space_id = _new_space(engine)
    try:
        with Session(engine) as session:
            row = session.get(VectorSpaceRow, space_id)
            result = provision_space(session, row)
            assert result.index_table is not None
            assert INDEX_TABLE_RE.fullmatch(result.index_table)
            assert result.dim == DIM
            assert result.created is True

            again = provision_space(session, row)
            assert again.index_table == result.index_table
            assert again.created is False
            assert again.backend == result.backend

        with Session(engine) as fresh:
            status = space_status(fresh, space_id)
            assert status.table_exists is True
            assert status.table_dim == DIM
            assert status.index_present is True
            assert status.row_count == 0

        table = result.index_table
        assert table_exists(engine, table)
        if engine.dialect.name == "postgresql":
            assert column_type(engine, table, "embedding") == f"vector({DIM})"
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text(
                            "SELECT 1 FROM pg_indexes WHERE tablename = :table "
                            "AND indexname = :index"
                        ),
                        {"table": table, "index": f"ix_{table}_hnsw"},
                    ).scalar()
                    is not None
                )
        else:
            assert table_exists(engine, "vector_entry_ids")
            declared = column_type(engine, table, "embedding")
            assert f"float[{DIM}]" in str(declared)
    finally:
        _drop(engine, space_id)


def test_provision_refuses_a_dimension_mismatch(engine):
    space_id = _new_space(engine)
    try:
        with Session(engine) as session:
            row = session.get(VectorSpaceRow, space_id)
            provision_space(session, row)
            row.dim = DIM * 2
            session.commit()
            with pytest.raises(VectorDimensionMismatch):
                provision_space(session, row)
            session.rollback()
            row = session.get(VectorSpaceRow, space_id)
            row.dim = DIM
            session.commit()
    finally:
        _drop(engine, space_id)


def test_provision_refuses_a_non_hex_index_table(engine):
    space_id = _new_space(engine)
    try:
        with Session(engine) as session:
            row = session.get(VectorSpaceRow, space_id)
            row.index_table = "vec_ZZZZZZZZ"
            session.commit()
            with pytest.raises(ValueError):
                provision_space(session, row)
            session.rollback()
            row = session.get(VectorSpaceRow, space_id)
            row.index_table = None
            session.commit()
    finally:
        _drop(engine, space_id)


def test_provision_refuses_an_index_table_not_derived_from_the_uuid(engine):
    space_id = _new_space(engine)
    try:
        with Session(engine) as session:
            row = session.get(VectorSpaceRow, space_id)
            row.index_table = "vec_deadbeef"
            session.commit()
            with pytest.raises(VectorProvisioningError):
                provision_space(session, row)
            session.rollback()
            row = session.get(VectorSpaceRow, space_id)
            row.index_table = None
            session.commit()
    finally:
        _drop(engine, space_id)


def test_linear_provisioning_creates_no_table(engine):
    space_id = _new_space(engine)
    try:
        with Session(engine) as session:
            row = session.get(VectorSpaceRow, space_id)
            result = provision_space(session, row, backend=vc.BACKEND_LINEAR)
            assert result.backend == vc.BACKEND_LINEAR
            assert result.index_table is None
            assert result.created is False
            status = space_status(session, row)
            assert status.backend == vc.BACKEND_LINEAR
            assert status.table_exists is False
            assert status.index_table is None
    finally:
        _drop(engine, space_id)


def test_provision_requires_a_persisted_space(engine):
    with Session(engine) as session, pytest.raises(VectorProvisioningError):
        provision_space(session, uuid.uuid4())


def test_pg_provisioning_refuses_dimensions_hnsw_cannot_index():
    engine = create_native_engine()
    try:
        if engine.dialect.name != "postgresql":
            pytest.skip("the pgvector HNSW dimension ceiling is PostgreSQL-only")
        space_id = _new_space(engine, dim=2001)
        try:
            with Session(engine) as session:
                row = session.get(VectorSpaceRow, space_id)
                with pytest.raises(VectorProvisioningError) as raised:
                    provision_space(session, row)
            assert "2000" in str(raised.value)
            assert "halfvec" in str(raised.value)
            table = index_table_name(space_id)
            assert table_exists(engine, table) is False, "the guard runs before any DDL"
        finally:
            _drop(engine, space_id)
    finally:
        engine.dispose()


def test_create_pg_extension_uses_a_separate_autocommit_connection(monkeypatch):
    from app.storage import vector_provisioning as vp

    recorded: dict[str, object] = {}

    class FakeConnection:
        def __init__(self) -> None:
            self.options: dict[str, object] = {}

        def execution_options(self, **kwargs):
            self.options.update(kwargs)
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> bool:
            return False

        def execute(self, statement):
            recorded["sql"] = str(statement)
            recorded["options"] = dict(self.options)

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    class FakeSession:
        def get_bind(self):
            return FakeEngine()

    monkeypatch.setattr(vp, "Engine", FakeEngine)
    vp._create_pg_extension(FakeSession())  # type: ignore[arg-type]
    assert "CREATE EXTENSION IF NOT EXISTS vector" in str(recorded["sql"])
    assert recorded["options"] == {"isolation_level": "AUTOCOMMIT"}


def test_create_pg_extension_failure_is_loud(monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from app.storage import vector_provisioning as vp

    class FailingConnection:
        def execution_options(self, **_kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> bool:
            return False

        def execute(self, _statement):
            raise SQLAlchemyError("permission denied to create extension")

    class FakeEngine:
        def connect(self):
            return FailingConnection()

    class FakeSession:
        def get_bind(self):
            return FakeEngine()

    monkeypatch.setattr(vp, "Engine", FakeEngine)
    with pytest.raises(VectorProvisioningError) as raised:
        vp._create_pg_extension(FakeSession())  # type: ignore[arg-type]
    assert "hard prerequisite" in str(raised.value)
