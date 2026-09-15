"""Outbound web access for AI tools — fetch guard, HTML→text, SearXNG.

Single owner of the HTTP behavior behind the AI web tools (`app.ai.tools.web`):
a hardened, no-auto-redirect httpx client, the SSRF guard
(resolve-then-connect, reserved ranges blocked on every hop), size/time caps,
a stdlib HTML→text extractor, and the user-hosted SearXNG client (search +
probe). Fetched content is untrusted input downstream; this module only
normalizes and caps it — it never interprets instructions in it.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from enum import Enum
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import ParseResult, urlencode, urlparse

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MAX_REDIRECTS = 5
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
SCAN_LIMIT = 32_000
DEFAULT_TEXT_CAP = 8_000
HTML_TEXT_YIELD_THRESHOLD = 300

_UA = "Mozilla/5.0 (compatible; CareerAssistant/1.0; +https://neuronection.dev)"


class WebFetchBlocked(Exception):
    """The target is private/reserved or violates the fetch guard."""


class SearxngProbeStatus(str, Enum):
    OK = "ok"
    UNCONFIGURED = "unconfigured"
    UNREACHABLE = "unreachable"
    JSON_DISABLED = "json_disabled"
    ERROR = "error"


class WebFetchResult(BaseModel):
    """Normalized, capped result of one outbound fetch."""

    url: str
    status: int
    title: str = ""
    text: str = ""
    content_type: str = ""
    truncated: bool = False
    rendered: bool = False


_web_client: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    """One shared client: redirects manual (guard re-checks each hop)."""
    global _web_client
    if _web_client is None or _web_client.is_closed:
        _web_client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
            headers={"User-Agent": _UA},
        )
    return _web_client


async def close_web_client() -> None:
    global _web_client
    if _web_client is not None and not _web_client.is_closed:
        await _web_client.aclose()
    _web_client = None


def parse_web_url(raw: str) -> ParseResult:
    """Parse and validate an absolute URL; raises on anything private-ish."""
    parsed = urlparse((raw or "").strip())
    if parsed.scheme not in ("https", "http"):
        raise WebFetchBlocked(f"unsupported scheme in URL: {raw!r}")
    if not parsed.hostname:
        raise WebFetchBlocked(f"URL has no hostname: {raw!r}")
    if parsed.username or parsed.password:
        raise WebFetchBlocked("URLs with credentials are not allowed")
    return parsed


def _ip_reserved(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    extra_nets = [
        ipaddress.ip_network("169.254.169.254/32"),
        ipaddress.ip_network("100.64.0.0/10"),
        ipaddress.ip_network("198.18.0.0/15"),
    ]
    if any(ip in net for net in extra_nets):
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _resolve_host(host: str) -> list[str]:
    """All address strings for the host (test seam — no real DNS in tests)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    return [str(info[4][0]) for info in infos]


async def assert_public_url(hostname: str) -> None:
    """Resolve every address for the host; any reserved one blocks the fetch."""
    host = urlparse(f"https://{hostname}").hostname or hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    ip_strings = [str(literal)] if literal is not None else None
    if ip_strings is None:
        try:
            ip_strings = await _resolve_host(host)
        except OSError as exc:
            raise WebFetchBlocked(f"cannot resolve host {host!r}: {exc}") from exc
    ip_strings = [ip for ip in ip_strings if ip.strip()]
    if not ip_strings:
        raise WebFetchBlocked(f"no addresses for host {host!r}")
    ips = []
    for raw in ip_strings:
        try:
            ips.append(ipaddress.ip_address(raw))
        except ValueError:  # pragma: no cover — getaddrinfo returns valid IPs
            continue
    if not ips:
        raise WebFetchBlocked(f"no addresses for host {host!r}")
    for ip in ips:
        if _ip_reserved(ip):
            raise WebFetchBlocked(f"private or reserved address for {host!r}")


async def _guarded_get(
    url: str, *, headers: Optional[dict] = None
) -> tuple[httpx.Response, str]:
    """GET with the SSRF guard re-applied on every redirect hop."""
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        parsed = parse_web_url(current)
        await assert_public_url(parsed.hostname)
        try:
            resp = await _client().get(current, headers=headers)
        except httpx.TimeoutException as exc:
            raise WebFetchBlocked(f"fetch timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise WebFetchBlocked(f"fetch failed: {exc}") from exc
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location")
            if not location:
                raise WebFetchBlocked("redirect without location")
            current = _resolve_redirect(parsed, location)
            continue
        return resp, current
    raise WebFetchBlocked(f"too many redirects (>{MAX_REDIRECTS})")


def _resolve_redirect(base: ParseResult, location: str) -> str:
    target = urlparse(location)
    if target.scheme:
        return location
    path = target.path or base.path
    if not path.startswith("/"):
        path = "/" + path
    merged = base._replace(path=path, query=target.query, fragment=target.fragment)
    return merged.geturl()


class _TextExtractor(HTMLParser):
    """Title + readable text; script/style stripped, block tags add breaks."""

    START_BLOCK = frozenset(
        {
            "p",
            "div",
            "br",
            "li",
            "tr",
            "section",
            "article",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "footer",
            "nav",
            "table",
        }
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_level = 0
        self._in_title = False
        self.title = ""
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_level += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.START_BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_level:
            self._skip_level -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str):
        if self._skip_level:
            return
        if self._in_title:
            self.title += data
        elif data.strip():
            self.parts.append(data)

    def text(self) -> str:
        lines = []
        for line in "".join(self.parts).splitlines():
            stripped = " ".join(line.split())
            if stripped:
                lines.append(stripped)
        return "\n".join(lines)


def text_from_html(html: str) -> tuple[str, str]:
    """(title, text) — script/style removed, paragraphs joined; empty-safe."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html or "")
        extractor.close()
    except Exception:  # noqa: BLE001 — malformed HTML still degrades to text
        return "", " ".join((html or "").split())[:DEFAULT_TEXT_CAP]
    return " ".join(extractor.title.split()), extractor.text()


_SEARXNG_PROBE_TTL = 300
_probe_cache: dict = {}


def _searxng_base(url: str) -> str:
    return url.rstrip("/")


async def probe_searxng(url: Optional[str]) -> dict:
    """Cached probe statuses; the Search-API host needs `format: json`."""
    if not (url or "").strip():
        return {"status": SearxngProbeStatus.UNCONFIGURED.value}
    cached = _probe_cache.get(url)
    if cached and time.monotonic() - cached["at"] < _SEARXNG_PROBE_TTL:
        return cached["result"]
    try:
        resp = await _client().get(
            f"{_searxng_base(url)}/search",
            params={"q": "probe", "format": "json"},
        )
    except httpx.HTTPError as exc:
        result = {
            "status": SearxngProbeStatus.UNREACHABLE.value,
            "detail": str(exc)[:200],
        }
    else:
        if resp.status_code == 200 and isinstance(_json_body(resp), dict):
            result = {"status": SearxngProbeStatus.OK.value}
        elif resp.status_code in (403, 404, 425):
            result = {"status": SearxngProbeStatus.JSON_DISABLED.value}
        else:
            result = {
                "status": SearxngProbeStatus.ERROR.value,
                "status_code": resp.status_code,
            }
    _probe_cache[url] = {"at": time.monotonic(), "result": result}
    return result


def _json_body(resp: httpx.Response):
    try:
        return resp.json()
    except ValueError:
        return None


async def search_web(url: Optional[str], query: str, n: int) -> dict:
    """SearXNG JSON search; structured-unavailable on every failure mode."""
    probe = await probe_searxng(url)
    status = probe.get("status")
    if status != SearxngProbeStatus.OK.value:
        return {"available": False, **probe}
    try:
        resp = await _client().get(
            f"{_searxng_base(url)}/search",
            params={"q": query, "format": "json", "pageno": 1, "safesearch": 1},
        )
        data = _json_body(resp)
        if resp.status_code != 200 or not isinstance(data, dict):
            return {"available": False, "status": SearxngProbeStatus.UNREACHABLE.value}
    except httpx.HTTPError as exc:
        return {
            "available": False,
            "status": SearxngProbeStatus.UNREACHABLE.value,
            "detail": str(exc)[:200],
        }
    hits = []
    for row in (data.get("results") or [])[:n]:
        if not isinstance(row, dict) or not row.get("url"):
            continue
        hits.append(
            {
                "title": str(row.get("title") or "")[:200],
                "url": str(row.get("url"))[:500],
                "snippet": str(row.get("content") or "")[:400],
            }
        )
    return {"available": True, "results": hits}


async def fetch_text(
    url: str, *, max_text: int = DEFAULT_TEXT_CAP, headers: Optional[dict] = None
) -> WebFetchResult:
    """Guarded, capped fetch; HTML bodies are reduced to title + text."""
    resp, final_url = await _guarded_get(url, headers=headers)
    ctype = resp.headers.get("content-type", "application/octet-stream").split(";")[0]
    raw = b""
    truncated = False
    async for chunk in resp.aiter_bytes():
        if len(raw) + len(chunk) > SCAN_LIMIT:
            raw += chunk[: max(0, SCAN_LIMIT - len(raw))]
            truncated = True
            break
        raw += chunk
    text = ""
    title = ""
    if "html" in ctype:
        title, text = text_from_html(
            raw.decode(resp.encoding or "utf-8", errors="replace")
        )
    else:
        text = " ".join(raw.decode("utf-8", errors="replace").split())
    if len(text) > max_text:
        text = text[:max_text]
        truncated = True
    return WebFetchResult(
        url=final_url,
        status=resp.status_code,
        title=title,
        text=text,
        content_type=ctype,
        truncated=truncated,
    )


async def render_text(url: str, *, page_timeout: float = 15.0) -> WebFetchResult:
    """Playwright tier — reuse the plan-76 persistent engine browser.

    Raises PDFEngineUnavailable when no engine is present (callers fall
    back to the plain fetch and mark ``rendered: false``).
    """
    from app.services.cv_pdf_service import (
        _get_browser,
        _get_playwright,
        _schedule_idle_close,
    )

    parse_web_url(url)
    await assert_public_url(urlparse(url).hostname)
    p = await _get_playwright()
    browser = await _get_browser(p)
    page = await browser.new_page()
    try:
        await page.goto(url, timeout=page_timeout * 1000, wait_until="domcontentloaded")
        title = str(await page.title() or "")
        text = str(await page.evaluate("document.body ? document.body.innerText : ''"))
    finally:
        await page.close()
        _schedule_idle_close()
    text = text or ""
    if len(text) > DEFAULT_TEXT_CAP:
        text = text[:DEFAULT_TEXT_CAP]
    return WebFetchResult(
        url=url,
        status=200,
        title=title,
        text=text,
        content_type="text/html",
        truncated=bool(len(text) >= DEFAULT_TEXT_CAP),
        rendered=True,
    )


def searxng_search_params(base: str, query: str) -> str:
    """Test-visible URL builder (mirrors the real request param order)."""
    return f"{_searxng_base(base)}/search?{urlencode({'q': query, 'format': 'json'})}"
