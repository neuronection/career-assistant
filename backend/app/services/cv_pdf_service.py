"""Server-side PDF rendering: headless Chromium via Playwright.

Capability-detected, never a hard dependency: when no Chromium-class browser
is reachable (lean self-hosts, stripped desktop installs), `html_to_pdf`
raises `PDFEngineUnavailable` and the export path degrades to the print-ready
HTML (the browser print dialog). Chromium is the same engine users print
with, so the PDF matches the on-screen preview exactly.

Engine resolution order (cached, retried after a failure):
  1. a `ms-playwright` browser tree shipped next to the frozen executable
     (Linux deb/AppImage bundles; an explicit `PLAYWRIGHT_BROWSERS_PATH`
     always wins),
  2. Playwright's default per-user install,
  3. the system Edge / Chrome browser via Playwright channels (Windows
     desktops ship Edge).

One lazily-launched Playwright driver + browser serves every render (export,
polish review, lint live-measure, copilot critique) and closes itself after
an idle period. The printed PDF is the only page-count truth: the PDF's own
page tree is counted via pypdfium2 and its pages rasterized exactly as
exported for the vision critique — margins and CSS print fragmentation
included. The renderer's line estimate is a fallback, never a gate.
"""

import asyncio
import io
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import pypdfium2 as pdfium

from app.core.errors import ValidationError


class PDFEngineUnavailable(ValidationError):
    """No Chromium-class browser is reachable on this host."""


# CSS px at 96dpi per page size (A4: 210x297mm, Letter: 216x279mm).
PAGE_PX: dict[str, tuple[int, int]] = {
    "a4": (794, 1123),
    "letter": (816, 1056),
}
MAX_SCREENSHOT_PAGES = 4
THUMBNAIL_MAX_WIDTH = 360
IDLE_SHUTDOWN_SECONDS = 300

# None = the bundled/default Playwright chromium; channels fall back to the
# system browser (Edge first — every supported Windows desktop has it).
_CHANNEL_CANDIDATES: tuple[Optional[str], ...] = (None, "msedge", "chrome")

_UNRESOLVED: object = object()
_PLAYWRIGHT: object = None
_PLAYWRIGHT_LOOP: asyncio.AbstractEventLoop | None = None
_BROWSER: object = None
_BROWSER_LOOP: asyncio.AbstractEventLoop | None = None
_BROWSER_CHANNEL: object = _UNRESOLVED
_ENGINE_LOCK: asyncio.Lock | None = None
_IDLE_HANDLE: asyncio.TimerHandle | None = None


@dataclass
class PageMeasure:
    """Ground-truth pagination of a rendered CV.

    `pages` is counted from the printed PDF (never clamped); `images` are
    the first printed pages rasterized exactly as exported, capped at
    `MAX_SCREENSHOT_PAGES` for the vision critique. `source` is "pdf" for a
    real measurement and None when nothing could be measured.
    """

    pages: Optional[int] = None
    source: Optional[str] = None
    images: list[tuple[str, bytes]] = field(default_factory=list)


def _bundled_browsers_path() -> Optional[str]:
    """Locate a `ms-playwright` tree shipped next to the frozen app.

    An explicit `PLAYWRIGHT_BROWSERS_PATH` always wins (Playwright reads it
    directly); otherwise look in the onefile extraction dir and next to the
    executable (onedir keeps datas in `_internal/`).
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return None
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    roots.extend([exe_dir, os.path.join(exe_dir, "_internal")])
    for root in roots:
        candidate = os.path.join(root, "ms-playwright")
        if os.path.isdir(candidate):
            return candidate
    return None


def _engine_lock() -> asyncio.Lock:
    global _ENGINE_LOCK
    if _ENGINE_LOCK is None:
        _ENGINE_LOCK = asyncio.Lock()
    return _ENGINE_LOCK


async def _get_playwright() -> object:
    """The persistent Playwright driver, started lazily and reused.

    The bundled browsers path must be resolved before the driver starts —
    the node process inherits (and reads) the environment at spawn time.
    A driver bound to another event loop is abandoned, never reused.
    """
    global _PLAYWRIGHT, _PLAYWRIGHT_LOOP
    loop = asyncio.get_running_loop()
    if _PLAYWRIGHT is not None and _PLAYWRIGHT_LOOP is loop:
        return _PLAYWRIGHT
    stale, stale_loop = _PLAYWRIGHT, _PLAYWRIGHT_LOOP
    if stale is not None and stale_loop is not None and stale_loop.is_closed():
        try:
            await asyncio.wait_for(stale.stop(), timeout=10)
        except Exception:  # noqa: BLE001 — a closed loop's driver is unreachable
            pass
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001 - optional dependency
        raise PDFEngineUnavailable(
            "Server PDF engine not installed — use the print view instead"
        ) from exc
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        bundled = _bundled_browsers_path()
        if bundled:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled
    _PLAYWRIGHT = await async_playwright().start()
    _PLAYWRIGHT_LOOP = loop
    return _PLAYWRIGHT


async def _launch_browser(p) -> object:
    """Launch with the resolved options; None channel first, then system
    browsers. A cached channel is trusted until a launch fails."""
    global _BROWSER_CHANNEL
    channels = (
        (_BROWSER_CHANNEL,)
        if _BROWSER_CHANNEL is not _UNRESOLVED
        else _CHANNEL_CANDIDATES
    )
    last_error: Optional[Exception] = None
    for channel in channels:
        kwargs: dict = {"args": ["--disable-dev-shm-usage"]}
        if channel:
            kwargs["channel"] = channel
        try:
            browser = await p.chromium.launch(**kwargs)
            _BROWSER_CHANNEL = channel
            try:
                browser.on("disconnected", _on_browser_disconnected)
            except Exception:  # noqa: BLE001 — duck-typed engines may not emit
                pass
            return browser
        except Exception as exc:  # noqa: BLE001 — try the next candidate
            last_error = exc
    _BROWSER_CHANNEL = _UNRESOLVED
    raise PDFEngineUnavailable(f"No Chromium-class browser launched: {last_error}")


async def _get_browser(p) -> object:
    """The persistent engine browser, launched lazily and reused.

    A browser bound to another event loop (test suites, embedded shells) is
    abandoned rather than reused — cross-loop use is undefined in Playwright.
    """
    global _BROWSER, _BROWSER_LOOP, _IDLE_HANDLE
    loop = asyncio.get_running_loop()
    if _BROWSER is not None and _BROWSER_LOOP is loop:
        if _IDLE_HANDLE is not None:
            _IDLE_HANDLE.cancel()
            _IDLE_HANDLE = None
        return _BROWSER
    stale, stale_loop = _BROWSER, _BROWSER_LOOP
    _BROWSER = None
    _BROWSER_LOOP = loop
    if stale is not None and stale_loop is not None and stale_loop.is_closed():
        try:
            await asyncio.wait_for(stale.close(), timeout=10)
        except Exception:  # noqa: BLE001 — a closed loop's browser is unreachable
            pass
    _BROWSER = await _launch_browser(p)
    return _BROWSER


def _on_browser_disconnected(browser: object) -> None:
    """Drop a dead browser from the cache the moment it disconnects.

    Without this, the next render reuses the closed handle and raises
    `TargetClosedError` — which drops it again, leaking the process."""
    global _BROWSER, _BROWSER_CHANNEL
    if _BROWSER is browser:
        _BROWSER = None
        _BROWSER_CHANNEL = _UNRESOLVED


async def _discard_browser() -> None:
    """Remove the cached browser AND close it so its process never leaks.

    A dead/flaky browser dropped by the retry path used to be forgotten
    without a `close()`, so every failed render left a zombie Chromium
    tree behind — enough failures wedged the host and later renders hung
    on `new_page`."""
    global _BROWSER, _BROWSER_CHANNEL
    async with _engine_lock():
        browser, _BROWSER = _BROWSER, None
        _BROWSER_CHANNEL = _UNRESOLVED
    if browser is None:
        return
    try:
        await asyncio.wait_for(browser.close(), timeout=10)
    except Exception:  # noqa: BLE001 — best-effort cleanup, never mask the render error
        pass


def _schedule_idle_close() -> None:
    """Close the browser after a quiet period — desktop RAM stays free."""
    global _IDLE_HANDLE
    if _IDLE_HANDLE is not None:
        _IDLE_HANDLE.cancel()
        _IDLE_HANDLE = None

    async def _close() -> None:
        await _discard_browser()

    loop = asyncio.get_running_loop()
    _IDLE_HANDLE = loop.call_later(
        IDLE_SHUTDOWN_SECONDS, lambda: asyncio.create_task(_close())
    )


async def shutdown_engine() -> None:
    """Close the browser and the driver (app shutdown)."""
    global _PLAYWRIGHT, _PLAYWRIGHT_LOOP, _BROWSER, _BROWSER_CHANNEL, _IDLE_HANDLE
    if _IDLE_HANDLE is not None:
        _IDLE_HANDLE.cancel()
        _IDLE_HANDLE = None
    async with _engine_lock():
        browser, playwright = _BROWSER, _PLAYWRIGHT
        _BROWSER = None
        _BROWSER_CHANNEL = _UNRESOLVED
        _PLAYWRIGHT = None
        _PLAYWRIGHT_LOOP = None
        try:
            if browser is not None:
                await browser.close()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass
        try:
            if playwright is not None:
                await playwright.stop()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass


async def _render_page(html: str) -> bytes:
    """Print one HTML document to PDF bytes through the persistent browser."""
    p = await _get_playwright()
    async with _engine_lock():
        browser = await _get_browser(p)
    try:
        page = await browser.new_page()
        try:
            await page.set_content(html, wait_until="load")
            try:
                await page.evaluate("document.fonts && document.fonts.ready")
            except Exception:  # noqa: BLE001 — fonts are best-effort
                pass
            await page.emulate_media(media="print")
            return await page.pdf(prefer_css_page_size=True, print_background=True)
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001 — a dead browser must not mask errors
                pass
    finally:
        _schedule_idle_close()


async def html_to_pdf(html: str) -> bytes:
    """Render print-ready CV HTML to PDF bytes (A4/Letter via @page).

    Retried once with a fresh browser — a flaky launch or a dead cached
    browser must not degrade a page-count gate to the renderer estimate.
    """
    last_error: Optional[Exception] = None
    for attempt in (0, 1):
        try:
            return await _render_page(html)
        except PDFEngineUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — engine failures degrade cleanly
            last_error = exc
            await _discard_browser()
            if attempt:
                break
    raise PDFEngineUnavailable(
        f"Server PDF rendering failed on this host: {last_error}"
    ) from last_error


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


def count_pdf_pages(pdf: bytes) -> int | None:
    """The canonical page counter: the PDF's own page tree via pdfium.

    Never clamped, never estimated. Falls back to the regex parse when
    pdfium cannot open the bytes; None when nothing could be read.
    """
    try:
        return len(pdfium.PdfDocument(pdf))
    except Exception:  # noqa: BLE001 — malformed bytes fall to the regex
        return pdf_page_count(pdf)


def _render_pdf_page_images(pdf: bytes, limit: int) -> list[tuple[str, bytes]]:
    """Rasterize the first `limit` printed pages exactly as exported."""
    images: list[tuple[str, bytes]] = []
    document = pdfium.PdfDocument(pdf)
    try:
        for index in range(min(limit, len(document))):
            page = document[index]
            bitmap = page.render(scale=1.5)
            buffer = io.BytesIO()
            bitmap.to_pil().save(buffer, format="PNG")
            images.append(("image/png", buffer.getvalue()))
            page.close()
    finally:
        document.close()
    return images


async def measure_pages(
    html: str, page_size: str = "a4", max_images: int = MAX_SCREENSHOT_PAGES
) -> PageMeasure:
    """Ground-truth pagination: print the HTML once, then count and rasterize.

    The count comes from the printed PDF's page tree — margins and CSS print
    fragmentation included — so it is exactly what an export produces.
    `max_images` caps only the vision-critique page images, never the count.
    """
    pdf = await html_to_pdf(html)
    pages = count_pdf_pages(pdf)
    if pages is None:
        return PageMeasure(None, None, [])
    images = _render_pdf_page_images(pdf, max_images) if max_images > 0 else []
    return PageMeasure(pages, "pdf", images)


def thumbnail_image(
    png: bytes, max_width: int = THUMBNAIL_MAX_WIDTH
) -> tuple[str, bytes]:
    """Downscale a rasterized page PNG to listing-card width.

    Never upscales: pages already narrower than the cap pass through.
    Resampling from the 1.5× render keeps small text readable at card
    size; never clamped, never a hard engine dependency (callers pass
    bytes they already hold).
    """
    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        if image.width <= max_width:
            return "image/png", png
        height = max(1, round(image.height * max_width / image.width))
        resized = image.resize((max_width, height), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        resized.save(buffer, format="PNG")
        return "image/png", buffer.getvalue()


async def engine_check() -> tuple[bool, str]:
    """Render a trivial one-page document through the full engine path.

    Used by `careerassistant enginecheck` and release smokes: a healthy
    engine prints and counts exactly one page. The engine is shut down on
    the way out — the CLI runs this under a throwaway `asyncio.run` loop,
    and an unstopped driver transport complains after that loop closes.
    """
    try:
        measure = await measure_pages(
            "<html><body><p>engine check</p></body></html>", max_images=0
        )
        if measure.pages != 1:
            return False, f"engine rendered {measure.pages} pages (expected 1)"
        channel = (
            "system browser" if _BROWSER_CHANNEL else "bundled playwright chromium"
        )
        return True, f"PDF engine healthy ({channel}, 1 page)"
    except PDFEngineUnavailable as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 — any failure is a red check
        return False, f"engine check failed: {exc}"
    finally:
        try:
            await shutdown_engine()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass


def run_async(coro):  # pragma: no cover - event-loop glue for sync contexts
    return asyncio.run(coro)
