"""LangGraph checkpointer: app-lifespan-owned persistence.

Server mode checkpoints into Postgres (AsyncPostgresSaver), the desktop
profile into SQLite (AsyncSqliteSaver); tests pass an ``InMemorySaver``
explicitly. The saver is created lazily on first use and ``setup()``
runs once; ``aclose_checkpointer()`` releases it at shutdown.
``thread_id`` is the autopilot run id, so interrupted runs
continue from the last checkpoint instead of restarting.
"""

import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver

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
