"""Web tool handlers — search/fetch/github through the registry (plan 80)."""

import pytest

from app.ai.tools import run_tool
from app.core.encryption import encrypt_secret
from app.services import webfetch


_PUBLIC = "93.184.216.34"


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """Hosts resolve to the public test IP; probe cache fresh per test."""
    from httpx import ConnectError

    async def resolver(host):
        if host in (_PUBLIC, "api.github.com"):
            return [_PUBLIC]
        raise ConnectError(f"no fake DNS for {host!r}")

    monkeypatch.setattr(webfetch, "_resolve_host", resolver)
    monkeypatch.setattr(webfetch, "_probe_cache", {})
    yield


@pytest.fixture(autouse=True)
def _clean_rate_hits():
    from app.ai.tools.web import _rate_hits

    _rate_hits.clear()
    yield
    _rate_hits.clear()


@pytest.fixture
def searx_url(db):
    from app.models.settings_model import AppSetting

    db.add(AppSetting(key="web.searxng_url", value={"url": "https://searx.example"}))
    return db.commit()


class FakeResponse:
    def __init__(
        self, status_code=200, content=b"", json_data=None, headers=None, encoding=None
    ):
        self.encoding = encoding
        self.status_code = status_code
        self._content = content
        self._json_data = json_data
        self.headers = headers or {}

    async def aiter_bytes(self):
        yield self._content

    @property
    def text(self):
        if self._json_data is None:
            return self._content.decode("utf-8", errors="replace")
        return __import__("json").dumps(self._json_data)

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


def _route(monkeypatch, routes: dict):
    from httpx import ConnectError

    async def get(url, params=None, headers=None):
        for key, resp in routes.items():
            if key in url:
                if callable(resp):
                    result = resp(url, params, headers)
                    if getattr(type(result), "__await__", None):
                        result = await result
                    return result
                return resp
        raise ConnectError(f"no route for {url!r}")

    client = type("FakeClient", (), {})()
    client.is_closed = False
    client.get = get
    monkeypatch.setattr(webfetch, "_client", lambda: client)


_PUBLIC = "93.184.216.34"


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """Hosts resolve to the public test IP; probe cache fresh per test."""
    from httpx import ConnectError

    async def resolver(host):
        if host in (_PUBLIC, "api.github.com"):
            return [_PUBLIC]
        raise ConnectError(f"no fake DNS for {host!r}")

    monkeypatch.setattr(webfetch, "_resolve_host", resolver)
    monkeypatch.setattr(webfetch, "_probe_cache", {})
    yield


@pytest.mark.asyncio
async def test_registry_declarations():
    from app.ai.tools import list_tools

    listed = {t["key"]: t for t in list_tools()}
    for key in ("web_search", "fetch_url", "github_repo"):
        entry = listed[key]
        assert entry["scope"] == "read"
        assert entry["input_schema"]["type"] == "object"
        assert entry["audiences"] == ["chat", "mcp"]


@pytest.mark.asyncio
async def test_web_search_unconfigured(db):
    result = await run_tool(db, "web_search", None, {"query": "jobs"})
    assert result["available"] is False
    assert "not configured" in result["reason"]


@pytest.mark.asyncio
async def test_web_search_unavailable_when_json_disabled(db, searx_url, monkeypatch):
    monkeypatch.setattr(webfetch, "_probe_cache", {})
    _route(
        monkeypatch,
        {"searx.example": FakeResponse(status_code=403, content=b"no json")},
    )
    result = await run_tool(db, "web_search", None, {"query": "jobs"})
    assert result["available"] is False
    assert result["status"] == "json_disabled"


@pytest.mark.asyncio
async def test_web_search_happy_path(db, searx_url, monkeypatch):
    blob = {
        "results": [
            {"title": t, "url": f"https://x.example/{t}", "content": f"{t} snippet"}
            for t in ("a", "b", "c")
        ]
    }

    def real_route(url, params, headers):
        if "format=json" and "/search" in url:
            if params is None:
                return FakeResponse(status_code=404)
            if "probe" in (params.get("q") or ""):
                return FakeResponse(json_data={"results": []})
            return FakeResponse(json_data=blob)
        return FakeResponse(status_code=404)

    _route(monkeypatch, {"searx.example": real_route})
    result = await run_tool(db, "web_search", None, {"query": "jobs", "n": 3})
    assert result["available"] is True
    results = result["results"]
    assert len(results) == 3
    assert set(results[0]) == {"title", "url", "snippet"}


@pytest.mark.asyncio
async def test_fetch_url_blocked_returns_unavailable(db):
    result = await run_tool(db, "fetch_url", None, {"url": "http://127.0.0.5/x"})
    assert result["available"] is False
    assert "blocked" in result["reason"]


@pytest.mark.asyncio
async def test_fetch_url_plain_interprets_html(db, monkeypatch):
    _route(
        monkeypatch,
        {
            "93.184.216.34": FakeResponse(
                status_code=200,
                content=b"<html><title>P</title><p>body text here</p></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "127.0.0.1": FakeResponse(),
        },
    )
    result = await run_tool(
        db, "fetch_url", None, {"url": "https://93.184.216.34/page"}
    )
    assert result["status"] == 200
    assert result["title"] == "P"
    assert "body text" in result["text"]
    assert result["rendered"] is False
    assert "reference data" in result["note"]


@pytest.mark.asyncio
async def test_fetch_url_escalates_on_sparse_html(db, monkeypatch):
    _route(
        monkeypatch,
        {
            "93.184.216.34": FakeResponse(
                status_code=200,
                content=b"<html><body><div id=app></div></body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        },
    )
    agent_calls = []

    async def fake_render(url, *, page_timeout=15.0):
        agent_calls.append(url)
        return webfetch.WebFetchResult(
            url=url, status=200, title="J", text="JS content", rendered=True
        )

    monkeypatch.setattr(webfetch, "render_text", fake_render)
    result = await run_tool(db, "fetch_url", None, {"url": "https://93.184.216.34/app"})
    assert result["rendered"] is True
    assert result["text"] == "JS content"
    assert agent_calls == ["https://93.184.216.34/app"]


@pytest.mark.asyncio
async def test_fetch_url_degrades_when_render_fails(db, monkeypatch):
    _route(
        monkeypatch,
        {
            "93.184.216.34": FakeResponse(
                status_code=200,
                content=b"<html><body></body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        },
    )

    async def dead_render(url, **_kw):
        raise RuntimeError("engine unfriendly")

    monkeypatch.setattr(webfetch, "render_text", dead_render)
    result = await run_tool(db, "fetch_url", None, {"url": "https://93.184.216.34/app"})
    assert result["rendered"] is False


def test_parse_github_repo_shapes():
    from app.ai.tools.web import parse_github_repo

    assert parse_github_repo("https://github.com/owner/repo") == ("owner", "repo")
    assert parse_github_repo("https://github.com/owner/repo.git") == ("owner", "repo")
    assert parse_github_repo("owner/repo") == ("owner", "repo")
    assert parse_github_repo("https://github.com/owner/repo/tree/main") == (
        "owner",
        "repo",
    )
    assert parse_github_repo("https://gitlab.com/owner/repo") is None
    assert parse_github_repo("") is None


@pytest.mark.asyncio
async def test_github_repo_metadata_and_readme(db, monkeypatch):
    def real_route(url, params, headers):
        if "/repos/owner/repo" in url and "readme" not in url:
            return FakeResponse(
                json_data={
                    "full_name": "owner/repo",
                    "description": "a demo",
                    "stargazers_count": 5,
                    "language": "Python",
                    "license": {"spdx_id": "MIT"},
                    "topics": ["t1"],
                    "pushed_at": "2026-01-01",
                }
            )
        if "readme" in url:
            assert headers.get("Accept") == "application/vnd.github.raw+blob", (
                "README needs raw accept header"
            )
            return FakeResponse(content=b"# Readme body", status_code=200)
        return FakeResponse(status_code=404)

    monkeypatch.setattr(webfetch, "_resolve_host", lambda host: _public(host))
    _route(monkeypatch, {"api.github.com": real_route})
    result = await run_tool(
        db, "github_repo", None, {"repo": "https://github.com/owner/repo"}
    )
    assert result["available"] is True
    assert result["stars"] == 5
    assert result["license"] == "MIT"
    assert result["readme_text"].startswith("# Readme")


@pytest.mark.asyncio
async def test_github_repo_uses_token_and_missing_repo(db, monkeypatch):
    from app.models.settings_model import AppSetting

    db.add(
        AppSetting(
            key="web.github_token",
            value={"token": encrypt_secret("tok") or ""},
        )
    )
    seen = {}

    def real_route(url, params, headers):
        seen["auth"] = headers.get("Authorization")
        if "/repos/missing" in url:
            return FakeResponse(status_code=404)
        return FakeResponse(status_code=404)

    monkeypatch.setattr(webfetch, "_resolve_host", lambda host: _public(host))
    _route(monkeypatch, {"api.github.com": real_route})
    result = await run_tool(db, "github_repo", None, {"repo": "owner/repo"})
    assert result["available"] is False
    assert "not found" in result["reason"]
    assert seen["auth"] == "Bearer tok"


@pytest.mark.asyncio
async def test_github_repo_rate_limit_payload(db, monkeypatch):
    from app.ai.tools.web import parse_github_repo  # noqa: F401

    monkeypatch.setattr(webfetch, "_resolve_host", lambda host: _public(host))
    _route(monkeypatch, {"api.github.com": FakeResponse(status_code=429)})
    result = await run_tool(db, "github_repo", None, {"repo": "owner/repo"})
    assert result["available"] is False
    assert "rate limited" in result["reason"]


async def _public(_host):
    return ["93.184.216.34"]


@pytest.mark.asyncio
async def test_rate_limits_flowthrough_registry(db, monkeypatch):
    """Exhaust the web_search window; the 6th call in a minute refuses."""
    from app.ai.tools.web import RATE_WINDOWS

    limit, _window = RATE_WINDOWS["web_search"]
    results = [
        await run_tool(db, "web_search", None, {"query": "q"}) for _ in range(limit + 1)
    ]
    assert results[-1]["reason"].startswith("rate limit")


# ------------------------------------------------- chatbot hooks (plan 80)


@pytest.mark.asyncio
async def test_pasted_github_link_runs_github_repo(db, monkeypatch):
    from app.ai.agents.chatbot import prepare_chat_prompt

    def route(url, params, headers):
        if "/repos/owner/proj" in url and "readme" not in url:
            return FakeResponse(
                json_data={
                    "full_name": "owner/proj",
                    "description": "a repo",
                    "stargazers_count": 1,
                    "language": "Python",
                    "license": {"spdx_id": "MIT"},
                    "topics": [],
                    "pushed_at": "2026-02-01",
                }
            )
        if "readme" in url:
            return FakeResponse(content=b"# Hi", status_code=200)
        raise AssertionError(url)

    _route(monkeypatch, {"api.github.com": route})
    prompt, metadata = await prepare_chat_prompt(
        db,
        profile_summary="",
        history=[],
        message="What is https://github.com/owner/proj about?",
    )
    names = [t["name"] for t in metadata["tools"]]
    assert "github_repo" in names
    assert "https://github.com/owner/proj" in prompt or metadata_tools_has(
        metadata, "github_repo"
    )


def metadata_tools_has(metadata, name):
    return any(t["name"] == name for t in metadata["tools"])


@pytest.mark.asyncio
async def test_pasted_generic_link_runs_fetch_url(db, monkeypatch):
    from app.ai.agents.chatbot import prepare_chat_prompt

    def route(url, params, headers):
        if "/repos" in url:
            return FakeResponse(status_code=404)
        return FakeResponse(
            content=b"<html><title>Doc</title><p>Hello page</p></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )

    _route(
        monkeypatch,
        {"93.184.216.34": route, "/repos": FakeResponse(status_code=404)},
    )
    _prompt, metadata = await prepare_chat_prompt(
        db,
        profile_summary="",
        history=[],
        message="Summarize https://93.184.216.34/guide",
    )
    assert metadata_tools_has(metadata, "fetch_url")


@pytest.mark.asyncio
async def test_search_keyword_runs_web_search(db, searx_url, monkeypatch):
    from app.ai.agents.chatbot import prepare_chat_prompt

    def route(url, params, headers):
        probe = "probe" in (params or {}).get("q", "")
        return FakeResponse(
            json_data={
                "results": []
                if probe
                else [{"title": "T", "url": "https://r.example", "content": "s"}]
            }
        )

    _route(monkeypatch, {"searx.example": route})
    _prompt, metadata = await prepare_chat_prompt(
        db,
        profile_summary="",
        history=[],
        message="Search the web for latest news about job platforms",
    )
    assert metadata_tools_has(metadata, "web_search")
