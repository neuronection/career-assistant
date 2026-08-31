"""Data portability: export zip, account deletion, download, desktop backups."""

import io
import sqlite3
import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.user_model import Profile, User


async def _register(client: AsyncClient, email: str) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret1", "full_name": "T"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_export_job_produces_downloadable_zip(client, db, auth_headers):
    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "s1"}, headers=auth_headers
        )
    ).json()
    sent = await client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        json={"content": "hello"},
        headers=auth_headers,
    )
    assert sent.status_code == 200, sent.text

    response = await client.post("/api/v1/me/export", headers=auth_headers)
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    from app.services.job_worker import JobWorker

    worker = JobWorker(db)
    while await worker.run_once():
        pass

    detail = await client.get(f"/api/v1/background-jobs/{job_id}", headers=auth_headers)
    body = detail.json()
    assert body["status"] == "succeeded", body.get("error")
    assert body["result"]["size_bytes"] > 0

    download = await client.get(
        f"/api/v1/background-jobs/{job_id}/download", headers=auth_headers
    )
    assert download.status_code == 200
    assert "application/zip" in download.headers["content-type"]
    assert "attachment" in download.headers["content-disposition"]

    bundle = zipfile.ZipFile(io.BytesIO(download.content))
    names = bundle.namelist()
    for expected in (
        "manifest.json",
        "profile.json",
        "match_insights.json",
        "chat_sessions.json",
        "documents.json",
    ):
        assert expected in names
    manifest = __import__("json").loads(bundle.read("manifest.json"))
    assert manifest["schema_version"] == 1
    sessions = __import__("json").loads(bundle.read("chat_sessions.json"))
    assert sessions[0]["title"] == "s1"
    assert sessions[0]["messages"]


async def test_export_download_is_private(client, db, auth_headers):
    other = await _register(client, "exporter2@example.com")
    response = await client.post("/api/v1/me/export", headers=other)
    job_id = response.json()["job_id"]

    from app.services.job_worker import JobWorker

    worker = JobWorker(db)
    while await worker.run_once():
        pass

    stolen = await client.get(
        f"/api/v1/background-jobs/{job_id}/download", headers=auth_headers
    )
    assert stolen.status_code == 404


async def test_delete_account_cascades_and_requires_password(client, db):
    headers = await _register(client, "deleteme@example.com")
    user = (
        (await db.execute(select(User).where(User.email == "deleteme@example.com")))
        .scalars()
        .first()
    )
    user_id = user.id

    wrong = await client.request(
        "DELETE", "/api/v1/me", json={"password": "not-it"}, headers=headers
    )
    assert wrong.status_code == 400

    ok = await client.request(
        "DELETE", "/api/v1/me", json={"password": "supersecret1"}, headers=headers
    )
    assert ok.status_code == 204

    db.expire_all()
    assert (await db.get(User, user_id)) is None
    assert (
        await db.execute(select(Profile).where(Profile.user_id == user_id))
    ).scalars().first() is None
    me_again = await client.get("/api/v1/auth/me", headers=headers)
    assert me_again.status_code == 401


async def test_last_admin_cannot_self_delete(client, db, auth_headers):
    # auth_headers fixture registers the first user → becomes admin.
    await _register(client, "second@example.com")
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert me["is_admin"] is True

    denied = await client.request(
        "DELETE", "/api/v1/me", json={"password": "supersecret1"}, headers=auth_headers
    )
    assert denied.status_code == 400
    assert "last admin" in denied.json()["detail"]


async def test_sole_user_can_delete_account(client, db):
    headers = await _register(client, "lonely@example.com")
    ok = await client.request(
        "DELETE", "/api/v1/me", json={"password": "supersecret1"}, headers=headers
    )
    assert ok.status_code == 204


def test_desktop_backup_roundtrip(tmp_path, monkeypatch):
    from app import backups
    from app.core.config import settings

    data_dir = tmp_path
    db_path = data_dir / "app.db"
    import sqlite3

    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE t (x TEXT)")
    connection.execute("INSERT INTO t VALUES ('hello')")
    connection.commit()
    connection.close()
    (data_dir / "uploads").mkdir()
    (data_dir / "uploads" / "doc.txt").write_text("document")
    (data_dir / "secret.key").write_text("s3cret")

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    archive = backups.create_backup(data_dir)
    assert archive.is_file()
    assert backups.prune_backups(data_dir) == 0

    connection = sqlite3.connect(db_path)
    connection.execute("DROP TABLE t")
    connection.commit()
    connection.close()

    summary = backups.restore_backup(data_dir, archive)
    assert summary["db"] is True and summary["secret"] is True
    connection = sqlite3.connect(db_path)
    rows = connection.execute("SELECT x FROM t").fetchall()
    connection.close()
    assert rows == [("hello",)]


def test_backup_prune_keeps_daily_and_weekly(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    from app import backups

    stamps = [datetime(2026, 8, 1) + timedelta(hours=6 * i) for i in range(60)]
    for index, stamp in enumerate(stamps):
        path = backups.backups_dir(tmp_path) / (
            f"backup-{stamp.strftime('%Y%m%d-%H%M%S')}.zip"
        )
        path.write_bytes(b"")
    assert len(backups.list_backups(tmp_path)) == 60

    removed = backups.prune_backups(tmp_path)
    remaining = backups.list_backups(tmp_path)
    assert removed > 0
    assert len(remaining) <= backups.KEEP_DAILY + backups.KEEP_WEEKLY
    assert remaining[-1] == max(remaining, key=lambda p: p.name)


def test_corrupt_db_is_quarantined_and_repaired(tmp_path, monkeypatch):
    from app import backups
    from app.core.config import settings
    import sqlite3

    data_dir = tmp_path
    db_path = data_dir / "app.db"
    (data_dir / "backups").mkdir()

    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE t (x TEXT)")
    connection.execute("INSERT INTO t VALUES ('keep')")
    connection.commit()
    connection.close()
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    archive = backups.create_backup(data_dir)

    db_path.write_bytes(b"this is not a database at all")
    assert backups._validate_sqlite(db_path) is False

    result = backups.verify_or_repair_database(data_dir)
    assert result == "repaired"
    assert backups._validate_sqlite(db_path) is True
    assert list((data_dir / "backups").glob("backup-*.zip")) == [archive]
    quarantined = list(data_dir.glob("corrupt-*.db"))
    assert len(quarantined) == 1


def test_restore_rejects_corrupt_archive_and_leaves_live_db(tmp_path, monkeypatch):
    from app import backups
    from app.core.config import settings

    data_dir = tmp_path
    db_path = data_dir / "app.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE t (x TEXT)")
    connection.commit()
    connection.close()
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    archive = data_dir / "backup-bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("app.db", b"this is not a database")
        bundle.writestr("uploads/doc.txt", "doc")

    with pytest.raises(RuntimeError, match="corrupt"):
        backups.restore_backup(data_dir, archive)
    assert not (data_dir / ".restore-staging").exists()

    connection = sqlite3.connect(db_path)
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    connection.close()
    assert ("t",) in tables
