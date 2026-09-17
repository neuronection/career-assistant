"""LangGraph checkpointer: app-lifespan-owned persistence.

Server mode checkpoints into Postgres (AsyncPostgresSaver), the desktop
profile into SQLite (AsyncSqliteSaver); tests pass an ``InMemorySaver``
explicitly. The saver is created lazily on first use and ``setup()``
runs once; ``aclose_checkpointer()`` releases it at shutdown.
``thread_id`` is the autopilot run id, so interrupted runs
continue from the last checkpoint instead of restarting.
"""

import logging
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

_stack: Optional[AsyncExitStack] = None
_checkpointer: Optional[BaseCheckpointSaver] = None


def _psycopg_uri() -> str:
    """The SQLAlchemy asyncpg URL rewritten for psycopg (checkpointer)."""
    url = settings.DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def _sqlite_path() -> str:
    """The checkpoint DB of the desktop profile.

    A separate sibling file, never the app database itself: the saver owns
    long write transactions (graph-step checkpoints) and sharing the file
    with the main engine deadlocks SQLite even under WAL ("database is
    locked" bursts while polish/autopilot runs are live). Fileless
    (``:memory:``) profiles stay in-memory.
    """
    url = settings.DATABASE_URL
    if "///" in url:
        path = url.split("///", 1)[-1]
    else:
        path = ""
    if not path or path == ":memory:":
        return ":memory:"
    return str(Path(path).parent / "checkpoints.db")


async def get_checkpointer() -> BaseCheckpointSaver:
    """The process checkpointer, created and set up on first use."""
    global _stack, _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    stack = AsyncExitStack()
    # Any: the two langgraph saver hierarchies (sqlite/postgres) share no
    # statically-visible async base with `setup` — the SDK boundary is dynamic.
    saver: Any
    if settings.DATABASE_URL.startswith("sqlite"):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        saver = await stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(_sqlite_path())
        )
    else:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        saver = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(_psycopg_uri())
        )
    await saver.setup()
    _checkpointer = saver
    _stack = stack
    return saver


async def aclose_checkpointer() -> None:
    """Release the process checkpointer (app shutdown)."""
    global _stack, _checkpointer
    if _stack is not None:
        try:
            await _stack.aclose()
        except Exception:  # noqa: BLE001 — shutdown must never raise
            logger.warning("Checkpointer close failed", exc_info=True)
    _stack = None
    _checkpointer = None


_GREGORIAN_100NS = 122192928000000000
_MS_PER_100NS = 10_000


def _stale_prefix(now_ms: int, ttl_days: int) -> str:
    cutoff_100ns = (now_ms - ttl_days * 86_400_000) * _MS_PER_100NS + _GREGORIAN_100NS
    return f"{cutoff_100ns >> 12:012x}"


def prune_checkpoints(
    db_path: Path, ttl_days: int, now_ms: Optional[int] = None
) -> int:
    """Delete desktop checkpoint threads whose latest write is older than the
    TTL (study's day-one retention beat — checkpoint rows grow unboundedly).

    Checkpoint ids are UUIDv6: the first 12 hex chars are the top 48 bits of
    the 100 ns Gregorian timestamp, so a zero-padded hex prefix compares
    lexicographically by time. Orphaned ``writes`` rows are dropped with the
    checkpoints. Returns removed checkpoint rows; no-op when the file does
    not exist. Server-mode Postgres pruning lands with the plan-98 Phase-4
    scheduler trigger.
    """
    import sqlite3

    if not db_path.exists():
        return 0
    prefix = _stale_prefix(
        now_ms if now_ms is not None else int(time.time() * 1000), ttl_days
    )
    connection = sqlite3.connect(db_path)
    try:
        stale = (
            "select thread_id || checkpoint_ns from checkpoints "
            "group by thread_id, checkpoint_ns "
            "having max(replace(checkpoint_id, '-', '')) < ?"
        )
        cursor = connection.execute(
            f"delete from checkpoints where thread_id || checkpoint_ns in ({stale})",
            (prefix,),
        )
        deleted = cursor.rowcount
        connection.execute(
            "delete from writes where not exists ("
            "select 1 from checkpoints c where c.thread_id = writes.thread_id "
            "and c.checkpoint_ns = writes.checkpoint_ns "
            "and c.checkpoint_id = writes.checkpoint_id)"
        )
        connection.commit()
        return deleted
    finally:
        connection.close()


def prune_desktop_checkpoints() -> int:
    """Boot-time prune of the desktop checkpoint DB (best-effort)."""
    path = _sqlite_path()
    if path == ":memory:":
        return 0
    try:
        return prune_checkpoints(Path(path), ttl_days=settings.CHECKPOINT_TTL_DAYS)
    except Exception:  # noqa: BLE001 — retention never blocks boot
        logger.warning("Checkpoint prune failed", exc_info=True)
        return 0


async def prune_postgres_checkpoints(db: AsyncSession, ttl_days: int) -> int:
    """Server-mode retention beat (plan 98 phase 4): delete LangGraph
    checkpoint threads whose latest write is older than the TTL — the same
    UUIDv6-prefix trick as the desktop prune, over the saver-owned tables
    in the product database. No-op on non-postgres dialects (the desktop
    prunes its SQLite file at boot instead). Returns removed thread rows.
    """
    from sqlalchemy import text

    if not settings.DATABASE_URL.startswith("postgresql"):
        return 0
    prefix = _stale_prefix(int(time.time() * 1000), ttl_days)
    stale = (
        "SELECT thread_id, checkpoint_ns FROM checkpoints "
        "GROUP BY thread_id, checkpoint_ns "
        "HAVING max(replace(checkpoint_id, '-', '')) < :prefix"
    )
    result = await db.execute(
        text(
            "WITH stale AS (" + stale + ") "
            "DELETE FROM checkpoints c USING stale s "
            "WHERE c.thread_id = s.thread_id AND c.checkpoint_ns = s.checkpoint_ns"
        ),
        {"prefix": prefix},
    )
    removed = result.rowcount or 0
    # Orphaned blobs/writes of pruned threads go with them (also sweeps
    # zero-checkpoint leftovers of never-resumed aborted runs).
    for table in ("checkpoint_blobs", "checkpoint_writes"):
        await db.execute(
            text(
                f"DELETE FROM {table} t WHERE NOT EXISTS ("
                "SELECT 1 FROM checkpoints c "
                "WHERE c.thread_id = t.thread_id "
                "AND c.checkpoint_ns = t.checkpoint_ns)"
            )
        )
    return removed
