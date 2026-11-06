"""Web-search provider adapters (plan 122 Phase 2): pure request builders
and response normalizers over the guarded search transport.

The wire shapes mirror the family contract (``contracts/search-providers.json``
+ the dev canonical's fixture suite): SearXNG GET ``/search?format=json``,
Tavily POST ``/search`` (Bearer + body), Brave GET ``/web/search``
(``X-Subscription-Token``), Exa POST ``/search`` (``x-api-key``), Serper POST
``/search`` (``X-API-KEY``) and Google Programmable Search GET (``key`` +
``cx``). The transport is injected — production builds it through
:func:`app.extensions.runtime.http.build_search_transport` (SSRF/egress
guard, response caps, refused redirects); tests inject a recording fake.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urlencode

from app.extensions.polite_http import PoliteHttpError
from app.extensions.runtime.http import SearchTransport, build_search_transport

PROVIDER_TYPES = ("searxng", "tavily", "brave", "exa", "serper", "google_pse")
DEFAULT_BASE_URLS = {
    "tavily": "https://api.tavily.com",
    "brave": "https://api.search.brave.com/res/v1",
    "exa": "https://api.exa.ai",
    "serper": "https://google.serper.dev",
    "google_pse": "https://www.googleapis.com/customsearch/v1",
}
BASE_URL_REQUIRED = ("searxng",)
KEYED_TYPES = ("tavily", "brave", "exa", "serper", "google_pse")
CONTENT_MAX_CHARS = 800
LIST_KEYS = {
    "searxng": ("results",),
    "tavily": ("results",),
    "brave": ("web", "results"),
    "exa": ("results",),
    "serper": ("organic",),
    "google_pse": ("items",),
}
_TYPE_ALIASES = {"google-pse": "google_pse", "google_pse": "google_pse"}


def canonical_type(value: str) -> str:
    """Catalog ids use hyphens; the stored/canonical type uses underscores."""
    token = str(value or "").strip()
    return _TYPE_ALIASES.get(token, token)


@dataclass(frozen=True)
class SearchRequest:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    body: dict | None = None

    def full_url(self) -> str:
        if not self.params:
            return self.url
        separator = "&" if "?" in self.url else "?"
        return f"{self.url}{separator}{urlencode(self.params)}"


def build_request(provider: dict, query: str, api_key: str, limit: int) -> SearchRequest:
    """One provider's wire request (method, URL, headers, params, body)."""
    p_type = canonical_type(provider.get("type", ""))
    base = str(provider.get("base_url") or DEFAULT_BASE_URLS.get(p_type) or "").rstrip("/")
    if not base:
        raise ValueError("this provider needs a base URL")
    if p_type == "searxng":
        return SearchRequest(
            method="GET",
            url=f"{base}/search",
            headers={"Accept": "application/json"},
            params={"q": query, "format": "json"},
        )
    if p_type == "tavily":
        return SearchRequest(
            method="POST",
            url=f"{base}/search",
            headers={"Authorization": f"Bearer {api_key}"},
            body={"query": query, "max_results": limit, "api_key": api_key},
        )
    if p_type == "brave":
        return SearchRequest(
            method="GET",
            url=f"{base}/web/search",
            headers={"X-Subscription-Token": api_key},
            params={"q": query, "count": str(limit)},
        )
    if p_type == "exa":
        return SearchRequest(
            method="POST",
            url=f"{base}/search",
            headers={"x-api-key": api_key},
            body={
                "query": query,
                "numResults": limit,
                "contents": {"text": {"maxCharacters": 400}},
            },
        )
    if p_type == "serper":
        return SearchRequest(
            method="POST",
            url=f"{base}/search",
            headers={"X-API-KEY": api_key},
            body={"q": query, "num": limit},
        )
    if p_type == "google_pse":
        return SearchRequest(
            method="GET",
            url=base,
            headers={"Accept": "application/json"},
            params={
                "key": api_key,
                "cx": str(provider.get("google_cx") or ""),
                "q": query,
                "num": str(min(limit, 10)),
            },
        )
    raise ValueError(f"unknown search provider type '{p_type}'")


def _row_hit(row) -> dict[str, str] | None:
    if not isinstance(row, dict):
        return None
    url = str(row.get("url") or row.get("link") or "").strip()
    if not url:
        return None
    title = str(row.get("title") or "").strip() or url
    content = row.get("content")
    if content is None:
        content = row.get("snippet")
    if content is None:
        content = row.get("description")
    if content is None:
        content = row.get("text")
    return {"title": title, "url": url, "snippet": str(content or "").strip()[:CONTENT_MAX_CHARS]}


def parse_hits(provider_type: str, payload, limit: int) -> list[dict[str, str]]:
    """Normalized ``{title, url, snippet}`` hits from one provider payload."""
    p_type = canonical_type(provider_type)
    node = payload
    for key in LIST_KEYS[p_type]:
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, list):
        raise ValueError(f"search provider response missing '{LIST_KEYS[p_type][-1]}' list")
    hits = [hit for hit in (_row_hit(row) for row in node) if hit is not None]
    return hits[:limit]


def _error(status: str, detail: str) -> dict:
    return {"available": False, "status": status, "detail": detail[:300]}


def _polite_status(exc: PoliteHttpError) -> str:
    if exc.code == "auth":
        return "auth"
    if exc.code == "rate-limited":
        return "rate_limit"
    if exc.code in ("unreachable", "net-denied"):
        return "unreachable"
    if exc.code == "provider":
        return "protocol"
    return "error"


async def run_search(
    provider: dict,
    query: str,
    *,
    api_key: str = "",
    limit: int | None = None,
    transport: SearchTransport | None = None,
) -> dict:
    """Run one provider search; never raises, returns the typed status dict."""
    p_type = canonical_type(provider.get("type", ""))
    if p_type not in PROVIDER_TYPES:
        return _error("unknown_type", f"unknown search provider type '{p_type}'")
    text = str(query or "").strip()
    if not text:
        return _error("bad_request", "empty search query")
    effective_limit = int(limit if limit is not None else provider.get("max_results") or 5)
    effective_limit = max(1, min(effective_limit, 10))
    if p_type in KEYED_TYPES and not api_key:
        return _error(
            "missing_key",
            f"{provider.get('name') or p_type} needs an API key",
        )
    if p_type == "google_pse" and not str(provider.get("google_cx") or "").strip():
        return _error("missing_config", "Google Programmable Search needs an engine id (cx)")
    if p_type in BASE_URL_REQUIRED and not str(provider.get("base_url") or "").strip():
        return _error("missing_config", "this provider needs a base URL")
    try:
        request = build_request(provider, text, api_key, effective_limit)
    except ValueError as exc:
        return _error("missing_config", str(exc))
    guarded = transport or build_search_transport()
    try:
        response = await guarded(request.method, request.full_url(), request.headers, request.body)
    except PoliteHttpError as exc:
        return _error(_polite_status(exc), exc.detail)
    if response.status in (401, 403):
        return _error("auth", f"search provider rejected the request ({response.status})")
    if response.status == 429:
        return _error("rate_limit", "search provider rate limit hit (429)")
    if response.status != 200:
        return _error("protocol", f"search provider returned {response.status}")
    body = response.body or ""
    content_type = str(response.headers.get("content-type") or "")
    if "json" not in content_type and not body.lstrip().startswith(("{", "[")):
        hint = " (enable the `json` format on the SearXNG instance)" if p_type == "searxng" else ""
        return _error("json_disabled", "provider returned non-JSON output" + hint)
    try:
        payload = json.loads(body)
    except ValueError:
        return _error("protocol", "search provider returned non-JSON output")
    try:
        hits = parse_hits(p_type, payload, effective_limit)
    except ValueError as exc:
        return _error("protocol", str(exc))
    return {"available": True, "results": hits}


async def probe_provider(
    provider: dict, *, api_key: str = "", transport: SearchTransport | None = None
) -> dict:
    """One benign search, reported in the UI's probe vocabulary."""
    import time

    started = time.monotonic()
    result = await run_search(provider, "neuronection", api_key=api_key, transport=transport)
    latency = int((time.monotonic() - started) * 1000)
    if result.get("available"):
        return {
            "status": "ok",
            "latency_ms": latency,
            "result_count": len(result.get("results") or []),
            "error": None,
        }
    status = result.get("status", "error")
    if status in ("missing_key", "missing_config", "bad_request", "unknown_type"):
        status = "error"
    return {
        "status": status,
        "latency_ms": latency,
        "result_count": None,
        "error": result.get("detail") or status,
    }


__all__ = [
    "BASE_URL_REQUIRED",
    "CONTENT_MAX_CHARS",
    "DEFAULT_BASE_URLS",
    "KEYED_TYPES",
    "PROVIDER_TYPES",
    "SearchRequest",
    "build_request",
    "canonical_type",
    "parse_hits",
    "probe_provider",
    "run_search",
]
