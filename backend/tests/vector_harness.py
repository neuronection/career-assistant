"""Shared fixtures for the P1b vector-store tests (not collected by pytest).

Builds a small space on either dialect, provisions its physical index and
returns a service wired to the matching backend. PostgreSQL uses the test
database (already migrated to head); SQLite uses a throwaway file with only
the vector metadata tables so the desktop lane never needs the full schema.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import (
    Column,
    Engine,
    MetaData,
    Table,
    Uuid,
    create_engine,
    delete,
    event,
    text,
)
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.vector_model import VectorDocument, VectorRecord
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.storage import vector_contract as vc
from app.storage.vector_backends import (
    LinearBackend,
    PgVectorBackend,
    SqliteVecBackend,
    VectorBackend,
)
from app.storage.vector_provisioning import provision_space
from app.storage.vector_store import VectorStoreService, canonical_space

DIM = 4


def sync_url(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


def _sqlite_foreign_keys(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_native_engine() -> Engine:
    engine = create_engine(sync_url(settings.database_url), pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_foreign_keys)
    return engine


def create_sqlite_engine(path: Path) -> Engine:
    """Only the vector metadata tables, so a desktop test needs no full schema."""
    engine = create_engine(f"sqlite:///{path}", pool_pre_ping=True)
    event.listen(engine, "connect", _sqlite_foreign_keys)
    metadata = MetaData()
    Table("profiles", metadata, Column("id", Uuid, primary_key=True))
    for model in (VectorSpaceRow, VectorDocument, VectorRecord):
        model.__table__.to_metadata(metadata)
    metadata.create_all(engine)
    return engine


def ensure_pgvector(engine: Engine) -> bool:
    """True when the PG test database has pgvector, installing it when permitted."""
    if engine.dialect.name != "postgresql":
        return False
    from app.storage.vector_backends import pgvector_available

    if pgvector_available(engine):
        return True
    try:
        with engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
    except Exception:
        return False
    return pgvector_available(engine)


def backend_for(engine: Engine, name: str) -> VectorBackend:
    if name == vc.BACKEND_LINEAR:
        return LinearBackend(engine)
    if name == vc.BACKEND_PGVECTOR:
        return PgVectorBackend(engine)
    if name == vc.BACKEND_SQLITE_VEC:
        return SqliteVecBackend(engine)
    raise ValueError(f"unknown backend {name!r}")


def backend_name_for(engine: Engine) -> str:
    if engine.dialect.name == "postgresql":
        return vc.BACKEND_PGVECTOR
    if engine.dialect.name == "sqlite":
        return vc.BACKEND_SQLITE_VEC
    raise ValueError(f"unsupported dialect {engine.dialect.name!r}")


@dataclass
class Harness:
    engine: Engine
    backend_name: str
    space: vc.VectorSpace
    service: VectorStoreService
    documents: dict[str, uuid.UUID] = field(default_factory=dict)
    scopes: dict[str, str] = field(default_factory=dict)

    def add_document(
        self,
        name: str,
        *,
        scope_type: str = "tenant",
        kind: str = "posting",
        source_id: str | None = None,
        source_hash: str = "0" * 64,
    ) -> uuid.UUID:
        registered = self.service.register_document(
            self.space,
            kind=kind,
            source_id=source_id or f"{name}-{uuid.uuid4().hex[:8]}",
            scope_type=scope_type,
            source_hash=source_hash,
            schema_version=1,
        )
        document_id = uuid.UUID(registered.document_id)
        self.documents[name] = document_id
        self.scopes[name] = scope_type
        return document_id

    def record(
        self,
        name: str,
        embedding: tuple[float, ...],
        *,
        record_id: str | None = None,
        view: str = "summary",
        chunk_index: int = 0,
        content_hash: str = "hash",
    ) -> vc.IndexRecord:
        return vc.IndexRecord(
            record_id=record_id or str(uuid.uuid4()),
            document_id=str(self.documents[name]),
            view=view,
            chunk_index=chunk_index,
            embedding=embedding,
            content_hash=content_hash,
        )

    def index(
        self,
        name: str,
        embedding: tuple[float, ...],
        *,
        record_id: str | None = None,
        view: str = "summary",
        chunk_index: int = 0,
        content_hash: str = "hash",
    ) -> vc.IndexRecord:
        record = self.record(
            name,
            embedding,
            record_id=record_id,
            view=view,
            chunk_index=chunk_index,
            content_hash=content_hash,
        )
        self.service.upsert_document(self.space, document_id=self.documents[name], records=[record])
        return record

    def index_many(self, records: list[vc.IndexRecord]) -> None:
        by_document: dict[uuid.UUID, list[vc.IndexRecord]] = {}
        for record in records:
            by_document.setdefault(uuid.UUID(record.document_id), []).append(record)
        for document_id, group in by_document.items():
            self.service.upsert_document(self.space, document_id=document_id, records=group)

    def search(
        self,
        query: tuple[float, ...],
        *,
        views: tuple[str, ...] = ("summary",),
        scope: vc.ScopeSpec | None = None,
        limit: int = 10,
        ef_search: int | None = None,
    ) -> list[vc.IndexHit]:
        return self.service.search(
            self.space,
            query,
            views=views,
            scope=scope or vc.ScopeSpec(kind="all", predicate=None),
            limit=limit,
            ef_search=ef_search,
        )


def create_space(
    engine: Engine,
    *,
    backend_name: str | None = None,
    dim: int = DIM,
    name: str | None = None,
) -> Harness:
    selected = backend_name or backend_name_for(engine)
    space_name = name or f"content-{uuid.uuid4().hex[:10]}"
    with Session(engine) as session:
        row = VectorSpaceRow(
            name=space_name,
            provider="openai",
            model="text-embedding-3-small",
            dim=dim,
        )
        session.add(row)
        session.commit()
        provision_space(session, row, backend=selected)
        session.refresh(row)
        canonical = canonical_space(row)
    backend = backend_for(engine, selected)
    return Harness(
        engine=engine,
        backend_name=selected,
        space=canonical,
        service=VectorStoreService(engine, backend=backend),  # type: ignore[arg-type]
    )


def drop_space(harness: Harness) -> None:
    table = harness.space.index_table
    with Session(harness.engine) as session:
        if table is not None:
            if harness.engine.dialect.name == "sqlite":
                session.execute(text(f"DROP TABLE IF EXISTS {table}"))
                space_id = uuid.UUID(harness.space.space_id or "")
                session.execute(delete(VectorRecord).where(VectorRecord.space_id == space_id))
                session.execute(delete(VectorDocument).where(VectorDocument.space_id == space_id))
            else:
                session.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        session.execute(
            delete(VectorSpaceRow).where(
                VectorSpaceRow.id == uuid.UUID(harness.space.space_id or "")
            )
        )
        session.commit()


def table_exists(engine: Engine, table: str) -> bool:
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            return (
                connection.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"),
                    {"name": table},
                ).scalar()
                is not None
            )
        return (
            connection.execute(
                text("SELECT to_regclass(CAST(:table AS text))"), {"table": table}
            ).scalar()
            is not None
        )


def column_type(engine: Engine, table: str, column: str) -> str | None:
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            return connection.execute(
                text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
                {"name": table},
            ).scalar()
        return connection.execute(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                "WHERE a.attrelid = CAST(:table AS regclass) AND a.attname = :column "
                "AND NOT a.attisdropped"
            ),
            {"table": table, "column": column},
        ).scalar()
