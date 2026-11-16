"""Plan 212 S1.2 — the parser view: what OUR extractor sees.

The service prints the CV's current state through the export engine and
reads the printed PDF back with pypdfium2. These tests pin the
deterministic findings without a real browser: `html_to_pdf` is the seam
(the established `test_cv_export`/`test_cv_pdf_engine` pattern), and the
fixture PDFs are built with real text operators so pdfium's extraction
is exercised for single-column, two-column-interleaved and image-only
pages.
"""

import io
import uuid

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from app.services.cv.cv_parse_view_service import (
    CvParseViewService,
    _findings,
    extract_page_texts,
)
from app.services.cv.cv_pdf_service import PDFEngineUnavailable
from tests.conftest import session_headers


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _text_pdf(pages: list[list[str]]) -> bytes:
    """Fixture PDF: one text line per entry, top-down, via real `Tj`
    operators (a genuine text layer pdfium can extract)."""
    writer = PdfWriter()
    for lines in pages:
        page = writer.add_blank_page(width=595, height=842)
        parts = []
        y = 770
        for line in lines:
            parts.append(f"BT /F1 12 Tf 72 {y} Td ({_escape(line)}) Tj ET".encode())
            y -= 24
        content = b"\n".join(parts)
        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")
        resources = DictionaryObject()
        resources[NameObject("/Font")] = DictionaryObject({NameObject("/F1"): font})
        resources[NameObject("/ProcSet")] = ArrayObject([NameObject("/PDF"), NameObject("/Text")])
        page[NameObject("/Resources")] = resources
        stream = DecodedStreamObject()
        stream.set_data(content)
        stream.update({NameObject("/Length"): NumberObject(len(content))})
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _blank_pdf(pages: int) -> bytes:
    """Image-only fixture: pages exist but carry no text operators."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# ------------------------------------------------------- text extraction


def test_extract_page_texts_single_column():
    pdf = _text_pdf([["Experience", "Built the thing", "Shipped it"]])
    count, texts = extract_page_texts(pdf)
    assert count == 1
    assert len(texts) == 1
    assert "Built the thing" in texts[0]
    assert texts[0].index("Experience") < texts[0].index("Built the thing")


def test_extract_page_texts_two_columns_keeps_content_order():
    """A two-column page extracted in content order: the text is all
    there — the reading-order SUSPICION is a separate finding."""
    pdf = _text_pdf([["Skills", "SQL", "Experience", "Acme internship", "Education", "BSc CS"]])
    count, texts = extract_page_texts(pdf)
    assert count == 1
    for heading in ("Skills", "Experience", "Education"):
        assert heading in texts[0]


def test_extract_page_texts_image_only():
    count, texts = extract_page_texts(_blank_pdf(2))
    assert count == 2
    assert all(text.strip() == "" for text in texts)


def test_extract_caps_wire_pages_never_the_count():
    pdf = _text_pdf([["only page"]])
    count, texts = extract_page_texts(pdf)
    assert count == 1 and len(texts) == 1


# ------------------------------------------------------------- findings


def _payload(headings: list[str]) -> dict:
    """A version payload whose `items` blocks render (visible) with one
    heading each — the input the reading-order comparison reads."""
    blocks = [
        {"kind": "items", "props": {"title": heading.title(), "source_key": heading}}
        for heading in headings
    ]
    snapshot = {"basics": {}, **{heading: [{"title": heading}] for heading in headings}}
    return {"snapshot": snapshot, "blocks": blocks}


def test_findings_clean_cv_emits_none():
    pdf_pages = ["Experience", "Built the thing", "Education", "BSc CS"]
    findings = _findings(_payload(["experience", "education"]), None, pdf_pages, 1, 1)
    assert findings == []


def test_findings_reading_order_suspicion():
    """Headings appear in a different sequence than the rendered block
    order — the column reading-order suspicion."""
    texts = [
        "Experience",
        "Skills",
        "Education",
        "BSc CS",
    ]
    payload = _payload(["experience", "education", "skills"])
    findings = _findings(payload, None, texts, 1, 1)
    ids = [finding.id for finding in findings]
    assert "reading_order" in ids
    finding = next(f for f in findings if f.id == "reading_order")
    assert finding.level == "warn"
    assert "order" in finding.message.lower()


def test_findings_welded_lines():
    long_line = "welded " * 40  # > 200 chars, one span
    findings = _findings(_payload([]), None, ["Experience", long_line], 1, 1)
    welded = next(f for f in findings if f.id == "welded_lines")
    assert welded.level == "warn"
    assert "1 line" in welded.message


def test_findings_header_contact_did_not_survive():
    payload = {
        "snapshot": {"basics": {"email": "me@example.com", "phone": "+30 555 0100"}},
        "blocks": [],
    }
    findings = _findings(payload, None, ["Experience", "Built things"], 1, 1)
    contact = next(f for f in findings if f.id == "header_contact")
    assert contact.level == "warn"
    assert "email" in contact.message and "phone" in contact.message
    # Present contact (phone formatting ignored) emits nothing.
    assert _findings(payload, None, ["call +30 555 0100 or me@example.com"], 1, 1) == []


def test_findings_page_overflow_vs_budget():
    findings = _findings(_payload([]), None, ["page one", "page two"], 2, 1)
    overflow = next(f for f in findings if f.id == "page_overflow")
    assert overflow.level == "warn"
    assert "2 pages" in overflow.message and "1-page" in overflow.message


def test_findings_empty_page():
    findings = _findings(_payload([]), None, ["real text", "   "], 2, 2)
    empty = next(f for f in findings if f.id == "empty_page")
    assert empty.level == "warn"
    assert "2" in empty.message


def test_findings_no_text_layer_is_a_fail():
    # No text layer short-circuits the rest — the whole page set is
    # unreadable, so listing per-page empties adds nothing.
    findings = _findings(_payload([]), None, ["", " "], 2, 2)
    assert [finding.id for finding in findings] == ["text_layer"]
    assert findings[0].level == "fail"
    assert "no text layer" in findings[0].message.lower()


# ------------------------------------------------------------------ API


async def _built_cv(client, headers) -> dict:
    response = await client.put(
        "/api/v1/profile",
        json={
            "basics": {
                "birth_year": 2005,
                "education_level": "bachelor",
                "email": "me@example.com",
                "phone": "+30 555 0100",
            },
            "academics": {},
            "aspirations": [],
            "interests": [],
            "hobbies": [],
            "likes": [],
            "dislikes": [],
            "work_preferences": {},
            "constraints": {},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    created = await client.post("/api/v1/cv", json={"title": "Parser View CV"}, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()


async def test_parse_view_endpoint_contract(
    client, auth_headers, profile_ready, seeded_catalog, monkeypatch
):
    import app.services.cv.cv_parse_view_service as module

    async def _pdf(html: str) -> bytes:
        return _text_pdf(
            [["Junior Backend Developer", "me@example.com", "Experience", "Acme internship"]]
        )

    monkeypatch.setattr(module, "html_to_pdf", _pdf)
    cv = await _built_cv(client, auth_headers)
    response = await client.get(f"/api/v1/cv/{cv['id']}/parse-view", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "pdf"
    assert body["page_count"] == 1
    assert body["text_layer"] is True
    assert len(body["pages"]) == 1
    page = body["pages"][0]
    assert page["index"] == 0 and page["line_count"] == 4
    assert "Acme internship" in page["text"]
    # No vendor claims, no score anywhere on this surface.
    assert "score" not in body
    for finding in body["findings"]:
        assert set(finding) == {"id", "level", "message"}
        assert finding["level"] in ("info", "warn", "fail")
    # Read-only: no version was created by the view.
    versions = await client.get(f"/api/v1/cv/{cv['id']}/versions", headers=auth_headers)
    assert versions.json() == []


async def test_parse_view_flags_deviations_end_to_end(
    client, auth_headers, profile_ready, seeded_catalog, monkeypatch
):
    """The fixture text carries the sections in the wrong order and a
    welded line — the findings surface them on the wire."""
    import app.services.cv.cv_parse_view_service as module

    async def _pdf(html: str) -> bytes:
        return _text_pdf([["Education", "BSc CS", "Experience", "one long welded " * 30]])

    monkeypatch.setattr(module, "html_to_pdf", _pdf)
    created = await client.post(
        "/api/v1/me/experience",
        json={
            "title": "DevOps intern",
            "kind": "internship",
            "org_name": "Acme Cloud",
            "start": "2025-01-01",
            "end": "2025-12-31",
            "hours_per_week": 40,
            "description": "Deployed things.",
            "skills": [],
            "achievements": [],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    cv = await _built_cv(client, auth_headers)
    patched = await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "blocks": [
                    {"kind": "header"},
                    {
                        "kind": "items",
                        "props": {"title": "Experience", "source_key": "experience"},
                    },
                    {
                        "kind": "custom_text",
                        "props": {"title": "Education", "text": "BSc CS"},
                    },
                ],
                "overrides": {},
            }
        },
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    response = await client.get(f"/api/v1/cv/{cv['id']}/parse-view", headers=auth_headers)
    assert response.status_code == 200, response.text
    ids = {finding["id"] for finding in response.json()["findings"]}
    assert "reading_order" in ids
    assert "welded_lines" in ids


async def test_parse_view_image_only_reports_no_text_layer(
    client, auth_headers, profile_ready, seeded_catalog, monkeypatch
):
    import app.services.cv.cv_parse_view_service as module

    async def _pdf(html: str) -> bytes:
        return _blank_pdf(1)

    monkeypatch.setattr(module, "html_to_pdf", _pdf)
    cv = await _built_cv(client, auth_headers)
    response = await client.get(f"/api/v1/cv/{cv['id']}/parse-view", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text_layer"] is False
    assert body["findings"][0]["id"] == "text_layer"
    assert body["findings"][0]["level"] == "fail"


async def test_parse_view_503_when_engine_unavailable(
    client, auth_headers, profile_ready, seeded_catalog, monkeypatch
):
    import app.services.cv.cv_parse_view_service as module

    async def _unavailable(html: str) -> bytes:
        raise PDFEngineUnavailable("Server PDF engine not installed — use the print view instead")

    monkeypatch.setattr(module, "html_to_pdf", _unavailable)
    cv = await _built_cv(client, auth_headers)
    response = await client.get(f"/api/v1/cv/{cv['id']}/parse-view", headers=auth_headers)
    assert response.status_code == 503, response.text
    assert "print" in response.json()["detail"].lower()


async def test_parse_view_is_ownership_checked(client, auth_headers, profile_ready, seeded_catalog):
    cv = await _built_cv(client, auth_headers)
    other = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"other-{uuid.uuid4().hex[:10]}@example.com",
            "password": "Str0ngPass!23",
            "full_name": "Other",
        },
    )
    headers = session_headers(other)
    response = await client.get(f"/api/v1/cv/{cv['id']}/parse-view", headers=headers)
    assert response.status_code == 404


async def test_service_build_uses_render_state_without_versions(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """The service path itself: render (no version), print, extract —
    and findings computed from the rendered payload."""
    import app.services.cv.cv_parse_view_service as module

    async def _pdf(html: str) -> bytes:
        return _text_pdf([["Experience", "Built the thing"]])

    monkeypatch.setattr(module, "html_to_pdf", _pdf)
    cv = await _built_cv(client, auth_headers)
    from sqlalchemy import select

    from app.models.cv_model import CvDocument

    row = (await db.execute(select(CvDocument).where(CvDocument.id == cv["id"]))).scalars().first()
    view = await CvParseViewService(db).build(row)
    assert view.page_count == 1 and view.text_layer is True
    assert view.engine == "pdf"
    assert [page.line_count for page in view.pages] == [2]
