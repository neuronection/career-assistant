"""No local filesystem path reaches an API response (ADR-0057 / plan 55 P2).

`documents.extraction` used to carry `pages[].image_path` as an absolute
`/…/uploads/derived/…` path. The migration rewrites stored values to object
keys and the response schema scrubs anything else, so the document shape is
safe even before a row is migrated.
"""

from __future__ import annotations

import io
import json
import os
import uuid
import zipfile

import anyio
import pytest
from sqlalchemy import select, update

from app.models.document_model import Document
from app.models.user_model import User
from app.services.admin.export_service import build_export
from app.services.profile.document_storage import document_storage, export_key
from app.storage.object_storage import ObjectTooLarge


async def _upload(client, headers, content: bytes = b"catalog text"):
    return await client.post(
        "/api/v1/documents",
        files={"file": ("catalog.txt", io.BytesIO(content), "text/plain")},
        headers=headers,
    )


async def test_document_responses_never_expose_local_paths(client, db, auth_headers):
    upload = await _upload(client, auth_headers)
    assert upload.status_code == 202, upload.text
    payload = upload.json()
    assert "object_key" not in payload["document"]
    document_id = uuid.UUID(payload["document"]["id"])
    row = (await db.execute(select(Document).where(Document.id == document_id))).scalars().first()
    owner_id = row.user_id

    tenant_key = f"tenants/{owner_id}/cv_pages/{document_id}-p2.png"
    other_tenant_key = f"tenants/{uuid.uuid4()}/cv_pages/{document_id}-p3.png"
    legacy = {
        "pages": [
            {
                "index": 0,
                "text": "parsed",
                "source": "text_layer",
                "image_path": f"/app/uploads/derived/{document_id}/page-0.png",
            },
            {
                "index": 1,
                "text": "parsed",
                "source": "text_layer",
                "image_path": f"uploads/derived/{document_id}/page-1.png",
            },
            {
                "index": 2,
                "text": "parsed",
                "source": "text_layer",
                "image_path": tenant_key,
            },
            {
                "index": 3,
                "text": "parsed",
                "source": "text_layer",
                "image_path": other_tenant_key,
            },
        ],
        "full_text": "parsed",
    }
    await db.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(
            kind="cv",
            extraction=legacy,
            page_count=4,
            error=(
                "render failed: /app/uploads/derived/x.png; "
                "cwd /home/user/private/project; C:\\Users\\me\\Temp\\x.png"
            ),
        )
    )
    await db.commit()

    for path in (f"/api/v1/documents/{document_id}", "/api/v1/documents?kind=cv"):
        response = await client.get(path, headers=auth_headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        body = json.dumps(payload)
        assert "uploads/" not in body
        assert "derived/" not in body
        assert '"/app/' not in body
        assert "/home/user" not in body
        assert "private" not in body
        assert "Users" not in body
        assert ":\\" not in body
        if isinstance(payload, list):
            document = next(d for d in payload if d["id"] == str(document_id))
        else:
            document = payload
        pages = document["extraction"]["pages"]
        # Owner tenant key survives; every other value (absolute, relative,
        # another tenant) is nulled.
        assert [page["image_path"] for page in pages] == [None, None, tenant_key, None]
        assert "uploads" not in document["error"]
        assert "<path>" in document["error"]


async def test_upload_stores_a_server_generated_key(client, db, auth_headers):
    upload = await _upload(client, auth_headers)
    document_id = uuid.UUID(upload.json()["document"]["id"])
    document = (
        (await db.execute(select(Document).where(Document.id == document_id))).scalars().first()
    )
    user = (await db.execute(select(User).where(User.id == document.user_id))).scalars().first()
    assert document.object_key == (f"tenants/{user.id}/documents/{document_id}.txt")
    assert document.extraction is None


async def test_download_streams_the_object(client, auth_headers):
    content = b"streamed through the store"
    upload = await _upload(client, auth_headers, content)
    document_id = upload.json()["document"]["id"]

    response = await client.get(f"/api/v1/documents/{document_id}/file", headers=auth_headers)
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_download_of_a_zero_byte_object_is_an_empty_200(client, auth_headers):
    upload = await _upload(client, auth_headers, b"")
    document_id = upload.json()["document"]["id"]
    response = await client.get(f"/api/v1/documents/{document_id}/file", headers=auth_headers)
    assert response.status_code == 200
    assert response.content == b""


async def test_download_is_404_when_the_object_disappears(client, db, auth_headers):
    upload = await _upload(client, auth_headers)
    document_id = uuid.UUID(upload.json()["document"]["id"])
    document = (
        (await db.execute(select(Document).where(Document.id == document_id))).scalars().first()
    )
    storage = document_storage()
    await anyio.to_thread.run_sync(storage.delete, document)

    response = await client.get(f"/api/v1/documents/{document_id}/file", headers=auth_headers)
    assert response.status_code == 404


async def test_contract_errors_map_to_http_statuses():
    from starlette.requests import Request

    from app.main import app
    from app.storage.object_storage import (
        ObjectNotFound,
        ObjectTooLarge,
        StorageAuthError,
        StorageConfigError,
        StorageUnavailable,
        UnsupportedOperation,
    )

    request = Request({"type": "http", "method": "GET", "path": "/"})
    cases = [
        (ObjectTooLarge("too big"), 413),
        (ObjectNotFound("missing"), 404),
        (UnsupportedOperation("no presign"), 409),
        (StorageUnavailable("down"), 503),
        (StorageAuthError("denied"), 503),
        (StorageConfigError("bad config"), 500),
    ]
    for error, expected in cases:
        handler = app.exception_handlers[type(error)]
        response = await handler(request, error)
        assert response.status_code == expected, type(error).__name__


async def test_storage_unavailable_maps_to_503(client, auth_headers, monkeypatch):
    from app.services.profile.document_storage import DocumentStorage
    from app.storage.object_storage import StorageUnavailable

    async def unavailable(_self, _document, _data):
        raise StorageUnavailable("provider down")

    monkeypatch.setattr(DocumentStorage, "aput_document", unavailable)
    response = await _upload(client, auth_headers)
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


async def test_export_is_an_object_under_the_tenant_prefix(client, db, auth_headers):
    content = b"export body"
    upload = await _upload(client, auth_headers, content)
    document_id = uuid.UUID(upload.json()["document"]["id"])
    user = (await db.execute(select(User))).scalars().first()
    job_id = uuid.uuid4()

    key = await build_export(db, user, job_id)
    assert key == export_key(user.id, job_id)
    storage = document_storage()
    try:
        raw = await storage.aread_key(key)
        assert raw is not None
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            names = set(bundle.namelist())
            assert "manifest.json" in names
            assert "documents.json" in names
            assert f"documents/{document_id}.txt" in names
            assert bundle.read(f"documents/{document_id}.txt") == content

        from app.models.background_job_model import BackgroundJob

        db.add(
            BackgroundJob(
                id=job_id,
                user_id=user.id,
                job_type="data_export",
                status="succeeded",
                progress=100,
                payload={},
                result={"export_key": key, "filename": "career-assistant-export.zip"},
            )
        )
        await db.commit()
        download = await client.get(
            f"/api/v1/background-jobs/{job_id}/download", headers=auth_headers
        )
        assert download.status_code == 200, download.text
        assert download.headers["cache-control"] == "no-store"
        with zipfile.ZipFile(io.BytesIO(download.content)) as bundle:
            assert f"documents/{document_id}.txt" in bundle.namelist()
    finally:
        await anyio.to_thread.run_sync(storage.delete_key, key)


async def _seed_owned_document(db, user, size: int) -> Document:
    """A document row + store object without the upload-cap endpoint check."""
    document = Document(
        id=uuid.uuid4(),
        user_id=user.id,
        kind="cv",
        filename=f"{uuid.uuid4()}.bin",
        mime="application/octet-stream",
        size_bytes=size,
        page_count=0,
        status="ready",
        error="",
    )
    db.add(document)
    await db.flush()
    document.object_key = await document_storage().aput_document(document, os.urandom(size))
    await db.commit()
    return document


async def _drop_documents(documents) -> None:
    storage = document_storage()
    for document in documents:
        await anyio.to_thread.run_sync(storage.delete, document)


async def test_export_cap_is_independent_of_the_upload_cap(client, db, auth_headers, monkeypatch):
    """One archive bundles every document; the 25 MB upload cap is not its cap."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_mb", 1, raising=False)
    monkeypatch.setattr(settings, "export_max_mb", 8, raising=False)
    user = (await db.execute(select(User))).scalars().first()
    storage = document_storage()
    documents = [await _seed_owned_document(db, user, 2 * 1024 * 1024) for _ in range(2)]
    key = None
    try:
        key = await build_export(db, user, uuid.uuid4())
        raw = await storage.aread_key(key)
        assert raw is not None
        # ~4 MB of documents under a 1 MB upload cap: the upload ceiling did
        # not bound the export.
        assert len(raw) > settings.max_upload_mb * 1024 * 1024
    finally:
        if key is not None:
            await anyio.to_thread.run_sync(storage.delete_key, key)
        await _drop_documents(documents)


async def test_export_over_the_export_cap_fails_with_the_ceiling_named(
    client, db, auth_headers, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "export_max_mb", 1, raising=False)
    user = (await db.execute(select(User))).scalars().first()
    documents = [await _seed_owned_document(db, user, 2 * 1024 * 1024)]
    try:
        with pytest.raises(ObjectTooLarge) as caught:
            await build_export(db, user, uuid.uuid4())
        message = str(caught.value)
        assert "CAREER_EXPORT_MAX_MB" in message
        assert str(settings.export_max_mb) in message
    finally:
        await _drop_documents(documents)
