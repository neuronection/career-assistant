"""migrate-objects for career: DB-driven document/page/export mapping.

Local test database, local target store, no credentials. Verifies the
dry-run/apply/verify flow, the resumable manifest, the non-empty guard, the
sha check, and the idempotent `--backfill-db` rewrite of `documents.object_key`,
`extraction.pages[].image_path` and the export job result.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.models.background_job_model import BackgroundJob
from app.models.document_model import Document
from app.models.user_model import User
from app.services.profile import document_storage as storage_module
from app.services.profile.document_storage import (
    DocumentStorage,
    document_key,
    export_key,
    legacy_document_path,
    legacy_page_path,
    page_key,
)
from app.storage.object_storage import LocalObjectStore, StorageConfig
from tests.settings_factory import settings_from_env_file

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "migrate_objects.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("career_migrate_objects", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cli = _load_cli()


def _settings(tmp_path: Path):
    return settings_from_env_file(
        None,
        data_dir=tmp_path / "data",
        upload_dir=str(tmp_path / "uploads"),
        identity_mode=None,
        object_storage_local_root=tmp_path / "target",
    )


def _args(
    manifest: Path,
    *,
    dry_run=False,
    apply=False,
    verify=False,
    backfill=False,
    force=False,
    rebind=False,
):
    return cli.build_parser().parse_args(
        [
            *(["--dry-run"] if dry_run else []),
            *(["--apply"] if apply else []),
            *(["--verify"] if verify else []),
            *(["--backfill-db"] if backfill else []),
            *(["--force"] if force else []),
            *(["--rebind"] if rebind else []),
            "--manifest",
            str(manifest),
        ]
    )


async def _run(args, settings, db):
    return await cli.run_async(args, settings, session_factory=_factory(db))


def _factory(db):
    @asynccontextmanager
    async def factory():
        yield db

    return factory


async def _user(db) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        password_hash="$2b$12$careermigrateplaceholder",
        full_name="",
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _document(db, user: User, payload: bytes, pages: int = 1) -> Document:
    document = Document(
        user_id=user.id,
        kind="cv",
        filename="cv.pdf",
        mime="application/pdf",
        size_bytes=len(payload),
        page_count=pages,
        status="parsed",
        error="",
        extraction={
            "pages": [
                {
                    "index": index,
                    "text": "",
                    "image_path": f"/app/uploads/derived/x/page-{index}.png",
                }
                for index in range(pages)
            ]
        },
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


def _write_legacy(settings, document: Document, payload: bytes, pages: int = 1) -> None:
    root = Path(settings.upload_root)
    source = legacy_document_path(document, root)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(payload)
    for index in range(pages):
        page = legacy_page_path(document.id, index, root)
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_bytes(f"page-{index}".encode())


def _target(settings) -> LocalObjectStore:
    return LocalObjectStore(
        StorageConfig(
            backend="local",
            entrypoint="server",
            local_root=Path(settings.object_storage_local_root),
            max_object_mb=25,
        ).validate()
    )


async def test_dry_run_reports_without_writing(db, tmp_path: Path, capsys) -> None:
    settings = _settings(tmp_path)
    user = await _user(db)
    document = await _document(db, user, b"pdf bytes")
    _write_legacy(settings, document, b"pdf bytes")
    manifest = tmp_path / "manifest.json"

    assert await _run(_args(manifest, dry_run=True), settings, db) == 0
    output = capsys.readouterr().out
    assert "would copy 2 object" in output
    assert not manifest.exists()
    assert not any(Path(settings.object_storage_local_root).rglob("*"))
    assert str(settings.upload_root) not in output


async def test_apply_verify_resume_and_backfill(db, tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    user = await _user(db)
    document = await _document(db, user, b"pdf bytes", pages=2)
    _write_legacy(settings, document, b"pdf bytes", pages=2)
    job = BackgroundJob(
        user_id=user.id, job_type="data_export", status="succeeded", payload={}, result={}
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    archive = Path(settings.upload_root) / "exports" / f"career-assistant-export-{job.id}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"zip")
    manifest = tmp_path / "manifest.json"

    assert await _run(_args(manifest, apply=True), settings, db) == 0
    store = _target(settings)
    assert store.get(document_key(user.id, document.id, document.filename)) == b"pdf bytes"
    assert store.get(page_key(user.id, document.id, 1)) == b"page-1"
    assert store.get(export_key(user.id, job.id)) == b"zip"

    assert await _run(_args(manifest, apply=True), settings, db) == 0
    assert await _run(_args(manifest, verify=True), settings, db) == 0

    # Dual-read before the backfill: the row has no key yet.
    monkeypatch.setattr(
        storage_module, "settings", type("S", (), {"upload_root": Path(settings.upload_root)})()
    )
    assert document.object_key is None
    assert DocumentStorage(store).read(document) == b"pdf bytes"

    assert await _run(_args(manifest, backfill=True), settings, db) == 0
    await db.refresh(document)
    await db.refresh(job)
    assert document.object_key == document_key(user.id, document.id, document.filename)
    assert document.extraction["pages"][0]["image_path"] == page_key(user.id, document.id, 0)
    assert document.extraction["pages"][1]["image_path"] == page_key(user.id, document.id, 1)
    assert job.result["export_key"] == export_key(user.id, job.id)
    assert "export_path" not in job.result
    assert DocumentStorage(store).read(document) == b"pdf bytes"

    # Idempotent: a second backfill changes nothing.
    assert await _run(_args(manifest, backfill=True), settings, db) == 0
    await db.refresh(document)
    assert document.object_key == document_key(user.id, document.id, document.filename)


async def test_export_without_job_is_skipped(db, tmp_path: Path, capsys) -> None:
    settings = _settings(tmp_path)
    user = await _user(db)
    document = await _document(db, user, b"pdf")
    _write_legacy(settings, document, b"pdf")
    archive = Path(settings.upload_root) / "exports" / f"career-assistant-export-{uuid.uuid4()}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"zip")
    manifest = tmp_path / "manifest.json"

    assert await _run(_args(manifest, apply=True), settings, db) == 0
    output = capsys.readouterr().out
    assert "skipped: exports/" in output
    assert "regenerable" in output
    store = _target(settings)
    assert not any(info.key.endswith(".zip") for info in store.list())


async def test_non_empty_target_refuses_until_forced(db, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    user = await _user(db)
    document = await _document(db, user, b"pdf")
    _write_legacy(settings, document, b"pdf")
    target = Path(settings.object_storage_local_root)
    target.mkdir(parents=True)
    (target / "foreign.bin").write_bytes(b"live data")
    manifest = tmp_path / "manifest.json"

    with pytest.raises(SystemExit, match="Refusing"):
        await _run(_args(manifest, apply=True), settings, db)
    assert await _run(_args(manifest, apply=True, force=True), settings, db) == 0


async def test_corrupt_manifest_and_verify_tamper(db, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    user = await _user(db)
    document = await _document(db, user, b"pdf")
    _write_legacy(settings, document, b"pdf")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{broken", encoding="utf-8")

    with pytest.raises(SystemExit, match="corrupt manifest"):
        await _run(_args(manifest, apply=True), settings, db)
    assert await _run(_args(manifest, apply=True, force=True), settings, db) == 0

    store = _target(settings)
    key = document_key(user.id, document.id, document.filename)
    store.put(key, b"tampered")
    assert await _run(_args(manifest, verify=True), settings, db) == 1


async def test_backfill_preserves_existing_keys_and_unverified_legacy_pages(
    db, tmp_path: Path, capsys
) -> None:
    settings = _settings(tmp_path)
    user = await _user(db)
    document = await _document(db, user, b"pdf")
    existing_key = page_key(user.id, document.id, 0)
    legacy_page = f"uploads/derived/{document.id}/page-1.png"
    document.extraction = {
        "pages": [
            {"index": 0, "text": "", "image_path": existing_key},
            {"index": 1, "text": "", "image_path": legacy_page},
        ]
    }
    db.add(document)
    await db.commit()
    _write_legacy(settings, document, b"pdf", pages=1)
    manifest = tmp_path / "manifest.json"

    assert await _run(_args(manifest, apply=True), settings, db) == 0
    assert await _run(_args(manifest, verify=True), settings, db) == 0
    assert await _run(_args(manifest, backfill=True), settings, db) == 0
    await db.refresh(document)
    assert document.extraction["pages"][0]["image_path"] == existing_key
    assert document.extraction["pages"][1]["image_path"] == legacy_page
    assert "unmigrated pages 1" in capsys.readouterr().out


async def test_wrong_target_is_refused_and_rebind_recovers(db, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    user = await _user(db)
    document = await _document(db, user, b"pdf")
    _write_legacy(settings, document, b"pdf")
    manifest = tmp_path / "manifest.json"
    assert await _run(_args(manifest, apply=True), settings, db) == 0

    other = settings.model_copy(update={"object_storage_local_root": tmp_path / "target-b"})
    with pytest.raises(SystemExit, match="manifest target does not match"):
        await _run(_args(manifest, apply=True), other, db)
    assert await _run(_args(manifest, apply=True, rebind=True), other, db) == 0
    assert await _run(_args(manifest, verify=True), other, db) == 0


async def test_nested_source_and_target_roots_are_refused(db, tmp_path: Path) -> None:
    settings = settings_from_env_file(
        None,
        data_dir=tmp_path / "data",
        upload_dir=str(tmp_path / "uploads"),
        identity_mode=None,
        object_storage_local_root=tmp_path / "uploads" / "nested",
    )
    user = await _user(db)
    document = await _document(db, user, b"pdf")
    _write_legacy(settings, document, b"pdf")
    with pytest.raises(SystemExit, match="nested"):
        await _run(_args(tmp_path / "manifest.json", apply=True), settings, db)


async def test_verify_blocks_a_missing_target_object(db, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    user = await _user(db)
    document = await _document(db, user, b"pdf")
    _write_legacy(settings, document, b"pdf")
    manifest = tmp_path / "manifest.json"
    assert await _run(_args(manifest, apply=True), settings, db) == 0
    key = document_key(user.id, document.id, document.filename)
    _target(settings).delete(key)
    assert await _run(_args(manifest, verify=True), settings, db) == 1


async def test_backfill_requires_verify(db, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    user = await _user(db)
    document = await _document(db, user, b"pdf")
    _write_legacy(settings, document, b"pdf")
    manifest = tmp_path / "manifest.json"

    assert await _run(_args(manifest, apply=True), settings, db) == 0
    with pytest.raises(SystemExit, match="requires a clean verify"):
        await _run(_args(manifest, backfill=True), settings, db)
