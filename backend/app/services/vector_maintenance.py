"""Bounded vector-store maintenance actions (plan 51 Q1b).

The action API never runs DDL on the request path; it enqueues a
``VECTOR_MAINTENANCE`` handler and this service executes one typed action:

* ``index-rebuild`` — PostgreSQL ``REINDEX INDEX CONCURRENTLY`` on the
  space's HNSW index. Concurrent reindex cannot run inside a transaction, so
  it uses an AUTOCOMMIT connection. SQLite has no online rebuild for the
  ``vec0`` virtual table; the honest dialect path is ``VACUUM`` (the store's
  file is rebuilt) and the result says so.
* ``vacuum`` — PostgreSQL ``VACUUM (ANALYZE)`` / SQLite ``VACUUM``, both on
  an AUTOCOMMIT connection.
* ``orphan-sweep`` — page through the space's documents and delete the ones
  whose polymorphic source no longer resolves, reusing the store's
  ``orphan_sweep`` erase path. ``dry_run`` counts without deleting.

Every path is bounded (``limit``), returns the family run-result contract and
never scans the whole corpus in one page. A linear space (no physical index)
honestly skips the physical actions instead of pretending they ran.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.services.vector_index_service import load_source
from app.storage.retrieval_ops import MaintenanceAction
from app.storage.vector_schema import validate_index_table
from app.storage.vector_store import VectorStoreService, canonical_space

DEFAULT_ORPHAN_LIMIT = 500
MAX_ORPHAN_LIMIT = 5000
ORPHAN_PAGE_SIZE = 500


def _result(**extra: Any) -> dict[str, Any]:
    """The run-result contract plus the action's own bounded detail block."""
    payload: dict[str, Any] = {
        "scanned": int(extra.pop("scanned", 0)),
        "embedded": 0,
        "skipped": 0,
        "failed": int(extra.pop("failed", 0)),
        "failed_ids": [],
        "failed_ids_truncated": False,
        "gate": "unknown",
    }
    payload.update(extra)
    return payload


def _autocommit(engine: Engine) -> Any:
    return engine.connect().execution_options(isolation_level="AUTOCOMMIT")


def run_sql_autocommit(engine: Engine, sql: str) -> None:
    """Run one statement outside a transaction (VACUUM/REINDEX CONCURRENTLY)."""
    with _autocommit(engine) as connection:
        connection.execute(text(sql))


async def _space_row(db: AsyncSession, ref: str | uuid.UUID) -> Any:
    from app.services import retrieval_ops_reads as reads

    return await reads.resolve_space(db, ref)


async def _orphan_sweep(
    db: AsyncSession,
    *,
    store: VectorStoreService,
    space: Any,
    limit: int,
    dry_run: bool,
    cancelled: Any = None,
) -> dict[str, Any]:
    page_size = min(max(limit, 1), ORPHAN_PAGE_SIZE)
    remaining = min(max(limit, 1), MAX_ORPHAN_LIMIT)
    after_id: str | None = None
    scanned = 0
    removed = 0
    stopped = False
    while remaining > 0:
        if cancelled is not None and await cancelled():
            stopped = True
            break
        page = store.lookup_documents(
            space,
            after_id=after_id,
            limit=min(page_size, remaining),
        )
        if not page:
            break
        ordered_ids = sorted(page)
        exists: dict[tuple[str, str], bool] = {}
        for document_id in ordered_ids:
            info = page[document_id]
            exists[(info.kind, info.source_id)] = (
                await load_source(db, info.kind, info.source_id) is not None
            )

        def resolve(
            kind: str, source_id: str, _exists: dict[tuple[str, str], bool] = exists
        ) -> bool:
            return _exists.get((kind, source_id), True)

        removed += store.orphan_sweep(
            space,
            resolve,
            limit=len(ordered_ids),
            after_id=after_id,
            dry_run=dry_run,
        )
        scanned += len(ordered_ids)
        remaining -= len(ordered_ids)
        after_id = ordered_ids[-1]
        if len(ordered_ids) < min(page_size, limit):
            break
    return {
        "scanned": scanned,
        "removed": removed,
        "dry_run": dry_run,
        "cancelled": stopped,
    }


async def run_maintenance(
    db: AsyncSession,
    *,
    space_id: str | uuid.UUID,
    action: str | MaintenanceAction,
    dry_run: bool = False,
    limit: int | None = None,
    store: VectorStoreService | None = None,
    engine: Engine | None = None,
    cancelled: Any = None,
) -> dict[str, Any]:
    """Execute one typed maintenance action against one space."""
    try:
        typed = MaintenanceAction(action)
    except ValueError as exc:
        raise ValidationError(
            f"unknown maintenance action {action!r}; expected one of "
            f"{[member.value for member in MaintenanceAction]}"
        ) from exc
    if store is None or engine is None:
        from app.core.database import sync_engine

        store = store or VectorStoreService(sync_engine)
        engine = engine or sync_engine
    row = await _space_row(db, space_id)
    space = canonical_space(row)
    dialect = str(db.get_bind().dialect.name)
    table = row.index_table
    physical = space.index_table is not None

    if typed is MaintenanceAction.ORPHAN_SWEEP:
        bounded = min(int(limit or DEFAULT_ORPHAN_LIMIT), MAX_ORPHAN_LIMIT)
        detail = await _orphan_sweep(db, store=store, space=space, limit=bounded, dry_run=dry_run)
        return _result(
            scanned=detail["scanned"],
            maintenance={
                "action": typed.value,
                "dialect": dialect,
                "dry_run": dry_run,
                "limit": bounded,
                "removed": detail["removed"],
                "cancelled": detail["cancelled"],
            },
        )

    if not physical:
        return _result(
            maintenance={
                "action": typed.value,
                "dialect": dialect,
                "dry_run": dry_run,
                "skipped": "no physical index (linear backend)",
            }
        )
    validate_index_table(table)
    index_name = f"ix_{table}_hnsw"
    if typed is MaintenanceAction.INDEX_REBUILD:
        if dialect == "postgresql":
            sql = f"REINDEX INDEX CONCURRENTLY {index_name}"
            executed = "reindex concurrently"
        elif dialect == "sqlite":
            sql = "VACUUM"
            executed = "vacuum (sqlite has no online REINDEX for vec0)"
        else:  # pragma: no cover - only two dialects exist
            raise ValidationError(f"index maintenance is not supported on {dialect}")
    elif typed is MaintenanceAction.VACUUM:
        sql = f"VACUUM (ANALYZE) {table}" if dialect == "postgresql" else "VACUUM"
        executed = "vacuum"
    else:  # pragma: no cover - retry-failed never reaches the handler
        raise ValidationError(f"{typed.value} is not a direct maintenance action")
    detail = {
        "action": typed.value,
        "dialect": dialect,
        "dry_run": dry_run,
        "index_table": table,
        "index": index_name if typed is MaintenanceAction.INDEX_REBUILD else None,
        "sql": sql,
        "executed": None if dry_run else executed,
    }
    if not dry_run:
        run_sql_autocommit(engine, sql)
    return _result(maintenance=detail)


__all__ = [
    "DEFAULT_ORPHAN_LIMIT",
    "MAX_ORPHAN_LIMIT",
    "ORPHAN_PAGE_SIZE",
    "run_maintenance",
    "run_sql_autocommit",
]
