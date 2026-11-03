"""Alembic autogenerate must never see the extension-managed vector objects.

The ``vec_*`` tables and the sqlite-vec ``vector_entry_ids`` rowid map are
owned by the provisioning seam, not by the ORM metadata. A live/dev database
carrying them must not emit ``RemoveTable``; this test creates both, compares
the metadata with and without the ``include_object`` hook (proving the hook
is what suppresses them), and pins the hook in ``alembic/env.py``.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

from app.models import Base
from app.storage.vector_schema import include_object, is_extension_managed_table
from tests.vector_harness import create_native_engine


@pytest.fixture
def engine():
    candidate = create_native_engine()
    try:
        yield candidate
    finally:
        candidate.dispose()


def _create_manager_tables(engine) -> tuple[str, str, bool]:
    table = f"vec_{uuid.uuid4().hex[:8]}"
    with engine.connect() as connection:
        connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        existing = connection.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'vector_entry_ids'")
            if engine.dialect.name == "sqlite"
            else text(
                "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = 'vector_entry_ids' AND n.nspname = current_schema()"
            )
        ).scalar()
        if existing is None:
            connection.execute(
                text(
                    "CREATE TABLE vector_entry_ids ("
                    "record_rowid INTEGER PRIMARY KEY, record_id TEXT NOT NULL UNIQUE)"
                )
            )
        connection.commit()
    return table, "vector_entry_ids", existing is None


def _remove_tables(engine, include: bool) -> set[str]:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"include_object": include_object} if include else {},
        )
        diff = compare_metadata(context, Base.metadata)
    names: set[str] = set()
    for entry in diff:
        if isinstance(entry, tuple) and entry and entry[0] == "remove_table":
            names.add(entry[1].name)
    return names


def _drop(engine, table: str, entry_ids: str, drop_entry_ids: bool) -> None:
    with engine.connect() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
        if drop_entry_ids:
            connection.execute(text(f"DROP TABLE IF EXISTS {entry_ids}"))
        connection.commit()


def test_autogenerate_ignores_the_physical_vector_objects(engine):
    table, entry_ids, drop_entry_ids = _create_manager_tables(engine)
    try:
        without_hook = _remove_tables(engine, include=False)
        assert table in without_hook, "the probe table must be visible to autogenerate"
        assert entry_ids in without_hook

        with_hook = _remove_tables(engine, include=True)
        assert table not in with_hook
        assert entry_ids not in with_hook
    finally:
        _drop(engine, table, entry_ids, drop_entry_ids)


def test_include_object_is_name_scoped():
    assert is_extension_managed_table("vec_0123abcd") is True
    assert is_extension_managed_table("vector_entry_ids") is True
    assert is_extension_managed_table("vector_records") is False
    assert is_extension_managed_table("vec_NOTHEX") is False
    assert include_object(None, "vec_0123abcd", "table", True, None) is False
    assert include_object(None, "vector_entry_ids", "table", True, None) is False
    assert include_object(None, "vector_records", "table", False, None) is True
    assert include_object(None, "ix_vec_0123abcd_hnsw", "index", True, None) is False


def test_alembic_env_wires_the_hook():
    env_source = (Path(__file__).resolve().parents[1] / "alembic" / "env.py").read_text(
        encoding="utf-8"
    )
    assert "include_object=include_object" in env_source
    assert env_source.count("include_object=include_object") == 2
