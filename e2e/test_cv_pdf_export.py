"""CV PDF export: the builder's Download → PDF writes a real PDF.

The server-side Chromium engine is optional (capability detection, never a
hard dependency): the spec probes the render path first and skips when the
host has no engine, exactly like the unit suite does.
"""

import pytest
from conftest import API, BASE_URL, api_headers
from playwright.sync_api import expect


def test_cv_pdf_export_downloads_pdf(page) -> None:
    created = page.request.post(
        f"{API}/cv",
        data={"title": "E2E PDF Export", "kind": "resume"},
        headers=api_headers(),
    )
    assert created.ok, created.text()
    cv_id = created.json()["id"]

    probe = page.request.get(f"{API}/cv/{cv_id}/preview.png", headers=api_headers())
    if probe.status == 503:
        pytest.skip(f"no server PDF engine on this host: {probe.text()[:120]}")

    page.goto(f"{BASE_URL}/cv/{cv_id}")
    expect(page.get_by_test_id("cv-builder")).to_be_visible(timeout=30_000)

    page.get_by_test_id("export-dropdown").click()
    with page.expect_download(timeout=120_000) as download_info:
        page.get_by_test_id("export-item-pdf").click()
    download = download_info.value
    assert download.suggested_filename.endswith(".pdf")
    path = download.path()
    assert path is not None
    with open(path, "rb") as handle:
        assert handle.read(4) == b"%PDF"
