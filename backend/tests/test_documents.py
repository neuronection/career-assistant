import io

from pypdf import PdfWriter

from app.services.job_worker import JobWorker


async def _drain(db):
    """Run the background queue to completion (mock AI is fast)."""
    worker = JobWorker(db)
    while await worker.run_once():
        pass


def _tiny_pdf(text: str) -> bytes:
    """Build a minimal one-page PDF containing the given text."""
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=400)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


async def _upload(
    client, headers, filename="catalog.txt", content=b"sample", mime="text/plain"
):
    return await client.post(
        "/api/v1/documents",
        files={"file": (filename, io.BytesIO(content), mime)},
        headers=headers,
    )


async def test_upload_parse_apply_text_document(client, db, auth_headers):
    content = (
        "ADMISSIONS BASELINES 2025\n"
        "University of Testing\n"
        "School of Computer Science — baseline 2025: 85.5 points quota 100\n"
        "School of Medicine — baseline 2025: 96 points quota 60\n"
    ).encode()
    response = await _upload(client, auth_headers, "baselines.txt", content)
    assert response.status_code == 202, response.text
    doc_id = response.json()["document"]["id"]
    await _drain(db)

    detail = await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "parsed", body
    assert body["extraction"]["universities"]
    assert body["page_count"] == 1

    applied = await client.post(
        f"/api/v1/documents/{doc_id}/apply", headers=auth_headers
    )
    assert applied.status_code == 200, applied.text
    counts = applied.json()["applied"]
    assert counts["universities"] >= 1
    assert counts["departments"] >= 1

    unis = (
        await client.get("/api/v1/universities?q=testing", headers=auth_headers)
    ).json()
    assert unis
    detail = (
        await client.get(f"/api/v1/universities/{unis[0]['id']}", headers=auth_headers)
    ).json()
    assert detail["departments"][0]["admissions"][0]["source"] == "document"


async def test_apply_twice_is_idempotent(client, db, auth_headers):
    content = "University of Idempotence\nSchool of Data — baseline 2025: 70 points\n".encode()
    upload = await _upload(client, auth_headers, "idem.txt", content)
    doc_id = upload.json()["document"]["id"]
    await _drain(db)
    await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    await client.post(f"/api/v1/documents/{doc_id}/apply", headers=auth_headers)
    second = await client.post(
        f"/api/v1/documents/{doc_id}/apply", headers=auth_headers
    )
    assert second.status_code == 200
    unis = (
        await client.get("/api/v1/universities?q=Idempotence", headers=auth_headers)
    ).json()
    assert len(unis) == 1
    detail = (
        await client.get(f"/api/v1/universities/{unis[0]['id']}", headers=auth_headers)
    ).json()
    assert len(detail["departments"]) == 1
    assert len(detail["departments"][0]["admissions"]) == 1


async def test_pdf_upload_accepted(client, db, auth_headers):
    response = await _upload(
        client,
        auth_headers,
        "catalog.pdf",
        _tiny_pdf("baseline 2025: 80"),
        "application/pdf",
    )
    assert response.status_code == 202
    await _drain(db)
    detail = await client.get(
        f"/api/v1/documents/{response.json()['document']['id']}", headers=auth_headers
    )
    assert detail.json()["mime"] == "application/pdf"


async def test_rejects_bad_mime(client, auth_headers):
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("x.png", io.BytesIO(b"binary"), "image/png")},
        headers=auth_headers,
    )
    assert response.status_code == 415


async def test_deadline_extracted_and_applied(client, db, auth_headers):
    content = (
        "University of Deadlines\n"
        "Application deadline: 2026-07-15\n"
        "School of Data Science — baseline 2025: 78 points quota 90\n"
    ).encode()
    upload = await _upload(client, auth_headers, "deadlines.txt", content)
    await _drain(db)
    detail = await client.get(
        f"/api/v1/documents/{upload.json()['document']['id']}", headers=auth_headers
    )
    body = detail.json()
    assert body["status"] == "parsed"
    dept = body["extraction"]["universities"][0]["departments"][0]
    assert dept["application_deadline"] == "2026-07-15"

    await client.post(f"/api/v1/documents/{body['id']}/apply", headers=auth_headers)
    unis = (
        await client.get("/api/v1/universities?q=Deadlines", headers=auth_headers)
    ).json()
    uni_detail = (
        await client.get(f"/api/v1/universities/{unis[0]['id']}", headers=auth_headers)
    ).json()
    assert uni_detail["departments"][0]["application_deadline"] == "2026-07-15"


async def test_deadline_manual_department(client, auth_headers):
    uni = (
        await client.post(
            "/api/v1/universities",
            json={"name": "Manual Uni", "country": "Greece"},
            headers=auth_headers,
        )
    ).json()
    dept = await client.post(
        f"/api/v1/universities/{uni['id']}/departments",
        json={"name": "School of Law", "application_deadline": "2026-05-01"},
        headers=auth_headers,
    )
    assert dept.status_code == 201
    assert dept.json()["application_deadline"] == "2026-05-01"


async def test_documents_are_private(client, auth_headers):
    upload = await _upload(client, auth_headers, "mine.txt", b"content")
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "other2@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    response = await client.get(
        f"/api/v1/documents/{upload.json()['document']['id']}", headers=other_headers
    )
    assert response.status_code == 404
