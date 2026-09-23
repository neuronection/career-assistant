"""PDF-engine ground truth: the printed PDF is the page-count source.

Plan 76 — `measure_pages` prints the HTML once through Chromium, counts
the PDF's own page tree (never clamped) and rasterizes the exact printed
pages for the vision critique. These tests pin that contract without a
real browser: `html_to_pdf` is the seam.
"""

import io
import os
import sys
from pathlib import Path

import pytest

from app.services import cv_pdf_service as pdf_service
from app.services.cv_pdf_service import PDFEngineUnavailable


def _blank_pdf(pages: int) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _clean_engine_state():
    yield
    if pdf_service._IDLE_HANDLE is not None:
        pdf_service._IDLE_HANDLE.cancel()
    pdf_service._IDLE_HANDLE = None
    pdf_service._BROWSER = None
    pdf_service._BROWSER_LOOP = None
    pdf_service._PLAYWRIGHT = None
    pdf_service._PLAYWRIGHT_LOOP = None
    pdf_service._BROWSER_CHANNEL = pdf_service._UNRESOLVED


async def test_measure_pages_counts_the_printed_pdf(monkeypatch):
    async def _pdf(html: str) -> bytes:
        return _blank_pdf(3)

    monkeypatch.setattr(pdf_service, "html_to_pdf", _pdf)
    measure = await pdf_service.measure_pages("<html></html>")
    assert measure.pages == 3
    assert measure.source == "pdf"
    assert len(measure.images) == 3
    assert all(mime == "image/png" for mime, _ in measure.images)


async def test_measure_caps_images_but_never_the_count(monkeypatch):
    """A 6-page CV over a 4-image cap reports 6 pages and 4 images — the
    old screenshot path clamped the count itself and read 6 as 4."""

    async def _pdf(html: str) -> bytes:
        return _blank_pdf(6)

    monkeypatch.setattr(pdf_service, "html_to_pdf", _pdf)
    measure = await pdf_service.measure_pages("<html></html>")
    assert measure.pages == 6
    assert len(measure.images) == pdf_service.MAX_SCREENSHOT_PAGES


async def test_measure_without_images_skips_rasterization(monkeypatch):
    async def _pdf(html: str) -> bytes:
        return _blank_pdf(2)

    monkeypatch.setattr(pdf_service, "html_to_pdf", _pdf)
    measure = await pdf_service.measure_pages("<html></html>", max_images=0)
    assert measure.pages == 2
    assert measure.images == []


async def test_count_pdf_pages_falls_back_to_the_regex_parse():
    """pdfium cannot open non-PDF bytes; the page-tree regex still reads
    Chromium-serialized structures."""
    crafted = b"%PDF-1.4 /Type /Pages /Kids [..] /Count 7 trailer"
    assert pdf_service.count_pdf_pages(crafted) == 7
    assert pdf_service.count_pdf_pages(b"garbage") is None


async def test_engine_check_reports_health_and_failure(monkeypatch):
    async def _one_page(html: str) -> bytes:
        return _blank_pdf(1)

    monkeypatch.setattr(pdf_service, "html_to_pdf", _one_page)
    ok, detail = await pdf_service.engine_check()
    assert ok, detail
    assert "1 page" in detail

    async def _unavailable(html: str) -> bytes:
        raise PDFEngineUnavailable("no browser")

    monkeypatch.setattr(pdf_service, "html_to_pdf", _unavailable)
    ok, detail = await pdf_service.engine_check()
    assert not ok
    assert "no browser" in detail


async def test_html_to_pdf_drops_a_dead_browser_and_retries(monkeypatch):
    """A cached browser dying mid-flight must not fail the render — the
    retry relaunches (channel resolution resets)."""

    class _Page:
        def __init__(self, fail: bool):
            self._fail = fail

        async def set_content(self, *args, **kwargs):
            if self._fail:
                raise RuntimeError("Target closed")

        async def evaluate(self, *args, **kwargs):
            return None

        async def emulate_media(self, *args, **kwargs):
            return None

        async def pdf(self, **kwargs):
            return _blank_pdf(1)

        async def close(self):
            return None

    class _Browser:
        def __init__(self):
            self.calls = 0

        async def new_page(self):
            self.calls += 1
            return _Page(fail=self.calls == 1)

        async def close(self):
            return None

    class _Chromium:
        def __init__(self):
            self.browser = _Browser()

        async def launch(self, **kwargs):
            return self.browser

    class _Playwright:
        def __init__(self):
            self.chromium = _Chromium()

    playwright = _Playwright()

    async def _fake_get_playwright():
        return playwright

    monkeypatch.setattr(pdf_service, "_get_playwright", _fake_get_playwright)
    pdf_bytes = await pdf_service.html_to_pdf("<html></html>")
    assert pdf_service.count_pdf_pages(pdf_bytes) == 1
    assert playwright.chromium.browser.calls == 2, "the dead page was retried"


async def test_failed_render_closes_every_discarded_browser(monkeypatch):
    """A dead/flaky browser is CLOSED, not merely forgotten — the old
    `_drop_browser` leaked a Chromium process on every failure, which
    eventually wedged the host and hung later renders on `new_page`."""

    class _Browser:
        def __init__(self):
            self.closes = 0

        async def new_page(self):
            raise RuntimeError("Target closed")

        async def close(self):
            self.closes += 1

    launched: list[_Browser] = []

    class _Chromium:
        async def launch(self, **kwargs):
            browser = _Browser()
            launched.append(browser)
            return browser

    class _Playwright:
        chromium = _Chromium()

    async def _fake_get_playwright():
        return _Playwright()

    monkeypatch.setattr(pdf_service, "_get_playwright", _fake_get_playwright)
    with pytest.raises(PDFEngineUnavailable):
        await pdf_service.html_to_pdf("<html></html>")

    assert len(launched) == 2, "the dead browser was retried once"
    assert all(browser.closes == 1 for browser in launched), (
        "each discarded browser must be closed so its process cannot leak"
    )
    assert pdf_service._BROWSER is None
    assert pdf_service._BROWSER_CHANNEL is pdf_service._UNRESOLVED


def test_disconnected_browser_is_evicted_from_the_cache():
    """A disconnect clears the cache only for the browser it happened to —
    so the next render relaunches instead of reusing a closed handle."""
    sentinel = object()
    other = object()
    pdf_service._BROWSER = sentinel
    pdf_service._BROWSER_CHANNEL = None

    pdf_service._on_browser_disconnected(other)
    assert pdf_service._BROWSER is sentinel

    pdf_service._on_browser_disconnected(sentinel)
    assert pdf_service._BROWSER is None
    assert pdf_service._BROWSER_CHANNEL is pdf_service._UNRESOLVED


def test_bundled_browsers_path_prefers_env_and_frozen_layout(monkeypatch, tmp_path):
    bundled = tmp_path / "ms-playwright"
    bundled.mkdir()
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "careerassistant"))
    monkeypatch.setattr(sys, "_MEIPASS", None, raising=False)
    assert pdf_service._bundled_browsers_path() == str(bundled)

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/custom/path")
    assert pdf_service._bundled_browsers_path() is None


def test_bundled_browsers_path_checks_the_internal_layout(monkeypatch, tmp_path):
    internal = tmp_path / "_internal" / "ms-playwright"
    internal.mkdir(parents=True)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "careerassistant"))
    monkeypatch.setattr(sys, "_MEIPASS", None, raising=False)
    assert pdf_service._bundled_browsers_path() == str(internal)


def test_page_overflow_message_carries_the_real_budget():
    from app.services.cv_export_service import lint

    report = lint(
        {"snapshot": {}, "blocks": []},
        "<html></html>",
        {"overflow": True, "estimated_pages": 3, "max_pages": 2},
        None,
    )
    overflow = next(c for c in report["checks"] if c["id"] == "page_overflow")
    assert "3 pages" in overflow["message"]
    assert "2-page budget" in overflow["message"]


def test_render_metrics_expose_max_pages():
    from app.services.cv_blocks import SAMPLE_SNAPSHOT
    from app.services.cv_builder_service import FALLBACK_CONTENT
    from app.services.cv_renderer import render_cv
    from app.schemas.cv_template import TemplateContent

    content = TemplateContent.model_validate(FALLBACK_CONTENT)
    result = render_cv(content, SAMPLE_SNAPSHOT, max_pages=2)
    assert result.metrics.max_pages == 2


def test_enginecheck_cli_exits_zero_on_a_healthy_engine(monkeypatch):
    from careerassistant.__main__ import main

    async def _one_page(html: str) -> bytes:
        return _blank_pdf(1)

    monkeypatch.setattr(pdf_service, "html_to_pdf", _one_page)
    assert main(["enginecheck"]) == 0

    async def _unavailable(html: str) -> bytes:
        raise PDFEngineUnavailable("none")

    monkeypatch.setattr(pdf_service, "html_to_pdf", _unavailable)
    assert main(["enginecheck"]) == 1


def test_frozen_env_untouched_without_bundled_tree(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(sys, "_MEIPASS", None, raising=False)
    (tmp_path / "python").write_text("")
    assert pdf_service._bundled_browsers_path() is None
    assert os.environ.get("PLAYWRIGHT_BROWSERS_PATH") is None


def test_running_footer_reaches_printed_pdf_page_2():
    """Margin-box counters land in the printed PDF's own page 2 text
    (the engine is the page-count truth per plan 76). Skips cleanly on
    hosts without any Chromium-class engine — the degradation is honest
    (fixed-footer fallback emits no numbers)."""
    import asyncio

    import pypdfium2 as pdfium

    from app.services.cv_pdf_service import (
        PDFEngineUnavailable,
        html_to_pdf,
    )

    html = (
        "<!DOCTYPE html><html><head><style>"
        "@page { size: 210mm 297mm; margin: 15mm; "
        "@bottom-right { content: 'p' counter(page) '/' counter(pages); } }"
        ".pg { break-after: page; }"
        "</style></head><body><div class='pg'>ONE</div><div>TWO</div></body></html>"
    )
    try:
        pdf_bytes = asyncio.run(html_to_pdf(html))
    except (PDFEngineUnavailable, RuntimeError):
        pytest.skip("no PDF engine on this host")
    document = pdfium.PdfDocument(pdf_bytes)
    assert len(document) == 2
    page_two_text = ""
    textpage = document[1].get_textpage()
    if textpage is not None:
        page_two_text = textpage.get_text_bounded() or ""
    assert "p2/2" in page_two_text
