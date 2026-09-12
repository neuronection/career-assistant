"""Server-side PDF rendering: headless Chromium via Playwright.

Capability-detected, never a hard dependency: when Chromium is
unavailable (desktop installs, lean self-hosts), `html_to_pdf` raises
`PDFEngineUnavailable` and the export path degrades to the print-ready
HTML (the browser print dialog). Chromium is the same engine users
print with, so the PDF matches the on-screen preview exactly.
"""

import asyncio
import math

from app.core.errors import ValidationError


class PDFEngineUnavailable(ValidationError):
    """Chromium/Playwright is not available on this host."""


# CSS px at 96dpi per page size (A4: 210x297mm, Letter: 216x279mm).
PAGE_PX: dict[str, tuple[int, int]] = {
    "a4": (794, 1123),
    "letter": (816, 1056),
}
MAX_SCREENSHOT_PAGES = 4


def pdf_engine_available() -> bool:
    """True when a headless Chromium can actually launch here."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001 - optional dependency
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
            return True
    except Exception:  # noqa: BLE001 - browser not installed / OS unsupported
        return False


async def html_to_pdf(html: str) -> bytes:
    """Render print-ready CV HTML to PDF bytes (A4/Letter via @page)."""
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001 - optional dependency
        raise PDFEngineUnavailable(
            "Server PDF engine not installed — use the print view instead"
        ) from exc
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(html, wait_until="load")
                await page.emulate_media(media="print")
                return await page.pdf(prefer_css_page_size=True, print_background=True)
            finally:
                await browser.close()
    except PDFEngineUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - engine failures degrade cleanly
        raise PDFEngineUnavailable(
            f"Server PDF rendering failed on this host: {exc}"
        ) from exc


def pdf_page_count(pdf: bytes) -> int | None:
    """Actual page count of a PDF as printed (no rendering engine needed).

    Reads the uncompressed page-tree `Count` from the PDF structure —
    Chromium serializes those objects plainly, so the count matches what
    the viewer shows. Falls back to None when the structure isn't
    readable (never guess at a page count).
    """
    import re

    counts = [
        int(match.group(1))
        for match in re.finditer(rb"/Type\s*/Pages[^>]*?/Count\s+(\d+)", pdf)
        or re.finditer(rb"/Type\s*/Pages\s*/Parent[^>]*?/Count\s+(\d+)", pdf)
    ]
    if not counts:
        return None
    return max(counts)


async def html_to_pngs(
    html: str, page_size: str = "a4", max_pages: int = MAX_SCREENSHOT_PAGES
) -> list[tuple[str, bytes]]:
    """Render print-ready CV HTML to one PNG per page.

    The visual-feedback path for the CV builder copilot: page-sized clips
    of the same print layout Chromium prints, so the assistant critiques
    what the user actually sees. Capability-detected like `html_to_pdf`.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001 - optional dependency
        raise PDFEngineUnavailable(
            "Server PDF engine not installed — visual review is unavailable"
        ) from exc
    width, height = PAGE_PX.get(page_size, PAGE_PX["a4"])
    pages = max(1, min(max_pages, MAX_SCREENSHOT_PAGES))
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page(
                    viewport={"width": width, "height": height}
                )
                await page.set_content(html, wait_until="load")
                await page.emulate_media(media="print")
                scroll_height = await page.evaluate("document.body.scrollHeight")
                count = max(1, min(pages, math.ceil(scroll_height / height)))
                shots: list[tuple[str, bytes]] = []
                for index in range(count):
                    clip = {
                        "x": 0,
                        "y": index * height,
                        "width": width,
                        "height": height,
                    }
                    shots.append(("image/png", await page.screenshot(clip=clip)))
                return shots
            finally:
                await browser.close()
    except PDFEngineUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - engine failures degrade cleanly
        raise PDFEngineUnavailable(
            f"Server screenshot rendering failed on this host: {exc}"
        ) from exc


def run_async(coro):  # pragma: no cover - event-loop glue for sync contexts
    return asyncio.run(coro)
