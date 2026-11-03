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
from app.storage.vector_schema import INDEX_TABLE_RE
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
