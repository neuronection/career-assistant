"""— CV Studio foundation: originals, text/OCR pipeline, CV records."""

import io
import uuid
from pathlib import Path

from pypdf import PdfWriter
from sqlalchemy import select

from app.models.cv_model import CvDocument, CvVersion
from app.models.enums import CvVersionCreator
from app.services.cv_source_service import content_sha256
from app.services.job_worker import JobWorker, enqueue


async def _drain(db):
    """Run the background queue to completion (mock AI is fast)."""
    worker = JobWorker(db)
    while await worker.run_once():
        pass


def _text_pdf(pages: list[str]) -> bytes:
    """Build a minimal PDF whose pages carry an embedded text layer."""
    objects: list[bytes] = []
    page_ids = []
    next_id = 3
    font_id = 3 + 2 * len(pages)
    for text in pages:
        content_id = next_id
        page_id = next_id + 1
        next_id += 2
        stream = f"BT /F1 14 Tf 40 700 Td ({text}) Tj ET".encode()
        objects.append(
            b"%d 0 obj\n<< /Length %d >>\nstream\n%s\nendstream\nendobj\n"
            % (content_id, len(stream), stream)
        )
        page_ids.append(page_id)
        objects.append(
            b"%d 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 400] "
            b"/Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>\nendobj\n"
            % (page_id, content_id, font_id)
        )
    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    objects.insert(
        0,
        b"1 0 obj\n<< /Type /Pages /Kids [%s] /Count %d >>\nendobj\n"
        % (kids, len(page_ids)),
    )
    objects.insert(
        1,
        b"2 0 obj\n<< /Type /Catalog /Pages 1 0 R >>\nendobj\n",
    )
    objects.append(
        b"%d 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        % font_id
    )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(obj)
    xref_at = out.tell()
    out.write(b"xref\n0 %d\n" % (len(objects) + 1))
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(
        b"trailer\n<< /Size %d /Root 2 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, xref_at)
    )
    data = out.getvalue()
    return data


def _tiny_png() -> bytes:
    """A valid 1x1 red PNG."""
    import struct
    import zlib as _zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", _zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = _zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


async def _upload_cv(client, headers, filename, content, mime):
    return await client.post(
        "/api/v1/documents?kind=cv",
        files={"file": (filename, io.BytesIO(content), mime)},
        headers=headers,
    )


async def _make_cv(client, headers, **overrides) -> dict:
    payload = {"title": "Backend Intern CV", **overrides}
    response = await client.post("/api/v1/cv", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_cv_upload_preserves_original_bytes(client, db, auth_headers):
    content = "Jane Doe — Python, SQL\nExperience: built a thing\n".encode()
    upload = await _upload_cv(client, auth_headers, "cv.txt", content, "text/plain")
    assert upload.status_code == 202, upload.text
    body = upload.json()
    assert body["document"]["kind"] == "cv"
    doc_id = body["document"]["id"]
    await _drain(db)

    detail = await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert detail.status_code == 200
    doc = detail.json()
    assert doc["status"] == "ready", doc
    assert doc["extraction"]["has_text_layer"] is True
    assert doc["extraction"]["ocr_used"] is False
    assert "Jane Doe" in doc["extraction"]["full_text"]
    assert doc["extraction"]["content_sha256"] == content_sha256(content)

    original = await client.get(
        f"/api/v1/documents/{doc_id}/file", headers=auth_headers
    )
    assert original.status_code == 200
    assert original.content == content, "original bytes must be byte-exact"


async def test_cv_pdf_text_layer_per_page(client, db, auth_headers):
    pages = ["Jane Doe CV", "Experience: DevOps intern"]
    upload = await _upload_cv(
        client, auth_headers, "cv.pdf", _text_pdf(pages), "application/pdf"
    )
    doc_id = upload.json()["document"]["id"]
    await _drain(db)

    detail = (
        await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    ).json()
    assert detail["status"] == "ready"
    assert detail["page_count"] == 2
    extraction = detail["extraction"]
    assert [p["index"] for p in extraction["pages"]] == [0, 1]
    assert extraction["pages"][0]["source"] == "text_layer"
    assert extraction["pages"][0]["text"].strip() == "Jane Doe CV"
    assert "DevOps intern" in extraction["full_text"]


async def test_cv_scanned_pdf_falls_back_to_mock_vision_ocr(client, db, auth_headers):
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=400)
    buffer = io.BytesIO()
    writer.write(buffer)
    upload = await _upload_cv(
        client, auth_headers, "scanned.pdf", buffer.getvalue(), "application/pdf"
    )
    doc_id = upload.json()["document"]["id"]
    await _drain(db)

    detail = (
        await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    ).json()
    assert detail["status"] == "ready", detail
    extraction = detail["extraction"]
    assert extraction["ocr_used"] is True
    assert extraction["pages"][0]["source"] == "ocr_vision"
    assert extraction["pages"][0]["text"].startswith("[ocr] page 0")
    assert extraction["engine"]["ocr"] == "vision"

    image = await client.get(
        f"/api/v1/documents/{doc_id}/pages/0/image", headers=auth_headers
    )
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"


async def test_cv_image_upload_uses_ocr_and_serves_page(client, db, auth_headers):
    upload = await _upload_cv(client, auth_headers, "cv.png", _tiny_png(), "image/png")
    assert upload.status_code == 202, upload.text
    doc_id = upload.json()["document"]["id"]
    await _drain(db)
    detail = (
        await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    ).json()
    assert detail["status"] == "ready"
    assert detail["extraction"]["ocr_used"] is True
    image = await client.get(
        f"/api/v1/documents/{doc_id}/pages/0/image", headers=auth_headers
    )
    assert image.status_code == 200


async def test_document_delete_removes_files(client, db, auth_headers):
    content = "to be deleted".encode()
    upload = await _upload_cv(client, auth_headers, "gone.txt", content, "text/plain")
    doc_id = upload.json()["document"]["id"]
    await _drain(db)
    assert source_file_path_by_id(doc_id).exists()
    response = await client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert response.status_code == 204
    assert not source_file_path_by_id(doc_id).exists()
    detail = await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert detail.status_code == 404


def source_file_path_by_id(document_id: str) -> Path:
    from app.core.config import settings

    return Path(settings.UPLOAD_DIR) / f"{document_id}.txt"


async def test_document_delete_requires_ownership(client, db, auth_headers):
    first = await _upload_cv(client, auth_headers, "mine.txt", b"x", "text/plain")
    other_headers = await _second_user(client)
    response = await client.delete(
        f"/api/v1/documents/{first.json()['document']['id']}", headers=other_headers
    )
    assert response.status_code == 404


async def _second_user(client) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "supersecret1"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_cv_crud_and_autosave(client, db, auth_headers):
    cv = await _make_cv(client, auth_headers, max_pages=2)
    assert cv["status"] == "draft"
    assert cv["kind"] == "resume"
    assert cv["context"]["mode"] == "all"
    assert cv["latest_version"] is None

    patch = await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {"header": {"name": "Jane"}, "blocks": []},
            "context": {"mode": "custom", "include": [], "exclude": []},
        },
        headers=auth_headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["working_content"]["header"]["name"] == "Jane"
    assert patch.json()["context"]["mode"] == "custom"

    listing = await client.get("/api/v1/cv", headers=auth_headers)
    assert [item["id"] for item in listing.json()] == [cv["id"]]


async def test_cv_versions_are_immutable_snapshots(client, db, auth_headers):
    cv = await _make_cv(client, auth_headers)
    content_v1 = {"blocks": [{"kind": "header", "text": "v1"}]}
    first = await client.post(
        f"/api/v1/cv/{cv['id']}/versions", json=content_v1, headers=auth_headers
    )
    assert first.status_code == 201, first.text
    v1 = first.json()
    assert v1["version"] == 1
    assert v1["created_by"] == "user_save"
    assert len(v1["content_hash"]) == 64

    second = await client.post(
        f"/api/v1/cv/{cv['id']}/versions",
        json={"blocks": [{"kind": "header", "text": "v2"}]},
        headers=auth_headers,
    )
    assert second.json()["version"] == 2

    versions = await client.get(f"/api/v1/cv/{cv['id']}/versions", headers=auth_headers)
    body = versions.json()
    assert [v["version"] for v in body] == [2, 1]
    assert body[0]["content_hash"] != body[1]["content_hash"]

    detail = (await client.get(f"/api/v1/cv/{cv['id']}", headers=auth_headers)).json()
    assert detail["latest_version"] == 2

    empty = await client.post(
        f"/api/v1/cv/{cv['id']}/versions", json={}, headers=auth_headers
    )
    assert empty.status_code == 400


async def test_cv_version_unique_constraint(db, client, auth_headers):
    import pytest
    from sqlalchemy.exc import IntegrityError

    cv = await _make_cv(client, auth_headers)
    service_cv = await _cv_by_title(db, cv["title"])
    service = _cv_service(db)
    await service.create_version(
        service_cv.id, service_cv.user_id, {"a": 1}, CvVersionCreator.USER_SAVE
    )
    db.add(
        CvVersion(
            cv_document_id=service_cv.id,
            version=1,
            content={"dup": True},
            content_hash="x" * 64,
            created_by=CvVersionCreator.EXPORT.value,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    rows = await db.execute(select(CvVersion).order_by(CvVersion.version))
    assert [v.version for v in rows.scalars()] == [1]


def _cv_service(db):
    from app.services.cv_service import CvService

    return CvService(db)


async def _cv_by_title(db, title: str) -> CvDocument:
    rows = await db.execute(select(CvDocument).where(CvDocument.title == title))
    return rows.scalars().first()


async def test_cv_ownership_is_enforced(client, db, auth_headers):
    cv = await _make_cv(client, auth_headers)
    other = await _second_user(client)
    response = await client.get(f"/api/v1/cv/{cv['id']}", headers=other)
    assert response.status_code == 404
    patch = await client.patch(
        f"/api/v1/cv/{cv['id']}", json={"title": "stolen"}, headers=other
    )
    assert patch.status_code == 404
    delete = await client.delete(f"/api/v1/cv/{cv['id']}", headers=other)
    assert delete.status_code == 404


async def test_cv_delete_cascades_versions(client, db, auth_headers):
    cv = await _make_cv(client, auth_headers)
    await client.post(
        f"/api/v1/cv/{cv['id']}/versions", json={"blocks": []}, headers=auth_headers
    )
    deleted = await client.delete(f"/api/v1/cv/{cv['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    rows = await db.execute(select(CvVersion))
    assert rows.scalars().all() == []


async def test_cv_create_rejects_foreign_source_document(client, db, auth_headers):
    response = await client.post(
        "/api/v1/cv",
        json={"title": "X", "source_document_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_cv_extract_job_requires_user(db):
    job = await enqueue(
        db,
        "cv_extract_text",
        {"document_id": str(uuid.uuid4())},
        user_id=None,
        max_attempts=1,
    )
    worker = JobWorker(db)
    claimed = await worker.claim_next()
    await worker.execute(claimed)
    await db.refresh(job)
    assert job.status == "failed"
    assert "requires a user" in (job.error or "")
