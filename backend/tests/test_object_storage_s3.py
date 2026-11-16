"""Opt-in S3/MinIO/AWS smoke test for the object-storage contract (plan 55 P2).

Normal PRs and the desktop suite need no credentials: without
``CAREER_TEST_S3_BUCKET`` this module skips. An endpoint is optional: real
AWS S3 uses the regional default, while MinIO/moto need
``CAREER_TEST_S3_ENDPOINT_URL``. It runs the family conformance wall plus
career's document facade (upload → read → stream → page → materialize →
delete) through the real backend, so the host key layout is proven on S3,
not only on `local`.

    CAREER_TEST_ALLOW_NETWORK=1 CAREER_TEST_S3_BUCKET=nx-object-storage \\
    CAREER_TEST_S3_ENDPOINT_URL=http://127.0.0.1:19000 \\
    CAREER_TEST_S3_ACCESS_KEY_ID=test CAREER_TEST_S3_SECRET_ACCESS_KEY=test \\
    CAREER_TEST_S3_REGION=us-east-1 CAREER_TEST_S3_PATH_STYLE=true \\
    CAREER_TEST_S3_SSE=none \\
    uv run --directory backend --with boto3 pytest -q tests/test_object_storage_s3.py

Real AWS S3 (credentials via the default chain, e.g. ``AWS_PROFILE``):

    AWS_PROFILE=study-test CAREER_TEST_ALLOW_NETWORK=1 \\
    CAREER_TEST_S3_BUCKET=study-assistant-test CAREER_TEST_S3_REGION=eu-north-1 \\
    CAREER_TEST_S3_PREFIX=test/career-smoke \\
    uv run --directory backend --with boto3 pytest -q tests/test_object_storage_s3.py

See docs/dev/storage.md.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.models.document_model import Document
from app.services.profile.document_storage import DocumentStorage
from app.storage.object_storage import (
    BACKEND_S3,
    ENTRYPOINT_SERVER,
    S3Config,
    StorageConfig,
    build_store,
    run_conformance,
)

ENV_PREFIX = "CAREER_TEST"
REQUIRED = ("S3_BUCKET",)


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"{ENV_PREFIX}_{name}") or default


def _require_backend() -> None:
    missing = [f"{ENV_PREFIX}_{name}" for name in REQUIRED if not _env(name)]
    if missing:
        pytest.skip(f"S3 smoke disabled; set {', '.join(missing)}")
    pytest.importorskip("boto3")


def _config(prefix: str) -> StorageConfig:
    endpoint = _env("S3_ENDPOINT_URL")
    path_style_raw = _env("S3_PATH_STYLE") or ("true" if endpoint else "false")
    path_style = path_style_raw.lower() in ("1", "true", "yes", "on")
    sse = _env("S3_SSE", "none" if endpoint else "AES256") or "none"
    return StorageConfig(
        backend=BACKEND_S3,
        entrypoint=ENTRYPOINT_SERVER,
        s3=S3Config(
            bucket=_env("S3_BUCKET") or "",
            region=_env("S3_REGION"),
            endpoint_url=endpoint,
            access_key_id=_env("S3_ACCESS_KEY_ID"),
            secret_access_key=_env("S3_SECRET_ACCESS_KEY"),
            session_token=_env("S3_SESSION_TOKEN"),
            path_style=path_style,
            sse=sse,
            prefix=prefix,
            verify_tls=(_env("S3_VERIFY_TLS", "true") or "true").lower()
            in ("1", "true", "yes", "on"),
        ),
    ).validate()


def _prefix() -> str:
    raw = (_env("S3_PREFIX", "smoke") or "smoke").strip("/")
    return f"{raw}/{uuid.uuid4().hex[:8]}/"


def _document(payload: bytes) -> Document:
    return Document(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        kind="cv",
        filename="cv.pdf",
        mime="application/pdf",
        size_bytes=len(payload),
        page_count=0,
        status="uploaded",
        error="",
    )


def test_s3_conformance() -> None:
    _require_backend()
    store = build_store(_config(_prefix()))
    try:
        store.health()
        assert run_conformance(store) == []
    finally:
        store.close()


def test_s3_document_facade_roundtrip() -> None:
    _require_backend()
    store = build_store(_config(_prefix()))
    payload = b"%PDF-1.4 s3 smoke body"
    page = b"\x89PNG\r\n\x1a\n page"
    document = _document(payload)
    storage = DocumentStorage(store)
    try:
        store.health()
        key = storage.put_document(document, payload)
        document.object_key = key
        assert key == f"tenants/{document.user_id}/documents/{document.id}.pdf"
        assert storage.read(document) == payload
        assert b"".join(storage.stream(document, chunk_size=3)) == payload
        assert storage.exists(document)
        # page_count stays 0 and extraction stays None: the delete must
        # enumerate the page prefix, not the row counters.
        storage.put_page(document, 0, page)
        storage.put_page(document, 3, page)
        assert storage.read_page(document, 0) == page
        with storage.materialize(document) as path:
            assert path.read_bytes() == payload
            assert path.stat().st_mode & 0o777 == 0o600
        assert not path.exists()
        export = storage.put_export(document.user_id, document.id, b"PK\x03\x04 export")
        assert storage.read_key(export) == b"PK\x03\x04 export"
        assert b"".join(storage.stream_key(export, chunk_size=4)) == b"PK\x03\x04 export"
        storage.delete(document)
        storage.delete_key(export)
        assert storage.read(document) is None
        assert storage.read_page(document, 0) is None
        assert storage.read_page(document, 3) is None
        assert storage.read_key(export) is None
    finally:
        store.close()


def test_s3_materialize_uses_private_temp_file(tmp_path: Path) -> None:
    _require_backend()
    store = build_store(_config(_prefix()))
    document = _document(b"materialize")
    storage = DocumentStorage(store)
    try:
        document.object_key = storage.put_document(document, b"materialize")
        with storage.materialize(document) as path:
            assert path.read_bytes() == b"materialize"
        storage.delete(document)
    finally:
        store.close()
