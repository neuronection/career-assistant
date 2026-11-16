"""Datastore break guard (family contract: datastore-breaks.md).

The v0.17 baseline cannot read a pre-v0.17 datastore. The desktop boot moves
the old datastore aside atomically, starts fresh and leaves a marker the SPA
renders as a one-time notice; the server preflight refuses with operator
guidance. Nothing is migrated, deleted or silently re-created beside the old
database.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from nx_auth.instance import IdentityMode

from app.core.config import Settings, settings
from app.local import DatabaseVersionError, head_revision, run_migrations
from app.storage.datastore_guard import (
    DatastoreQuarantineError,
    guard_datastore,
    read_marker,
)
from tests.conftest import auth_kit
from tests.settings_factory import settings_from_env_file

LEGACY_REVISION = "0100_previous_line"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _local_settings(tmp_path: Path, db_name: str = "career-assistant.db") -> Settings:
    return settings_from_env_file(
        None,
        data_dir=tmp_path,
        config_dir=tmp_path / "config",
        database_url=f"sqlite+aiosqlite:///{tmp_path / db_name}",
        upload_dir=str(tmp_path / "uploads"),
        app_env="test",
        identity_mode=IdentityMode.DESKTOP,
    )


def _legacy_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (LEGACY_REVISION,))
        connection.execute("CREATE TABLE previous_profile (id VARCHAR(32) PRIMARY KEY)")
        connection.execute("INSERT INTO previous_profile VALUES ('old-profile')")
        connection.commit()
    finally:
        connection.close()


def _use_database(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}")


def _revision(db_path: Path) -> str | None:
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        connection.close()
    return str(row[0]) if row else None


def test_legacy_datastore_is_quarantined_and_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local_settings(tmp_path)
    db_path = tmp_path / "career-assistant.db"
    _legacy_db(db_path)
    for sidecar in ("-wal", "-shm"):
        db_path.with_name(db_path.name + sidecar).write_bytes(b"sidecar")
    (tmp_path / "checkpoints.db").write_bytes(b"checkpoints")
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "cv.pdf").write_bytes(b"pdf")
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / "backup-20260101-000000.zip").write_bytes(b"archive")
    (tmp_path / "auth_keys.json").write_text("{}", encoding="utf-8")
    (tmp_path / "env").write_text("CAREER_SOMETHING=1\n", encoding="utf-8")

    notice = guard_datastore(local)

    assert notice is not None
    folder = Path(notice.path)
    assert folder.is_dir()
    assert folder.name.startswith("previous-datastore-")
    assert not db_path.exists()
    assert (folder / db_path.name).is_file()
    assert (folder / "checkpoints.db").is_file()
    assert (folder / "uploads" / "cv.pdf").is_file()
    assert (folder / "backups" / "backup-20260101-000000.zip").is_file()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "nx-datastore-quarantine/v1"
    assert manifest["product"] == "career-assistant"
    assert manifest["reason"] == "incompatible-schema"
    assert manifest["schema_revision"] == LEGACY_REVISION
    assert "career-assistant.db" in manifest["items"]
    assert "uploads" in manifest["items"]
    assert read_marker(tmp_path) == notice.as_dict()
    # Schema-bound state moves; config and keys stay with the instance.
    assert (tmp_path / "auth_keys.json").is_file()
    assert (tmp_path / "env").is_file()

    _use_database(monkeypatch, db_path)
    run_migrations()
    assert _revision(db_path) == head_revision()
    connection = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()
    assert "previous_profile" not in tables


def test_current_datastore_is_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    local = _local_settings(tmp_path)
    db_path = tmp_path / "career-assistant.db"
    _use_database(monkeypatch, db_path)
    run_migrations()
    before = db_path.read_bytes()

    assert guard_datastore(local) is None
    assert db_path.read_bytes() == before
    assert read_marker(tmp_path) is None


def test_fresh_install_needs_no_quarantine(tmp_path: Path) -> None:
    local = _local_settings(tmp_path)
    assert guard_datastore(local) is None
    assert read_marker(tmp_path) is None
    assert not list(tmp_path.glob("previous-datastore-*"))


def test_unreadable_datastore_is_preserved_not_deleted(tmp_path: Path) -> None:
    local = _local_settings(tmp_path)
    db_path = tmp_path / "career-assistant.db"
    db_path.write_bytes(b"this is not a sqlite database")

    notice = guard_datastore(local)

    assert notice is not None
    assert notice.reason == "unreadable"
    assert notice.schema_revision is None
    assert (Path(notice.path) / db_path.name).read_bytes() == b"this is not a sqlite database"
    assert not db_path.exists()


def test_quarantine_failure_keeps_the_old_datastore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local_settings(tmp_path)
    db_path = tmp_path / "career-assistant.db"
    _legacy_db(db_path)
    before = db_path.read_bytes()

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("locked")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(DatastoreQuarantineError, match="could not be moved aside"):
        guard_datastore(local)
    assert db_path.read_bytes() == before
    assert read_marker(tmp_path) is None
    assert not list(tmp_path.glob("previous-datastore-*"))


def test_null_schema_stamp_is_quarantined(tmp_path: Path) -> None:
    local = _local_settings(tmp_path)
    db_path = tmp_path / "career-assistant.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (NULL)")
        connection.commit()
    finally:
        connection.close()

    notice = guard_datastore(local)

    assert notice is not None
    assert notice.reason == "incompatible-schema"
    assert notice.schema_revision is None
    assert not db_path.exists()


def test_quarantine_refuses_while_another_instance_owns_the_datastore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local_settings(tmp_path)
    db_path = tmp_path / "career-assistant.db"
    _legacy_db(db_path)
    before = db_path.read_bytes()
    monkeypatch.setattr("app.desktop.single_instance.focus_existing_instance", lambda *_: True)

    with pytest.raises(DatastoreQuarantineError, match="Another Career Assistant instance"):
        guard_datastore(local)
    assert db_path.read_bytes() == before
    assert read_marker(tmp_path) is None


def test_entrypoint_seed_quarantines_an_old_datastore(tmp_path: Path) -> None:
    """The real `careerassistant` boot path over a pre-v0.17 data dir."""
    db_path = tmp_path / "career-assistant.db"
    _legacy_db(db_path)
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "cv.pdf").write_bytes(b"pdf")
    (tmp_path / "auth_keys.json").write_text("{}", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("CAREER_")}
    env.update(
        {
            "CAREER_APP_ENV": "test",
            "CAREER_DATA_DIR": str(tmp_path),
            "CAREER_CONFIG_DIR": str(tmp_path / "config"),
            "CAREER_ENV_FILE": str(tmp_path / "env"),
            "CAREER_SKIP_SEED": "1",
        }
    )

    result = subprocess.run(
        [sys.executable, "-m", "careerassistant", "seed"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    folders = list(tmp_path.glob("previous-datastore-*"))
    assert len(folders) == 1
    assert (folders[0] / db_path.name).is_file()
    assert (folders[0] / "uploads" / "cv.pdf").is_file()
    assert (folders[0] / "manifest.json").is_file()
    assert read_marker(tmp_path) is not None
    assert _revision(db_path) == head_revision()
    assert (tmp_path / "auth_keys.json").is_file()


def test_postgres_datastores_are_left_to_the_operator(tmp_path: Path) -> None:
    local = settings_from_env_file(
        None,
        data_dir=tmp_path,
        config_dir=tmp_path / "config",
        database_url="postgresql+asyncpg://user:pass@localhost:5432/career",
        app_env="test",
    )
    assert guard_datastore(local) is None


def test_run_migrations_refuses_a_previous_release_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "career-assistant.db"
    _legacy_db(db_path)
    _use_database(monkeypatch, db_path)

    with pytest.raises(DatabaseVersionError, match=LEGACY_REVISION):
        run_migrations()
    assert _revision(db_path) == LEGACY_REVISION


def test_preflight_mode_reports_the_datastore_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import careerassistant.__main__ as entry

    db_path = tmp_path / "career-assistant.db"
    _legacy_db(db_path)
    _use_database(monkeypatch, db_path)
    assert entry.main(["preflight"]) == 1
    assert "cannot read" in capsys.readouterr().err

    _use_database(monkeypatch, tmp_path / "fresh.db")
    assert entry.main(["preflight"]) == 0


async def test_instance_config_exposes_the_marker_on_desktop(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local_settings(tmp_path)
    _legacy_db(tmp_path / "career-assistant.db")
    notice = guard_datastore(local)
    assert notice is not None
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    kit = auth_kit()
    monkeypatch.setattr(kit, "config", replace(kit.config, identity_mode=IdentityMode.DESKTOP))

    response = await client.get("/api/v1/instance/config")

    assert response.status_code == 200
    assert response.json()["datastore_quarantine"] == {
        "path": notice.path,
        "reason": "incompatible-schema",
        "quarantined_at": notice.quarantined_at,
        "schema_revision": LEGACY_REVISION,
        "from_version": None,
    }


async def test_instance_config_hides_the_marker_in_server_mode(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local_settings(tmp_path)
    _legacy_db(tmp_path / "career-assistant.db")
    assert guard_datastore(local) is not None
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    response = await client.get("/api/v1/instance/config")

    assert response.json()["datastore_quarantine"] is None
    assert response.json()["identity_mode"] == "server"


async def test_instance_config_survives_a_malformed_marker(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "datastore-quarantine.json").write_text(
        '{"format": "nx-datastore-quarantine/v1", "path": null}', encoding="utf-8"
    )
    kit = auth_kit()
    monkeypatch.setattr(kit, "config", replace(kit.config, identity_mode=IdentityMode.DESKTOP))

    response = await client.get("/api/v1/instance/config")

    assert response.status_code == 200
    assert response.json()["datastore_quarantine"] is None
    assert read_marker(tmp_path) is None
