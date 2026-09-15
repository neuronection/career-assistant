"""webfetch service — SSRF guard, HTML→text, caps, SearXNG probe/search."""

import httpx
import pytest

from app.services import webfetch
from app.services.webfetch import (
    WebFetchBlocked,
    assert_public_url,
    fetch_text,
    parse_web_url,
    probe_searxng,
    search_web,
    text_from_html,
)


class FakeResponse:
    def __init__(
        self, status_code=200, content=b"", json_data=None, headers=None, encoding=None
    ):
        self.status_code = status_code
        self._content = content
        self._json_data = json_data
        self.headers = headers or {}
        self.encoding = encoding

    @property
    def content_type(self):
        return self.headers.get("content-type", "").split(";")[0]

    async def aiter_bytes(self):
        yield self._content

    def json(self):
        if self._json_data is None:
            raise ValueError("not json")
        return self._json_data


async def _reset(routes, url, params=None, headers=None):
    if callable(routes):
        return routes(url, params, headers)
    return routes


def _route(monkeypatch, pattern, response=None):
    """httpx client stand-in; `pattern` may be str or {pattern: response}."""
    if isinstance(pattern, dict):
        return _routes(monkeypatch, pattern)
    return _routes(monkeypatch, {pattern: response})


def _routes(monkeypatch, routes: dict):
    calls = []

    client = type("FakeClient", (), {})()
    client.is_closed = False

    async def get(url, params=None, headers=None):
        calls.append((url, dict(params or {}), dict(headers or {})))
        target = routes.get("placeholder.example")
        for key, resp in routes.items():
            if key in url:
                target = resp
                break
        else:
            raise AssertionError(f"unexpected URL {url!r}")
        if callable(target):
            return target(url, params, headers)
        return target

    client.get = get
    monkeypatch.setattr(webfetch, "_client", lambda: client)
    return calls


async def _resolve(table, host):
    value = table.get(host, table.get("*"))
    if value is None:
        raise OSError(f"no entry for {host}")
    return value


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """Hosts resolve to 93.184.216.34 unless a test overrides the table."""
    monkeypatch.setattr(
        webfetch, "_resolve_host", lambda host: _resolve({"*": ["93.184.216.34"]}, host)
    )
    monkeypatch.setattr(webfetch, "_probe_cache", {})
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ip",
    [
        "127.1.1.1",
        "10.0.0.5",
        "192.168.1.4",
        "172.20.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "100.64.0.10",
        "198.18.5.5",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
    ],
)
async def test_guard_blocks_reserved_addresses(monkeypatch, ip):
    monkeypatch.setattr(
        webfetch, "_resolve_host", lambda host: _resolve({host: [ip]}, host)
    )
    with pytest.raises(WebFetchBlocked):
        await assert_public_url("placeholder.example")


@pytest.mark.asyncio
async def test_guard_blocks_mixed_resolutions(monkeypatch):
    table = {"dual.example": ["93.184.216.5", "192.168.0.99"]}
    monkeypatch.setattr(webfetch, "_resolve_host", lambda host: _resolve(table, host))
    with pytest.raises(WebFetchBlocked):
        await assert_public_url("dual.example")


@pytest.mark.asyncio
async def test_guard_allows_public():
    await assert_public_url("placeholder.example")


def test_parse_web_url_rejects_credentials_and_scheme():
    with pytest.raises(WebFetchBlocked):
        parse_web_url("ftp://example.com/x")
    with pytest.raises(WebFetchBlocked):
        parse_web_url("https://user:pass@example.com/x")
    with pytest.raises(WebFetchBlocked):
        parse_web_url("not a url")


HTML = (
    "<html><head><title>Hello</title><style>a{}</style></head>"
    "<body><script>alert(1)</script><p>Hello <b>world</b></p><p>Second</p></html>"
)


def test_text_from_html_strips_scripts_and_styles():
    title, text = text_from_html(HTML)
    assert title == "Hello"
    assert "alert" not in text
    assert text == "Hello world\nSecond"


def test_text_from_html_malformed_is_safe():
    _title, text = text_from_html("<html><div>u<tbody>")
    assert "u" in text


@pytest.mark.asyncio
async def test_fetch_text_caps_and_truncates(monkeypatch):
    page = FakeResponse(
        content=HTML.encode(), headers={"content-type": "text/html; charset=utf-8"}
    )
    _route(monkeypatch, "placeholder.example", page)
    result = await fetch_text("https://placeholder.example/page", max_text=8)
    assert result.status == 200
    assert result.title == "Hello"
    assert result.truncated is True
    assert len(result.text) <= 8


@pytest.mark.asyncio
async def test_fetch_text_plain_content_type(monkeypatch):
    _route(
        monkeypatch,
        "placeholder.example",
        FakeResponse(
            content=b"plain body text", headers={"content-type": "text/plain"}
        ),
    )
    result = await fetch_text("https://placeholder.example/file.txt")
    assert result.text == "plain body text"
    assert result.truncated is False


@pytest.mark.asyncio
async def test_fetch_scan_limit_truncates_bytes(monkeypatch):
    huge = b"x" * (webfetch.SCAN_LIMIT + 100)
    _route(
        monkeypatch,
        "placeholder.example",
        FakeResponse(content=huge, headers={"content-type": "text/plain"}),
    )
    result = await fetch_text("https://placeholder.example/big")
    assert result.truncated is True


@pytest.mark.asyncio
async def test_probe_statuses(monkeypatch):
    _route(
        monkeypatch,
        {
            "searx1": FakeResponse(json_data={"results": []}),
            "searx2": FakeResponse(status_code=403, content=b"Forbidden"),
        },
    )
    boom = type("Boom", (), {})()
    boom.is_closed = False

    async def down(*_a, **_k):
        raise httpx.ConnectError("down")

    boom.get = down

    assert (await probe_searxng(None))["status"] == "unconfigured"
    assert (await probe_searxng("https://searx1.example"))["status"] == "ok"
    assert (await probe_searxng("https://searx2.example"))["status"] == "json_disabled"
    monkeypatch.setattr(webfetch, "_client", lambda: boom)
    assert (await probe_searxng("https://searx3.example"))["status"] == "unreachable"


@pytest.mark.asyncio
async def test_probe_cache_hit(monkeypatch):
    _route(monkeypatch, "searx1", FakeResponse(json_data={"results": []}))
    await probe_searxng("https://searx1.example")
    assert webfetch._probe_cache["https://searx1.example"]["result"]["status"] == "ok"


@pytest.mark.asyncio
async def test_search_web_returns_hits_and_unavailable(monkeypatch):
    data = {
        "results": [
            {"title": "A", "url": "https://a.example/x", "content": "a snippet"},
            {"title": "B", "url": "https://b.example/y", "content": "b snippet"},
        ]
    }

    _route(monkeypatch, "searx", FakeResponse(json_data=data))
    result = await search_web("https://searx.example", "q", 5)
    assert result["available"] is True
    assert len(result["results"]) == 2
    assert result["results"][0]["snippet"] == "a snippet"
    unavailable = await search_web(None, "q", 5)
    assert unavailable["available"] is False


@pytest.mark.asyncio
async def test_fetch_blocks_redirect_to_private(monkeypatch):
    hop = FakeResponse(status_code=302, headers={"location": "http://10.0.0.9/secret"})
    _route(monkeypatch, "placeholder.example", hop)
    with pytest.raises(WebFetchBlocked):
        await fetch_text("https://placeholder.example/go")


@pytest.mark.asyncio
async def test_fetch_too_many_redirects(monkeypatch):
    def hop(_url, _params, _headers):
        return FakeResponse(status_code=302, headers={"location": "/next"})

    _route(monkeypatch, "placeholder.example", hop)
    with pytest.raises(WebFetchBlocked, match="redirects"):
        await fetch_text("https://placeholder.example/go")
