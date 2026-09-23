"""pytest-xdist worker bootstrap: route and prepare a per-worker database.

``tests/__init__.py`` calls :func:`route_worker_database` at package import,
which happens BEFORE ``tests.conftest`` (and therefore before the app's
engines are created) — env-var routes reach ``app.core.config.settings``
on first import.

Why: concurrently running workers against the one ``career_test`` database
only reached ~2x throughput on 16 cores. Every SINGLE_USER_MODE test
lazily inserts the same default user inside its open transaction, and
Postgres serializes whole tests behind the lock waits on that unique key.
Routing each worker to its own database removes all cross-worker DB
contention and makes ``tests/test_migrations.py``'s real Alembic DDL
round-trips safe to distribute (they now mutate only the worker's own
schema). Under sqlite, each worker gets an isolated file in its own
directory — that also isolates the checkpointer's sibling
``checkpoints.db`` (``app/ai/checkpointer.py`` derives it from the DB's
parent directory).
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_XDIST_ROOT = "tests/_xdist"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _migrate_worker_db() -> None:
    """Bring the worker database to head in-process (idempotent at head)."""
    from alembic import command
    from alembic.config import Config

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "alembic"),
    )
    command.upgrade(config, "head")


def _create_postgres_database(worker_url: str) -> None:
    """CREATE DATABASE when this worker's copy doesn't exist yet."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    parts = urlsplit(worker_url)
    name = parts.path.lstrip("/")
    admin = urlunsplit((parts.scheme, parts.netloc, "/postgres", "", ""))

    async def _create() -> None:
        engine = create_async_engine(admin, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
                exists = (
                    await conn.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :name"),
                        {"name": name},
                    )
                ).scalar()
                if not exists:
                    safe_name = name.replace('"', '""')
                    await conn.execute(text(f'CREATE DATABASE "{safe_name}"'))
        finally:
            await engine.dispose()

    asyncio.run(_create())


def route_worker_database() -> None:
    """Point this process at its own database copy (xdist workers only).

    The worker id comes from ``PYTEST_XDIST_WORKER`` (set by pytest-xdist
    before the conftest is imported), so serial runs and the xdist
    controller are no-ops and keep the original ``DATABASE_URL``.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    base = os.environ.get("DATABASE_URL")
    if not worker or not base:
        return
    if "app.core.config" in sys.modules:
        raise RuntimeError(
            "xdist worker DB routing ran after app.core.config was imported — "
            "settings are already cached, so workers would share one database. "
            "Route in tests/__init__.py before any app import."
        )
    if base.startswith("sqlite"):
        scheme, _, rest = base.partition("://")
        file_part = rest.split("?", 1)[0]
        if file_part in ("", ":memory:"):
            return
        worker_root = _BACKEND_ROOT / _XDIST_ROOT / worker
        worker_root.mkdir(parents=True, exist_ok=True)
        os.environ["DATABASE_URL"] = f"{scheme}:///{worker_root / Path(file_part).name}"
    else:
        parts = urlsplit(base)
        last = parts.path.rpartition("/")[2]
        if not last or last == ":memory:":
            return
        parent = parts.path.rpartition("/")[0]
        worker_url = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                f"{parent}/{last}_{worker}",
                parts.query,
                "",
            )
        )
        _create_postgres_database(worker_url)
        os.environ["DATABASE_URL"] = worker_url
    _migrate_worker_db()
