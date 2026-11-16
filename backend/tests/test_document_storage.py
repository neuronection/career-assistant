"""Career's DocumentStorage facade over the family object-storage contract.

The DB stores an opaque object key; rows written before the contract keep
their legacy `<upload_dir>/<id><ext>` file usable through dual-read. Store
I/O from async paths must leave the event loop (anyio thread bridge).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config

from alembic import command
from app.models.document_model import Document
from app.models.enums import DocumentKind, DocumentStatus
from app.services.profile import document_storage as storage_module
from app.services.profile.document_storage import (
    DocumentStorage,
    document_key,
    export_key,
    page_key,
)
from app.storage.bootstrap import resolve_storage_config
from app.storage.object_storage import (
    BACKEND_LOCAL,
    BACKEND_S3,
    ENTRYPOINT_SERVER,
    LocalObjectStore,
    StorageConfig,
    UnsupportedOperation,
)
from tests.settings_factory import settings_from_env_file


def _store(tmp_path: Path) -> LocalObjectStore:
    return LocalObjectStore(
        StorageConfig(
            backend=BACKEND_LOCAL,
            entrypoint=ENTRYPOINT_SERVER,
            local_root=tmp_path / "uploads",
            max_object_mb=25,
        ).validate()
    )


def _document(payload: bytes = b"", filename: str = "cv.pdf") -> Document:
    return Document(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        kind=DocumentKind.CV.value,
        filename=filename,
        mime="application/pdf",
        size_bytes=len(payload),
        page_count=0,
        status=DocumentStatus.UPLOADED.value,
        error="",
    )


def test_keys_are_server_generated_and_tenant_scoped() -> None:
    document = _document()
    assert document_key(document.user_id, document.id, "CV.PDF") == (
        f"tenants/{document.user_id}/documents/{document.id}.pdf"
    )
    assert page_key(document.user_id, document.id, 2) == (
        f"tenants/{document.user_id}/cv_pages/{document.id}-p2.png"
    )
    assert export_key(document.user_id, document.id) == (
        f"tenants/{document.user_id}/exports/{document.id}.zip"
    )
    assert document_key(document.user_id, document.id, "../../evil.pdf").endswith(
        f"{document.id}.pdf"
    )


def test_dual_read_prefers_the_object_then_the_legacy_file(tmp_path, monkeypatch):
    settings = SimpleNamespace(upload_root=tmp_path / "uploads")
    monkeypatch.setattr(storage_module, "settings", settings)
    store = _store(tmp_path)
    storage = DocumentStorage(store)
    document = _document(b"legacy")

    legacy = tmp_path / "uploads" / f"{document.id}.pdf"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"legacy")

    # no key, no object: legacy fallback
    assert storage.read(document) == b"legacy"
    assert b"".join(storage.stream(document, chunk_size=3)) == b"legacy"
    with storage.materialize(document) as path:
        # A private copy, never the durable legacy path.
        assert path != legacy
        assert path.read_bytes() == b"legacy"
        assert path.stat().st_mode & 0o777 == 0o600
        materialized = path
    assert not materialized.exists()

    # key present but object absent (the migration backfill window)
    document.object_key = document_key(document.user_id, document.id, document.filename)
    assert storage.read(document) == b"legacy"

    # object wins over the legacy file
    storage.put_document(document, b"object")
    assert storage.read(document) == b"object"
    with storage.materialize(document) as path:
        assert path.read_bytes() == b"object"
        assert path.stat().st_mode & 0o777 == 0o600


def test_object_only_row_reads_without_a_legacy_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage_module, "settings", SimpleNamespace(upload_root=tmp_path / "uploads")
    )
    storage = DocumentStorage(_store(tmp_path))
    document = _document(b"only")
    document.object_key = storage.put_document(document, b"only")
    assert storage.read(document) == b"only"
    assert storage.exists(document)


def test_delete_removes_source_pages_and_legacy_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage_module, "settings", SimpleNamespace(upload_root=tmp_path / "uploads")
    )
    store = _store(tmp_path)
    storage = DocumentStorage(store)
    document = _document(b"delete me")
    document.page_count = 2
    document.extraction = {"pages": [{"index": 0}, {"index": 1}]}
    document.object_key = storage.put_document(document, b"delete me")
    storage.put_page(document, 0, b"page-0")

    derived = tmp_path / "uploads" / "derived" / str(document.id)
    derived.mkdir(parents=True)
    (derived / "page-0.png").write_bytes(b"legacy page")
    legacy = tmp_path / "uploads" / f"{document.id}.pdf"
    legacy.write_bytes(b"legacy source")

    storage.delete(document)
    assert store.get(document.object_key) is None
    assert store.get(page_key(document.user_id, document.id, 0)) is None
    assert not legacy.exists()
    assert not derived.exists()


def test_delete_enumerates_pages_without_row_counters(tmp_path, monkeypatch):
    """A failed/PROCESSING document owns pages but reports page_count=0."""
    monkeypatch.setattr(
        storage_module, "settings", SimpleNamespace(upload_root=tmp_path / "uploads")
    )
    store = _store(tmp_path)
    storage = DocumentStorage(store)
    document = _document(b"failed")
    document.page_count = 0
    document.extraction = None
    document.status = DocumentStatus.FAILED.value
    document.object_key = storage.put_document(document, b"failed")
    storage.put_page(document, 0, b"page-0")
    storage.put_page(document, 7, b"page-7")

    storage.delete(document)

    assert store.get(document.object_key) is None
    assert store.get(page_key(document.user_id, document.id, 0)) is None
    assert store.get(page_key(document.user_id, document.id, 7)) is None
    assert list(store.list(storage.page_prefix(document))) == []


def test_delete_spares_an_object_shared_with_another_row(tmp_path):
    store = _store(tmp_path)
    storage = DocumentStorage(store)
    document = _document(b"shared")
    document.object_key = storage.put_document(document, b"shared")
    storage.delete(document, object_shared=True)
    assert store.get(document.object_key) == b"shared"


class _CountDB:
    def __init__(self, count: int) -> None:
        self.count = count

    async def scalar(self, *_args, **_kwargs):
        return self.count


async def test_async_delete_checks_for_a_sharing_row(tmp_path):
    store = _store(tmp_path)
    storage = DocumentStorage(store)
    document = _document(b"shared")
    document.object_key = storage.put_document(document, b"shared")

    await storage.adelete(document, db=_CountDB(1))  # type: ignore[arg-type]
    assert store.get(document.object_key) == b"shared"

    # A legacy row (object_key is None) still consults the sharing guard
    # through its deterministic key.
    document.object_key = None
    await storage.adelete(document, db=_CountDB(1))  # type: ignore[arg-type]
    assert store.get(document_key(document.user_id, document.id, document.filename)) == b"shared"

    await storage.adelete(document, db=_CountDB(0))  # type: ignore[arg-type]
    assert store.get(document_key(document.user_id, document.id, document.filename)) is None


class _RecordingStore:
    """Delegating store that records which thread performed the call."""

    def __init__(self, inner: LocalObjectStore) -> None:
        self.inner = inner
        self.put_threads: list[int] = []
        self.get_threads: list[int] = []

    @property
    def backend(self) -> str:
        return self.inner.backend

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def put(self, *args, **kwargs):
        self.put_threads.append(threading.get_ident())
        return self.inner.put(*args, **kwargs)

    def get(self, *args, **kwargs):
        self.get_threads.append(threading.get_ident())
        return self.inner.get(*args, **kwargs)


async def test_store_io_leaves_the_event_loop(tmp_path):
    store = _RecordingStore(_store(tmp_path))
    storage = DocumentStorage(store)  # type: ignore[arg-type]
    document = _document(b"offload")
    loop_thread = threading.get_ident()

    key = await storage.aput_document(document, b"offload")
    document.object_key = key
    assert await storage.aread(document) == b"offload"

    assert store.put_threads and store.get_threads
    assert all(ident != loop_thread for ident in store.put_threads)
    assert all(ident != loop_thread for ident in store.get_threads)


async def test_async_document_apis_offload(tmp_path):
    store = _RecordingStore(_store(tmp_path))
    storage = DocumentStorage(store)  # type: ignore[arg-type]
    document = _document(b"stream")
    document.object_key = await storage.aput_document(document, b"stream")
    assert b"".join([chunk async for chunk in storage.astream(document, chunk_size=2)]) == (
        b"stream"
    )


def test_settings_bind_the_object_cap_to_the_largest_object_class(tmp_path):
    settings = settings_from_env_file(
        None,
        max_upload_mb=25,
        upload_dir=str(tmp_path / "uploads"),
        data_dir=tmp_path,
    )
    config = resolve_storage_config(settings)
    assert config.backend == BACKEND_LOCAL
    # Uploads stay capped at 25 in the service; the store must accept a full
    # export (default export ceiling 1024).
    assert config.max_object_mb == max(25, settings.export_max_mb)
    assert settings.export_max_mb == 1024

    lowered = settings_from_env_file(
        None,
        max_upload_mb=25,
        export_max_mb=64,
        upload_dir=str(tmp_path / "uploads"),
        data_dir=tmp_path,
    )
    assert resolve_storage_config(lowered).max_object_mb == 64


def test_settings_cloud_profile_resolves_the_provider_backend(tmp_path):
    settings = settings_from_env_file(
        None,
        upload_dir=str(tmp_path / "uploads"),
        data_dir=tmp_path,
        cloud_profile="aws",
        object_storage_backend="s3",
        s3_bucket="career-test",
        s3_region="eu-central-1",
    )
    config = resolve_storage_config(settings)
    assert config.backend == BACKEND_S3
    assert config.required is True
    assert config.max_object_mb == max(settings.max_upload_mb, settings.export_max_mb)


def test_desktop_refuses_an_object_backend(tmp_path):
    from app.storage.object_storage import StorageConfigError

    settings = settings_from_env_file(
        None,
        upload_dir=str(tmp_path / "uploads"),
        data_dir=tmp_path,
        identity_mode="desktop",
        object_storage_backend="s3",
        s3_bucket="career-test",
        s3_region="eu-central-1",
    )
    with pytest.raises(StorageConfigError):
        resolve_storage_config(settings)


def test_backup_refuses_an_object_backend(tmp_path, monkeypatch):
    from app import backups
    from app.storage import bootstrap

    settings = settings_from_env_file(
        None,
        upload_dir=str(tmp_path / "uploads"),
        data_dir=tmp_path,
        object_storage_backend="s3",
        s3_bucket="career-test",
        s3_region="eu-central-1",
    )
    monkeypatch.setattr(bootstrap, "global_settings", settings)
    with pytest.raises(UnsupportedOperation):
        backups.create_backup(tmp_path)
    with pytest.raises(UnsupportedOperation):
        backups.restore_backup(tmp_path, tmp_path / "missing.zip")


def _configured(tmp_path: Path, monkeypatch) -> Config:
    from app.core.config import settings

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'storage-migration.db'}"
    monkeypatch.setenv("CAREER_DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "database_url", db_url, raising=False)
    return Config("alembic.ini")


def test_0015_adds_object_key_without_data_backfill(tmp_path, monkeypatch):
    config = _configured(tmp_path, monkeypatch)
    db_file = tmp_path / "storage-migration.db"
    command.upgrade(config, "0014")

    document_id = uuid.uuid4()
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    now = datetime.now(UTC).isoformat()
    extraction = {
        "pages": [
            {"index": 0, "text": "hello", "image_path": "/app/uploads/derived/x/page-0.png"},
            {"index": 1, "text": "", "image_path": None},
        ]
    }
    connection = sqlite3.connect(db_file)
    try:
        connection.execute(
            "INSERT INTO documents (id, user_id, kind, filename, mime, size_bytes, "
            "page_count, status, error, extraction, created_at, updated_at) "
            "VALUES (?, ?, 'cv', 'cv.pdf', 'application/pdf', 3, 2, 'ready', '', ?, ?, ?)",
            (document_id.hex, user_id.hex, json.dumps(extraction), now, now),
        )
        connection.execute(
            "INSERT INTO background_jobs (id, user_id, job_type, status, progress, payload, "
            "attempts, max_attempts, cancel_requested, result, created_at, updated_at) "
            "VALUES (?, ?, 'data_export', 'succeeded', 100, '{}', 1, 1, 0, ?, ?, ?)",
            (
                job_id.hex,
                user_id.hex,
                json.dumps({"export_path": "/app/uploads/exports/x.zip", "filename": "x.zip"}),
                now,
                now,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    command.upgrade(config, "head")

    connection = sqlite3.connect(db_file)
    try:
        row = connection.execute(
            "SELECT object_key, extraction FROM documents WHERE id = ?", (document_id.hex,)
        ).fetchone()
        assert row[0] is None
        # DDL only: the path/extraction/export backfill is migrate-objects
        # --backfill-db, which runs after --verify, not at upgrade time.
        unchanged = json.loads(row[1])
        assert unchanged["pages"][0]["image_path"] == "/app/uploads/derived/x/page-0.png"
        result = json.loads(
            connection.execute(
                "SELECT result FROM background_jobs WHERE id = ?", (job_id.hex,)
            ).fetchone()[0]
        )
        assert result["export_path"] == "/app/uploads/exports/x.zip"
    finally:
        connection.close()

    command.downgrade(config, "0014")
    connection = sqlite3.connect(db_file)
    try:
        columns = {
            info[1] for info in connection.execute("PRAGMA table_info('documents')").fetchall()
        }
        assert "object_key" not in columns
    finally:
        connection.close()


def test_local_conformance(tmp_path):
    from app.storage.object_storage import run_conformance

    store = _store(tmp_path)
    try:
        assert run_conformance(store) == []
    finally:
        store.close()
