"""pytest-xdist worker bootstrap: route and prepare a per-worker database.

``tests/__init__.py`` calls :func:`route_worker_database` at package import,
which happens BEFORE ``tests.conftest`` (and therefore before the app's
engines are created) — env-var routes reach ``app.core.config.settings``
on first import.

Why: concurrently running workers against the one ``neuronection_career_test`` database
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

A worker owns more than its database: extension/import/preview/mail state
lives under ``CAREER_DATA_DIR`` and document uploads under
``CAREER_UPLOAD_DIR``, both shared trees by default. Routing also points
those two settings at ``<worker root>/data`` and ``<worker root>/uploads``
so everything mutable a worker writes is process-private.
"""

import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_XDIST_ROOT = "tests/_xdist"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]

_worker_root: Path | None = None


def worker_root_for(worker: str) -> Path:
    """The state directory the given xdist worker owns."""
    return _BACKEND_ROOT / _XDIST_ROOT / worker


def routed_worker_root() -> Path | None:
    """The worker root this process was routed to, or ``None`` when it was not routed.

    Serial runs, the xdist controller, a missing ``CAREER_DATABASE_URL`` and
    in-memory databases never reach the routing below, so consumers can use
    this to tell "routed worker" from "not routed" instead of re-deriving the
    preconditions.
    """
    return _worker_root


def _migrate_worker_db() -> None:
    """Bring the worker database to head in-process (idempotent at head)."""
    from alembic.config import Config

    from alembic import command

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


def _worker_sqlite_url(base_url: str, worker_root: Path) -> str | None:
    """This worker's SQLite URL inside its own directory, ``None`` for memory databases."""
    scheme, _, rest = base_url.partition("://")
    file_part = rest.split("?", 1)[0].lstrip("/")
    if file_part in ("", ":memory:"):
        return None
    return f"{scheme}:///{worker_root / Path(file_part).name}"


def _worker_postgres_url(base_url: str, worker: str) -> str | None:
    """This worker's own copy of the base Postgres database, ``None`` without a name."""
    parts = urlsplit(base_url)
    last = parts.path.rpartition("/")[2]
    if not last or last == ":memory:":
        return None
    parent = parts.path.rpartition("/")[0]
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            f"{parent}/{last}_{worker}",
            parts.query,
            "",
        )
    )


def _route_worker_state(worker_root: Path) -> None:
    """Point ``CAREER_DATA_DIR``/``CAREER_UPLOAD_DIR`` at this worker's own trees.

    The job/import/preview/mail state and the upload store are shared trees
    by default, so every routed worker gets its own copies. Cleanup is
    worker-scoped by construction: only ``<worker_root>/data`` and
    ``<worker_root>/uploads`` are recreated, never anything else in
    ``tests/_xdist`` — every worker runs this at import, so a wider delete
    would remove a peer's live database.
    """
    data_dir = worker_root / "data"
    upload_dir = worker_root / "uploads"
    for path in (data_dir, upload_dir):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)
    os.environ["CAREER_DATA_DIR"] = str(data_dir)
    os.environ["CAREER_UPLOAD_DIR"] = str(upload_dir)


def route_worker_database() -> None:
    """Point this process at its own database and state trees (xdist workers only).

    The worker id comes from ``PYTEST_XDIST_WORKER`` (set by pytest-xdist
    before the conftest is imported), so serial runs and the xdist
    controller are no-ops and keep the original ``CAREER_DATABASE_URL``.
    """
    global _worker_root
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    base = os.environ.get("CAREER_DATABASE_URL")
    if not worker or not base:
        return
    worker_root = worker_root_for(worker)
    if base.startswith("sqlite"):
        worker_url = _worker_sqlite_url(base, worker_root)
    else:
        worker_url = _worker_postgres_url(base, worker)
    if worker_url is None:
        return
    if "app.core.config" in sys.modules:
        raise RuntimeError(
            "xdist worker DB routing ran after app.core.config was imported — "
            "settings are already cached, so workers would share one database. "
            "Route in tests/__init__.py before any app import."
        )
    if not base.startswith("sqlite"):
        _create_postgres_database(worker_url)
    _route_worker_state(worker_root)
    os.environ["CAREER_DATABASE_URL"] = worker_url
    _worker_root = worker_root
    _migrate_worker_db()
