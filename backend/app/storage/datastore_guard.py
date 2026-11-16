"""One-time datastore break gate (family contract: datastore-breaks.md).

The v0.17 baseline cannot read a pre-v0.17 datastore. Rather than migrate,
delete or keep a previous reader, the first boot of this line moves the old
datastore aside atomically, starts fresh and leaves a marker the SPA renders
as a one-time notice. PostgreSQL (web / self-host) has no file to move: it is
preflighted with operator guidance at the entrypoint instead.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.local import DatabaseVersionError, incompatible_message, known_revisions

logger = logging.getLogger(__name__)

CONTRACT_FORMAT = "nx-datastore-quarantine/v1"
PRODUCT = "career-assistant"
FOLDER_PREFIX = "previous-datastore-"
MANIFEST_NAME = "manifest.json"
MARKER_NAME = "datastore-quarantine.json"

FRESH = "fresh"
CURRENT = "current"
PREVIOUS = "previous"
UNREADABLE = "unreadable"

REASON_SCHEMA = "incompatible-schema"
REASON_UNREADABLE = "unreadable"


class DatastoreQuarantineError(RuntimeError):
    """The old datastore could not be moved aside; refuse rather than risk it."""


@dataclass(frozen=True)
class QuarantineNotice:
    """The marker payload: what was moved, why, and where it went."""

    path: str
    reason: str
    quarantined_at: str
    schema_revision: str | None = None
    from_version: str | None = None
    items: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": CONTRACT_FORMAT,
            "product": PRODUCT,
            "path": self.path,
            "reason": self.reason,
            "quarantined_at": self.quarantined_at,
            "schema_revision": self.schema_revision,
            "from_version": self.from_version,
            "items": list(self.items),
        }


def _sqlite_file(url: str) -> Path | None:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            raw = url[len(prefix) :].split("?", 1)[0]
            if not raw or raw == ":memory:":
                return None
            return Path(raw)
    return None


def _sync_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + url.split("://", 1)[1]
    return url


def _probe_sqlite(db_path: Path) -> tuple[str, str | None]:
    try:
        if not db_path.exists() or db_path.stat().st_size == 0:
            return FRESH, None
    except OSError:
        return UNREADABLE, None
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.DatabaseError:
        return UNREADABLE, None
    try:
        try:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.DatabaseError:
            row = None
        revision = str(row[0]) if row and row[0] is not None else None
        if revision is not None:
            return (CURRENT if revision in known_revisions() else PREVIOUS), revision
        tables = [
            str(entry[0])
            for entry in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return (PREVIOUS if tables else FRESH), None
    except sqlite3.DatabaseError:
        return UNREADABLE, None
    finally:
        connection.close()


def _probe_server(url: str) -> tuple[str, str | None]:
    """Classify a server datastore. Connection failures propagate as-is."""
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(_sync_url(url))
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            revision = None
            if inspector.has_table("alembic_version"):
                row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
                revision = str(row[0]) if row and row[0] is not None else None
            if revision is not None:
                return (CURRENT if revision in known_revisions() else PREVIOUS), revision
            tables = [name for name in inspector.get_table_names() if name != "alembic_version"]
            return (PREVIOUS if tables else FRESH), None
    finally:
        engine.dispose()


def database_state(url: str | None = None) -> tuple[str, str | None]:
    """Classify the datastore behind `url` without mutating it.

    Returns `(state, revision)` where state is `fresh`, `current`,
    `previous` or `unreadable`. Connection failures that are not a database
    error (unreachable host, bad credentials) propagate — they are an
    operator problem with their own message.
    """
    if url is None:
        from app.core.config import settings

        url = settings.database_url
    path = _sqlite_file(url)
    if path is not None:
        return _probe_sqlite(path)
    return _probe_server(url)


def assert_compatible_database(url: str | None = None) -> None:
    """Refuse a datastore this release cannot read, before anything opens it."""
    state, revision = database_state(url)
    if state == PREVIOUS:
        raise DatabaseVersionError(incompatible_message(revision))
    if state == UNREADABLE:
        raise DatabaseVersionError(
            "The datastore could not be read as a database. Nothing was changed.\n"
            "Restore a backup or start from a fresh data directory."
        )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _database_items(db_path: Path) -> list[Path]:
    checkpoints = db_path.parent / "checkpoints.db"
    return [
        item
        for database in (db_path, checkpoints)
        for item in (
            database,
            database.with_name(database.name + "-wal"),
            database.with_name(database.name + "-shm"),
        )
    ]


def _content_items(settings: Settings) -> list[Path]:
    items = [settings.data_dir / "backups"]
    from app.storage.bootstrap import is_object_backend

    if not is_object_backend(settings):
        uploads = settings.upload_path
        if not uploads.is_absolute():
            uploads = settings.data_dir / uploads
        items.insert(0, uploads)
    return items


def _another_instance_alive(data_dir: Path) -> bool:
    """A live desktop instance owns the datastore socket (never move under it)."""
    try:
        from app.desktop.single_instance import focus_existing_instance

        return focus_existing_instance(data_dir)
    except (OSError, AttributeError):
        return False


def quarantine(
    settings: Settings,
    *,
    reason: str,
    schema_revision: str | None,
) -> QuarantineNotice:
    """Move the old datastore aside (atomic rename) and mark the new boot."""
    data_dir = settings.data_dir
    db_path = settings.sqlite_path
    if db_path is None:
        raise DatastoreQuarantineError("Quarantine applies to the SQLite profile only.")
    if _another_instance_alive(data_dir):
        raise DatastoreQuarantineError(
            "Another Career Assistant instance is running and owns this datastore. "
            "Quit it from the tray, then relaunch."
        )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    folder = data_dir / f"{FOLDER_PREFIX}{stamp}"
    suffix = 1
    while folder.exists():
        folder = data_dir / f"{FOLDER_PREFIX}{stamp}-{suffix}"
        suffix += 1
    sources = _database_items(db_path) + _content_items(settings)
    sources = [source for source in sources if source.exists()]
    folder.mkdir(parents=True)
    moved: list[Path] = []
    try:
        for source in sources:
            os.replace(source, folder / source.name)
            moved.append(source)
    except OSError as error:
        for source in reversed(moved):
            with contextlib.suppress(OSError):
                os.replace(folder / source.name, source)
        with contextlib.suppress(OSError):
            folder.rmdir()
        raise DatastoreQuarantineError(
            "The previous datastore could not be moved aside. Close any other "
            f"Career Assistant instance, check permissions for {data_dir}, keep "
            "the data, uploads and backups folders on one volume, then relaunch. "
            f"({error})"
        ) from error
    quarantined_at = datetime.now(UTC).isoformat()
    notice = QuarantineNotice(
        path=str(folder),
        reason=reason,
        quarantined_at=quarantined_at,
        schema_revision=schema_revision,
        items=tuple(sorted(path.name for path in moved)),
    )
    payload = notice.as_dict()
    _write_json(folder / MANIFEST_NAME, payload)
    _write_json(data_dir / MARKER_NAME, payload)
    logger.warning("Datastore quarantined (%s) at %s", reason, folder)
    return notice


def guard_datastore(settings: Settings) -> QuarantineNotice | None:
    """Quarantine a pre-v0.17 SQLite datastore; PostgreSQL is ops-owned."""
    db_path = settings.sqlite_path
    if db_path is None:
        return None
    state, revision = _probe_sqlite(db_path)
    if state in (FRESH, CURRENT):
        return None
    return quarantine(
        settings,
        reason=REASON_UNREADABLE if state == UNREADABLE else REASON_SCHEMA,
        schema_revision=revision,
    )


def read_marker(data_dir: Path) -> dict[str, Any] | None:
    """The pending quarantine marker, if this boot moved a datastore aside.

    A malformed or partial marker reads as absent: the public instance
    config (read before login) must never fail because a marker write was
    cut short.
    """
    try:
        payload = json.loads((data_dir / MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("format") != CONTRACT_FORMAT:
        return None
    for field in ("path", "reason", "quarantined_at"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            return None
    for field in ("schema_revision", "from_version"):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            payload[field] = str(value)
    return payload
