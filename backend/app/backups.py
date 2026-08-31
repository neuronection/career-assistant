"""Local (desktop) backups: consistent SQLite snapshot + uploads + secret.

Backups are zips under `<data_dir>/backups/`:
    backup-YYYYMMDD-HHMMSS.zip
        manifest.json        {created_at, app_version, contents}
        career-assistant.db  consistent snapshot (VACUUM INTO)
        uploads/…            uploaded documents
        secret.key           required to decrypt stored AI keys
Retention keeps 14 daily and 8 weekly archives.
"""

import json
import logging
import re
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
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


def _db_path(data_dir: Path) -> Path:
    """The SQLite file this instance uses (parsed from DATABASE_URL)."""
    url = settings.DATABASE_URL
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        raise RuntimeError("Local backups require the SQLite database profile")
    return Path(url[len(prefix) :])


def _snapshot_db(db_path: Path, target: Path) -> None:
    """Consistent copy of a live SQLite database (WAL-safe)."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("VACUUM INTO ?", (str(target),))
    finally:
        connection.close()


def create_backup(data_dir: Path) -> Path:
    """Create one backup archive; returns its path."""
    db_path = _db_path(data_dir)
    if not db_path.is_file():
        raise RuntimeError(f"Database file not found: {db_path}")

    created = datetime.now(timezone.utc)
    out = backups_dir(data_dir) / (f"backup-{created.strftime('%Y%m%d-%H%M%S')}.zip")
    secret = data_dir / "secret.key"
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
                    bundle.write(
                        file_path, arcname=str(file_path.relative_to(data_dir))
                    )
        if secret.is_file():
            bundle.write(secret, arcname="secret.key")
        bundle.writestr(
            "manifest.json",
            json.dumps(
                {
                    "created_at": created.isoformat(),
                    "app_version": settings.VERSION,
                    "contents": ["db", "uploads", "secret.key"],
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
        (
            p
            for p in backups_dir(data_dir).glob("backup-*.zip")
            if BACKUP_PATTERN.match(p.name)
        ),
        key=_backup_timestamp,
    )


def prune_backups(data_dir: Path) -> int:
    """Keep the newest KEEP_DAILY daily and KEEP_WEEKLY weekly archives."""
    candidates = list_backups(data_dir)
    if len(candidates) <= KEEP_DAILY + KEEP_WEEKLY:
        return 0
    keep: set[Path] = set(candidates[-KEEP_DAILY:])
    week_buckets: dict[int, Path] = {}
    for path in candidates:
        stamp = _backup_timestamp(path)
        bucket = stamp.isocalendar()[:2]
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
        age_hours = (
            datetime.now(timezone.utc) - newest.replace(tzinfo=timezone.utc)
        ).total_seconds() / 3600
        if age_hours < 24:
            return None
    try:
        archive = create_backup(data_dir)
        prune_backups(data_dir)
        return archive
    except Exception:  # noqa: BLE001 — backups must never block startup
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


def verify_or_repair_database(data_dir: Path) -> str:
    """Quarantine a corrupt DB and restore the newest backup's snapshot.

    Returns one of: "ok", "repaired", "quarantined".
    """
    db_path = _db_path(data_dir)
    if not db_path.is_file() or _validate_sqlite(db_path):
        return "ok"

    quarantine = db_path.with_name(
        f"corrupt-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.db"
    )
    db_path.replace(quarantine)
    logger.error("Database corrupt; quarantined as %s", quarantine.name)

    for archive in reversed(list_backups(data_dir)):
        with zipfile.ZipFile(archive) as bundle:
            if db_path.name not in bundle.namelist():
                continue
            bundle.extract(db_path.name, data_dir)
            extracted = data_dir / db_path.name
            if _validate_sqlite(extracted):
                extracted.replace(db_path)
                logger.warning("Restored database from %s", archive.name)
                return "repaired"
            extracted.unlink(missing_ok=True)
    return "quarantined"


def restore_backup(data_dir: Path, archive: Path) -> dict:
    """Replace the live db/uploads/secret with an archive's contents."""
    restored = {"db": False, "uploads": 0, "secret": False}
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        db_path = _db_path(data_dir)
        if db_path.name in names:
            staging = data_dir / ".restore-staging"
            staging.mkdir(exist_ok=True)
            try:
                bundle.extract(db_path.name, staging)
                candidate = staging / db_path.name
                if not _validate_sqlite(candidate):
                    raise RuntimeError("Backup contains a corrupt database")
                for suffix in ("-wal", "-shm"):
                    db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
                candidate.replace(db_path)
                restored["db"] = True
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        if "secret.key" in names:
            bundle.extract("secret.key", data_dir)
            restored["secret"] = True
        for name in names:
            if name.startswith("uploads/") and not name.endswith("/"):
                bundle.extract(name, data_dir)
                restored["uploads"] += 1
    return restored
