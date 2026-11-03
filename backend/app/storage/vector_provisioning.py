"""Physical vector-store provisioning for one embedding space (plan 50 §3.4,
P1b).

This is the only seam allowed to issue ``CREATE TABLE`` for a vector index.
It never runs on a request path: a migration or the (P1c) reindex job calls
:func:`provision_space` off the request; desktop users never run the CLI.
The metadata row and the DDL commit together, so ``vector_spaces.index_table``
is never true while the physical table is missing (or vice versa).

PostgreSQL is a hard prerequisite: a web deployment that enables semantic
search must have the ``vector`` extension, and provisioning fails loudly when
it cannot be created. SQLite is best-effort: without a loadable
``sqlite-vec`` the space stays linear (``index_table`` stays ``NULL``) and the
factory never pretends an ANN index exists.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.storage.vector_contract import (
    BACKEND_LINEAR,
    BACKEND_PGVECTOR,
    BACKEND_SQLITE_VEC,
    VectorSpace,
)
from app.storage.vector_schema import (
    VECTOR_ENTRY_IDS_TABLE,
    index_table_name,
    validate_index_table,
)

logger = logging.getLogger(__name__)


class VectorProvisioningError(RuntimeError):
    """Provisioning could not create a usable physical store."""


class VectorDimensionMismatch(VectorProvisioningError):
    """An existing physical table has a different dimension than the space."""


@dataclass(frozen=True)
class SpaceProvision:
    """The result of one idempotent provisioning call."""

    space_id: str
    name: str
    backend: str
    index_table: str | None
    dim: int
    created: bool
    detail: str


@dataclass(frozen=True)
class SpaceStatus:
    """The physical side of one space, for ops/status reads."""

    space_id: str
    name: str
    backend: str
    index_table: str | None
    dim: int
    table_exists: bool
    table_dim: int | None
    index_present: bool
    row_count: int
    detail: str


def _sessionmaker(bind: Engine | sessionmaker[Session]) -> sessionmaker[Session]:
    return sessionmaker(bind=bind, expire_on_commit=False) if isinstance(bind, Engine) else bind


def _row_for(
    session: Session,
    space: VectorSpace | VectorSpaceRow | uuid.UUID | str,
) -> VectorSpaceRow:
    if isinstance(space, VectorSpaceRow):
        row = session.get(VectorSpaceRow, space.id)
    elif isinstance(space, VectorSpace):
        if space.space_id is not None:
            row = session.get(VectorSpaceRow, uuid.UUID(str(space.space_id)))
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
    else:
        row = session.get(VectorSpaceRow, uuid.UUID(str(space)))
    if row is None:
        raise VectorProvisioningError(f"vector space {space!r} has no persisted row")
    return row


def _declared_table(row: VectorSpaceRow) -> str:
    if row.index_table is not None:
        validate_index_table(row.index_table)
        expected = index_table_name(row.id)
        if row.index_table != expected:
            raise VectorProvisioningError(
                f"space {row.name!r} declares {row.index_table!r}, "
                f"but its UUID derives {expected!r}"
            )
        return row.index_table
    return index_table_name(row.id)


def _pg_extension_version(session: Session) -> str:
    version = session.execute(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    if version is None:
        try:
            with session.begin_nested():
                session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except SQLAlchemyError as exc:
            raise VectorProvisioningError(
                "pgvector is not installed and CREATE EXTENSION vector failed — "
                "semantic search is a hard prerequisite on PostgreSQL"
            ) from exc
        version = session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
    if version is None:  # pragma: no cover - defensive
        raise VectorProvisioningError("pgvector could not be installed")
    return str(version)


def _pg_provision(session: Session, row: VectorSpaceRow) -> SpaceProvision:
    table = _declared_table(row)
    version = _pg_extension_version(session)
    exists = (
        session.execute(text("SELECT to_regclass(CAST(:table AS text))"), {"table": table}).scalar()
        is not None
    )
    if exists:
        declared = session.execute(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) "
                "FROM pg_attribute a "
                "WHERE a.attrelid = CAST(:table AS regclass) "
                "AND a.attname = 'embedding' AND NOT a.attisdropped"
            ),
            {"table": table},
        ).scalar()
        match = re.fullmatch(r"vector\((\d+)\)", str(declared or ""))
        if match is None:
            raise VectorDimensionMismatch(
                f"existing index {table!r} has no vector embedding column ({declared!r})"
            )
        if int(match.group(1)) != row.dim:
            raise VectorDimensionMismatch(
                f"existing index {table!r} is vector({match.group(1)}), "
                f"space {row.name!r} needs vector({row.dim})"
            )
    else:
        session.execute(
            text(
                f"CREATE TABLE {table} ("
                "record_id UUID PRIMARY KEY REFERENCES vector_records(id) ON DELETE CASCADE, "
                f"embedding vector({row.dim}) NOT NULL)"
            )
        )
    session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_hnsw ON {table} "
            "USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )
    )
    row.index_table = table
    return SpaceProvision(
        space_id=str(row.id),
        name=row.name,
        backend=BACKEND_PGVECTOR,
        index_table=table,
        dim=row.dim,
        created=not exists,
        detail=f"pgvector {version}: {table} vector({row.dim}) + HNSW cosine",
    )


def _sqlite_load_vec(session: Session) -> bool:
    try:
        import sqlite_vec
    except ImportError:  # pragma: no cover - sqlite-vec is a desktop extra
        return False
    try:
        raw = session.connection().connection.driver_connection
        if raw is None:
            return False
        raw.enable_load_extension(True)
        sqlite_vec.load(raw)
        session.connection().exec_driver_sql("SELECT vec_version()").scalar()
        return True
    except Exception:
        logger.warning("sqlite-vec could not be loaded", exc_info=True)
        return False


def _sqlite_table_dim(session: Session, table: str) -> int | None:
    sql = session.execute(
        text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
        {"name": table},
    ).scalar()
    if sql is None:
        return None
    match = re.search(r"float\[(\d+)\]", str(sql))
    if match is None:
        raise VectorDimensionMismatch(
            f"existing index {table!r} has no float[dim] embedding column"
        )
    return int(match.group(1))


def _sqlite_provision(session: Session, row: VectorSpaceRow) -> SpaceProvision:
    if not _sqlite_load_vec(session):
        if row.index_table is not None:
            raise VectorProvisioningError(
                f"space {row.name!r} already declares {row.index_table!r}, "
                "but sqlite-vec cannot be loaded"
            )
        return SpaceProvision(
            space_id=str(row.id),
            name=row.name,
            backend=BACKEND_LINEAR,
            index_table=None,
            dim=row.dim,
            created=False,
            detail="sqlite-vec unavailable: the space serves the linear fallback",
        )
    table = _declared_table(row)
    existing_dim = _sqlite_table_dim(session, table)
    if existing_dim is not None and existing_dim != row.dim:
        raise VectorDimensionMismatch(
            f"existing index {table!r} is float[{existing_dim}], "
            f"space {row.name!r} needs float[{row.dim}]"
        )
    session.execute(
        text(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
            "record_rowid INTEGER PRIMARY KEY, "
            f"embedding float[{row.dim}] distance_metric=cosine)"
        )
    )
    session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {VECTOR_ENTRY_IDS_TABLE} ("
            "record_rowid INTEGER PRIMARY KEY, record_id TEXT NOT NULL UNIQUE)"
        )
    )
    row.index_table = table
    version = session.connection().exec_driver_sql("SELECT vec_version()").scalar()
    return SpaceProvision(
        space_id=str(row.id),
        name=row.name,
        backend=BACKEND_SQLITE_VEC,
        index_table=table,
        dim=row.dim,
        created=existing_dim is None,
        detail=f"sqlite-vec {version}: {table} float[{row.dim}] cosine",
    )


def _linear_provision(row: VectorSpaceRow) -> SpaceProvision:
    if row.index_table is not None:
        raise VectorProvisioningError(
            f"space {row.name!r} already declares {row.index_table!r}; "
            "linear provisioning never drops a physical index"
        )
    return SpaceProvision(
        space_id=str(row.id),
        name=row.name,
        backend=BACKEND_LINEAR,
        index_table=None,
        dim=row.dim,
        created=False,
        detail="linear backend: vector_records.embedding is the single copy",
    )


def provision_space(
    session: Session,
    space: VectorSpace | VectorSpaceRow | uuid.UUID | str,
    *,
    backend: str | None = None,
    commit: bool = True,
) -> SpaceProvision:
    """Create/verify one space's physical index, idempotently.

    ``backend`` defaults to the dialect's engine (pgvector on PostgreSQL,
    sqlite-vec on SQLite); ``linear`` is available for an explicit fallback.
    The metadata ``index_table`` write commits in the same transaction as the
    DDL, so the two can never disagree.
    """
    row = _row_for(session, space)
    dialect = session.get_bind().dialect.name
    if backend == BACKEND_LINEAR:
        result = _linear_provision(row)
    elif backend == BACKEND_PGVECTOR:
        if dialect != "postgresql":
            raise VectorProvisioningError("pgvector provisioning needs PostgreSQL")
        result = _pg_provision(session, row)
    elif backend == BACKEND_SQLITE_VEC:
        if dialect != "sqlite":
            raise VectorProvisioningError("sqlite-vec provisioning needs SQLite")
        result = _sqlite_provision(session, row)
    elif dialect == "postgresql":
        result = _pg_provision(session, row)
    elif dialect == "sqlite":
        result = _sqlite_provision(session, row)
    else:  # pragma: no cover - an unsupported dialect has no vector store
        raise VectorProvisioningError(f"unsupported database dialect: {dialect}")
    if commit:
        session.commit()
    return result


def space_status(
    session: Session,
    space: VectorSpace | VectorSpaceRow | uuid.UUID | str,
) -> SpaceStatus:
    """Report the physical side of a space without creating anything."""
    row = _row_for(session, space)
    dialect = session.get_bind().dialect.name
    table = row.index_table
    if table is not None:
        validate_index_table(table)
    backend = BACKEND_LINEAR
    exists = False
    table_dim: int | None = None
    index_present = False
    row_count = 0
    detail = "linear fallback"
    if table is not None and dialect == "postgresql":
        backend = BACKEND_PGVECTOR
        declared = session.execute(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) "
                "FROM pg_attribute a "
                "WHERE a.attrelid = CAST(:table AS regclass) "
                "AND a.attname = 'embedding' AND NOT a.attisdropped"
            ),
            {"table": table},
        ).scalar()
        exists = declared is not None
        if declared is not None:
            match = re.fullmatch(r"vector\((\d+)\)", str(declared))
            table_dim = int(match.group(1)) if match else None
            row_count = int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
            index_present = (
                session.execute(
                    text(
                        "SELECT 1 FROM pg_indexes WHERE tablename = :table AND indexname = :index"
                    ),
                    {"table": table, "index": f"ix_{table}_hnsw"},
                ).scalar()
                is not None
            )
            detail = f"pgvector: {declared}, {row_count} row(s)"
        else:
            detail = f"pgvector: index table {table!r} is missing"
    elif table is not None and dialect == "sqlite":
        backend = BACKEND_SQLITE_VEC
        table_dim = _sqlite_table_dim(session, table)
        exists = table_dim is not None
        if exists:
            row_count = int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
            index_present = (
                session.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"),
                    {"name": VECTOR_ENTRY_IDS_TABLE},
                ).scalar()
                is not None
            )
            detail = f"sqlite-vec: float[{table_dim}], {row_count} row(s)"
    return SpaceStatus(
        space_id=str(row.id),
        name=row.name,
        backend=backend,
        index_table=table,
        dim=row.dim,
        table_exists=exists,
        table_dim=table_dim,
        index_present=index_present,
        row_count=row_count,
        detail=detail,
    )


def provision_for_bind(
    bind: Engine | sessionmaker[Session],
    space: VectorSpace | VectorSpaceRow | uuid.UUID | str,
    *,
    backend: str | None = None,
) -> SpaceProvision:
    """Session-owning wrapper for a CLI/job call site (P1c)."""
    with _sessionmaker(bind)() as session:
        return provision_space(session, space, backend=backend)
