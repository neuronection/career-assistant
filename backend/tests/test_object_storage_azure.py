"""Opt-in Azure Blob smoke test for the object-storage contract (plan 55 P2).

Skips cleanly without credentials; normal PRs never need a cloud account.
Provide a connection string or a managed-identity account URL:

    CAREER_TEST_AZURE_CONTAINER=career-data \\
    CAREER_TEST_AZURE_CONNECTION_STRING='DefaultEndpointsProtocol=https;...' \\
    CAREER_TEST_ALLOW_NETWORK=1 \\
    uv run --directory backend --with azure-storage-blob \\
      pytest -q tests/test_object_storage_azure.py

Managed identity instead of a connection string:

    CAREER_TEST_AZURE_CONTAINER=career-data \\
    CAREER_TEST_AZURE_ACCOUNT_URL=https://career.blob.core.windows.net \\
    CAREER_TEST_AZURE_ACCOUNT_NAME=career \\
    CAREER_TEST_AZURE_CREDENTIAL=managed_identity \\
    uv run --directory backend --with azure-storage-blob --with azure-identity \\
      pytest -q tests/test_object_storage_azure.py

It runs the family conformance wall plus the document facade round-trip.
See docs/dev/storage.md.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.models.document_model import Document
from app.services.profile.document_storage import DocumentStorage
from app.storage.object_storage import (
    BACKEND_AZURE_BLOB,
    ENTRYPOINT_SERVER,
    AzureBlobConfig,
    StorageConfig,
    build_store,
    run_conformance,
)

ENV_PREFIX = "CAREER_TEST"
CONTAINER = f"{ENV_PREFIX}_AZURE_CONTAINER"
CONNECTION_STRING = f"{ENV_PREFIX}_AZURE_CONNECTION_STRING"
ACCOUNT_URL = f"{ENV_PREFIX}_AZURE_ACCOUNT_URL"
ACCOUNT_NAME = f"{ENV_PREFIX}_AZURE_ACCOUNT_NAME"
CREDENTIAL = f"{ENV_PREFIX}_AZURE_CREDENTIAL"
PREFIX = f"{ENV_PREFIX}_AZURE_PREFIX"


def _managed_identity() -> bool:
    return bool(
        os.environ.get(ACCOUNT_URL)
        and os.environ.get(CREDENTIAL, "").strip().lower() == "managed_identity"
    )


def _require_backend() -> bool:
    if not os.environ.get(CONTAINER):
        pytest.skip(f"Azure smoke disabled; set {CONTAINER}")
    managed = _managed_identity()
    if not os.environ.get(CONNECTION_STRING) and not managed:
        pytest.skip(
            "Azure smoke disabled; set "
            f"{CONNECTION_STRING} or {ACCOUNT_URL} + {CREDENTIAL}=managed_identity"
        )
    pytest.importorskip("azure.storage.blob")
    if managed:
        pytest.importorskip("azure.identity")
    return managed


def _config(prefix: str, managed: bool) -> StorageConfig:
    return StorageConfig(
        backend=BACKEND_AZURE_BLOB,
        entrypoint=ENTRYPOINT_SERVER,
        cloud_profile="azure",
        required=True,
        azure_blob=AzureBlobConfig(
            container=os.environ[CONTAINER],
            connection_string=None if managed else os.environ.get(CONNECTION_STRING),
            account_url=os.environ.get(ACCOUNT_URL) if managed else None,
            account_name=os.environ.get(ACCOUNT_NAME),
            managed_identity=managed,
            prefix=prefix,
        ),
    ).validate()


def _prefix() -> str:
    raw = (os.environ.get(PREFIX) or "smoke").strip("/")
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


def test_azure_conformance() -> None:
    managed = _require_backend()
    store = build_store(_config(_prefix(), managed))
    try:
        store.health()
        assert run_conformance(store) == []
    finally:
        store.close()


def test_azure_document_facade_roundtrip() -> None:
    managed = _require_backend()
    store = build_store(_config(_prefix(), managed))
    payload = b"%PDF-1.4 azure smoke body"
    page = b"\x89PNG\r\n\x1a\n page"
    document = _document(payload)
    storage = DocumentStorage(store)
    try:
        store.health()
        key = storage.put_document(document, payload)
        document.object_key = key
        assert key == f"tenants/{document.user_id}/documents/{document.id}.pdf"
        assert storage.read(document) == payload
        # page_count stays 0 and extraction stays None on purpose.
        storage.put_page(document, 0, page)
        storage.put_page(document, 2, page)
        assert storage.read_page(document, 0) == page
        with storage.materialize(document) as path:
            assert path.read_bytes() == payload
        export = storage.put_export(document.user_id, document.id, b"PK\x03\x04 export")
        assert storage.read_key(export) == b"PK\x03\x04 export"
        storage.delete(document)
        storage.delete_key(export)
        assert storage.read(document) is None
        assert storage.read_page(document, 0) is None
        assert storage.read_page(document, 2) is None
        assert storage.read_key(export) is None
    finally:
        store.close()
