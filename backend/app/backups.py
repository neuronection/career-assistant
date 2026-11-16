"""Local (desktop) backups: consistent SQLite snapshot + uploads + keys.

Backups are zips under `<data_dir>/backups/`:
    backup-YYYYMMDD-HHMMSS.zip
        manifest.json        {created_at, app_version, schema, contents}
                             `schema` is the Alembic head that wrote the
                             archive; a restore refuses a mismatched one
                             before anything is swapped
        career-assistant.db  consistent snapshot (VACUUM INTO)
        uploads/…            uploaded documents
        auth_keys.json       per-instance key family (identity-auth §8) —
                             without it a restore can decrypt nothing and
                             every session invalidates
        secret.key           pre-migration pre-P3d key (kept when present so
                             restored old snapshots can still drain their
                             JWT-derived ciphertext via migration 0044)
Retention keeps 14 daily and 8 weekly archives.
"""

import json
import logging
import re
import shutil
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

BACKUP_PATTERN = re.compile(r"^backup-(\d{8})-(\d{6})\.zip$")
KEEP_DAILY = 14
KEEP_WEEKLY = 8


def backups_dir(data_dir: Path) -> Path:
    path = data_dir / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _db_path() -> Path:
    """The SQLite file this instance uses (from the database profile)."""
    path = settings.sqlite_path
    if path is None:
        raise RuntimeError("Local backups require the SQLite database profile")
    return path


def _snapshot_db(db_path: Path, target: Path) -> None:
    """Consistent copy of a live SQLite database (WAL-safe)."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("VACUUM INTO ?", (str(target),))
    finally:
        connection.close()


def _require_local_storage() -> None:
    """Backups archive the local uploads tree; an object backend has none.

    Desktop-only by design: a cloud deployment relies on provider
    durability for document bytes and keeps database dumps (ADR-0057).
    """
    from app.storage.bootstrap import is_object_backend
    from app.storage.object_storage import UnsupportedOperation

    if is_object_backend():
        raise UnsupportedOperation(
            "Local backups are unavailable under an object-storage backend; "
            "document bytes live in the provider and the database dump remains the backup"
        )


def create_backup(data_dir: Path) -> Path:
    """Create one backup archive; returns its path."""
    from app.local import head_revision
    from app.storage.datastore_guard import database_state

    _require_local_storage()

    db_path = _db_path()
    if not db_path.is_file():
        raise RuntimeError(f"Database file not found: {db_path}")
    _, revision = database_state(f"sqlite+aiosqlite:///{db_path}")
    schema = revision or head_revision()

    created = datetime.now(UTC)
    out = backups_dir(data_dir) / (f"backup-{created.strftime('%Y%m%d-%H%M%S')}.zip")
    keys_file = data_dir / "auth_keys.json"
    secret = data_dir / "secret.key"
    contents = ["db", "uploads"]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        snapshot = data_dir / f".snapshot-{created.strftime('%Y%m%d-%H%M%S')}.db"
        try:
            _snapshot_db(db_path, snapshot)
            bundle.write(snapshot, arcname=db_path.name)
        finally:
            snapshot.unlink(missing_ok=True)
        uploads = data_dir / "uploads"
        if uploads.is_dir():
            for file_path in uploads.rglob("*"):
                if file_path.is_file() and "exports" not in file_path.parts:
                    bundle.write(file_path, arcname=str(file_path.relative_to(data_dir)))
        if keys_file.is_file():
            bundle.write(keys_file, arcname="auth_keys.json")
            contents.append("auth_keys.json")
        if secret.is_file():
            bundle.write(secret, arcname="secret.key")
            contents.append("secret.key")
        bundle.writestr(
            "manifest.json",
            json.dumps(
                {
                    "created_at": created.isoformat(),
                    "app_version": settings.version,
                    "schema": schema,
                    "contents": contents,
                },
                indent=2,
            ),
        )
    logger.info("Backup written: %s", out)
    return out


def _backup_timestamp(path: Path) -> datetime:
    match = BACKUP_PATTERN.match(path.name)
    if match is None:
        raise ValueError(path.name)
    return datetime.strptime(f"{match.group(1)}-{match.group(2)}", "%Y%m%d-%H%M%S")


def list_backups(data_dir: Path) -> list[Path]:
    return sorted(
        (p for p in backups_dir(data_dir).glob("backup-*.zip") if BACKUP_PATTERN.match(p.name)),
        key=_backup_timestamp,
    )


def prune_backups(data_dir: Path) -> int:
    """Keep the newest KEEP_DAILY daily and KEEP_WEEKLY weekly archives."""
    candidates = list_backups(data_dir)
    if len(candidates) <= KEEP_DAILY + KEEP_WEEKLY:
        return 0
    keep: set[Path] = set(candidates[-KEEP_DAILY:])
    week_buckets: dict[tuple[int, int], Path] = {}
    for path in candidates:
        stamp = _backup_timestamp(path)
        iso = stamp.isocalendar()
        bucket = (iso.year, iso.week)
        week_buckets[bucket] = path  # later entries overwrite → newest of week
    for path in week_buckets.values():
        keep.add(path)
    removed = 0
    for path in candidates:
        if path not in keep:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def backup_if_due(data_dir: Path) -> Path | None:
    """Back up when the newest archive is older than 24h (boot-time hook)."""
    existing = list_backups(data_dir)
    if existing:
        newest = _backup_timestamp(existing[-1])
        age_hours = (datetime.now(UTC) - newest.replace(tzinfo=UTC)).total_seconds() / 3600
        if age_hours < 24:
            return None
    try:
        archive = create_backup(data_dir)
        prune_backups(data_dir)
        return archive
    except Exception:
        logger.exception("Scheduled backup failed")
        return None


def _validate_sqlite(path: Path) -> bool:
    try:
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA schema_version").fetchone()
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            connection.close()
        return True
    except sqlite3.DatabaseError:
        return False


def _archive_schema(bundle: zipfile.ZipFile) -> str | None:
    """The schema revision an archive's manifest declares, when it has one."""
    try:
        manifest = json.loads(bundle.read("manifest.json"))
    except (KeyError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    schema = manifest.get("schema")
    return str(schema) if schema else None


def _assert_restorable(bundle: zipfile.ZipFile, candidate: Path) -> None:
    """Refuse an archive from a previous schema line before anything is swapped."""
    from app.local import known_revisions
    from app.storage.datastore_guard import PREVIOUS, UNREADABLE, database_state

    declared = _archive_schema(bundle)
    state, revision = database_state(f"sqlite+aiosqlite:///{candidate}")
    if state in (PREVIOUS, UNREADABLE) or (
        declared is not None and declared not in known_revisions()
    ):
        found = declared or revision
        detail = f"schema revision {found}" if found else "an unknown schema"
        raise RuntimeError(
            f"This backup uses {detail}, which this release cannot read. Backups made by "
            "another release cannot be restored; the live datastore was left untouched."
        )


def restore_backup(data_dir: Path, archive: Path) -> dict:
    """Replace the live db/uploads/keys with an archive's contents.

    The swapped-in database is migrated to head before this returns —
    restore is the declared D6 exception (reference-architecture §4): an
    ops action that migrates, exactly like study's restore API (audit F12).
    """
    _require_local_storage()
    restored = {"db": False, "uploads": 0, "keys": False, "secret": False}
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        db_path = _db_path()
        if db_path.name in names:
            staging = data_dir / ".restore-staging"
            staging.mkdir(exist_ok=True)
            try:
                bundle.extract(db_path.name, staging)
                candidate = staging / db_path.name
                if not _validate_sqlite(candidate):
                    raise RuntimeError("Backup contains a corrupt database")
                _assert_restorable(bundle, candidate)
                for suffix in ("-wal", "-shm"):
                    db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
                candidate.replace(db_path)
                restored["db"] = True
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        if "auth_keys.json" in names:
            bundle.extract("auth_keys.json", data_dir)
            restored["keys"] = True
        if "secret.key" in names:
            bundle.extract("secret.key", data_dir)
            restored["secret"] = True
        for name in names:
            if name.startswith("uploads/") and not name.endswith("/"):
                bundle.extract(name, data_dir)
                restored["uploads"] += 1
    if restored["db"]:
        # The one sanctioned runtime migration site (F12) — declared to
        # the C3 gate; every other migration stays entrypoint/CLI-owned.
        from app.local import run_migrations  # gate-allow: run_migrations (F12 restore)

        run_migrations()  # gate-allow: run_migrations (F12 restore)
    return restored
