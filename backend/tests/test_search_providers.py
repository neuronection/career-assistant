"""Web-search provider parity wall (plan 122 Phase 2): the guarded POST
transport, the per-provider adapters and the ordered-fallback behavior.

Provider response fixtures are the family contract's captured wire shapes
(``contracts/search-providers.json`` + the dev canonical fixture suite):
SearXNG ``results``, Tavily ``results``, Brave ``web.results``, Exa
``results``, Serper ``organic`` and Google PSE ``items``. No test opens a
socket — the guarded transport is driven over ``httpx.MockTransport`` with
an injected resolver, and the adapters take a recording fake.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.extensions.polite_http import PoliteHttpConfig, PoliteHttpError
from app.extensions.runtime.http import build_search_transport, reset_runtime
from app.extensions.search_adapters import (
    build_request,
    canonical_type,
    parse_hits,
    probe_provider,
    run_search,
)
from app.extensions.search_providers import (
    list_providers,
    provider_api_key,
    search_with_fallback,
    upsert_provider,
)
from app.models.settings_model import AppSetting

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "search_providers"
SHAPES = {
    "searxng": "searxng_results.json",
    "tavily": "tavily_results.json",
    "brave": "brave_results.json",
    "exa": "exa_results.json",
    "serper": "serper_organic.json",
    "google_pse": "google_pse_items.json",
}
EXPECTED_FIRST = {
    "searxng": (
        "Acid\u2013base reaction",
        "https://en.wikipedia.org/wiki/Acid%E2%80%93base_reaction",
    ),
    "tavily": ("Spaced repetition", "https://example.org/spaced"),
    "brave": ("Electron configuration", "https://example.org/ec"),
    "exa": ("MIT 18.06", "https://ocw.mit.edu/18-06"),
    "serper": ("Photosynthesis", "https://example.org/photo"),
    "google_pse": ("Chemical kinetics", "https://example.org/kinetics"),
}
RESOLVER_IP = "93.184.216.50"


def payload_for(provider_type: str) -> dict:
    return json.loads((FIXTURES / SHAPES[provider_type]).read_text(encoding="utf-8"))


def provider_row(provider_type: str, **extra) -> dict:
    row = {
        "id": "p1",
        "name": provider_type,
        "type": provider_type,
        "enabled": True,
        "base_url": "",
        "google_cx": None,
        "max_results": 5,
        "timeout_ms": 8000,
    }
    row.update(extra)
    return row


def fake_transport(payload=None, *, status: int = 200):
    calls: list[tuple[str, str, dict, dict | None]] = []

    async def transport(method: str, url: str, headers: dict, body: dict | None = None):
        calls.append((method, url, dict(headers), body))
        body_text = payload if isinstance(payload, str) else json.dumps(payload or {})
        content_type = (
            "application/json"
            if not isinstance(body_text, str) or body_text.lstrip().startswith(("{", "["))
            else "text/html"
        )
        return type(
            "Response",
            (),
            {
                "status": status,
                "body": body_text,
                "headers": {"content-type": content_type},
                "url": url,
                "truncated": False,
            },
        )()

    return transport, calls


@pytest.fixture(autouse=True)
def _fresh_runtime():
    reset_runtime()
    yield
    reset_runtime()


# ------------------------------------------------------------- wire shapes


def test_catalog_type_aliases():
    assert canonical_type("google-pse") == "google_pse"
    assert canonical_type("google_pse") == "google_pse"
    assert canonical_type("tavily") == "tavily"


@pytest.mark.parametrize(
    ("provider_type", "method", "url", "header_name", "body_key"),
    [
        ("searxng", "GET", "https://searx.example.org/search", None, None),
        ("tavily", "POST", "https://api.tavily.com/search", "Authorization", "query"),
        (
            "brave",
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            "X-Subscription-Token",
            None,
        ),
        ("exa", "POST", "https://api.exa.ai/search", "x-api-key", "query"),
        ("serper", "POST", "https://google.serper.dev/search", "X-API-KEY", "q"),
        (
            "google_pse",
            "GET",
            "https://www.googleapis.com/customsearch/v1",
            None,
            None,
        ),
    ],
)
def test_request_shapes(provider_type, method, url, header_name, body_key):
    row = provider_row(
        provider_type,
        base_url="https://searx.example.org" if provider_type == "searxng" else "",
        google_cx="a1b2c3d4e5f6g7h8j" if provider_type == "google_pse" else None,
    )
    request = build_request(row, "acid base", "secret-key", 5)
    assert request.method == method
    assert request.url == url
    if header_name:
        assert request.headers[header_name].endswith("secret-key")
    if body_key:
        assert request.body is not None and request.body[body_key] == "acid base"
    assert "q=acid+base" in request.full_url() or any(
        str(value) == "acid base" for value in (request.body or {}).values()
    )


@pytest.mark.parametrize("provider_type", list(SHAPES))
def test_parse_hits_shapes(provider_type):
    hits = parse_hits(provider_type, payload_for(provider_type), 5)
    assert hits
    assert (hits[0]["title"], hits[0]["url"]) == EXPECTED_FIRST[provider_type]
    assert hits[0]["snippet"]


# ----------------------------------------------------------- adapter walls


@pytest.mark.parametrize("provider_type", list(SHAPES))
async def test_run_search_success(provider_type):
    row = provider_row(
        provider_type,
        base_url="https://searx.example.org" if provider_type == "searxng" else "",
        google_cx="a1b2c3d4e5f6g7h8j" if provider_type == "google_pse" else None,
    )
    transport, calls = fake_transport(payload_for(provider_type))
    result = await run_search(row, "query", api_key="secret-key", transport=transport)
    assert result["available"] is True
    assert result["results"][0]["url"] == EXPECTED_FIRST[provider_type][1]
    assert len(calls) == 1


async def test_run_search_missing_key_never_calls_the_wire():
    transport, calls = fake_transport(payload_for("tavily"))
    result = await run_search(provider_row("tavily"), "query", transport=transport)
    assert result == {
        "available": False,
        "status": "missing_key",
        "detail": "tavily needs an API key",
    }
    assert calls == []


async def test_run_search_google_pse_needs_engine_id():
    transport, calls = fake_transport(payload_for("google_pse"))
    result = await run_search(
        provider_row("google_pse"), "query", api_key="AIza-secret", transport=transport
    )
    assert result["status"] == "missing_config"
    assert calls == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "auth"), (403, "auth"), (429, "rate_limit"), (400, "protocol"), (500, "protocol")],
)
async def test_run_search_status_mapping(status, expected):
    transport, _ = fake_transport({}, status=status)
    result = await run_search(
        provider_row("tavily"), "query", api_key="secret-key", transport=transport
    )
    assert result["available"] is False
    assert result["status"] == expected


async def test_run_search_non_json_is_typed():
    transport, _ = fake_transport("<html>nope</html>")
    result = await run_search(
        provider_row("serper"), "query", api_key="secret-key", transport=transport
    )
    assert result["status"] == "json_disabled"


async def test_probe_reports_the_ui_vocabulary():
    transport, _ = fake_transport(payload_for("brave"))
    probe = await probe_provider(provider_row("brave"), api_key="secret", transport=transport)
    assert probe["status"] == "ok"
    assert probe["result_count"] == 1
    failing, _ = fake_transport({}, status=401)
    probe = await probe_provider(provider_row("brave"), api_key="secret", transport=failing)
    assert probe["status"] == "auth"


# ------------------------------------------------------------- guarded POST


def _guarded(handler, domains=None, **config):
    return build_search_transport(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        resolver=lambda host: [RESOLVER_IP],
        domains=domains,
        config=PoliteHttpConfig(max_retries=1, **config),
    )


async def test_post_is_pinned_and_body_reaches_the_wire():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"results": []}, headers={"content-type": "application/json"}
        )

    response = await _guarded(handler)(
        "POST",
        "https://api.tavily.com/search",
        {"Authorization": "Bearer tvly-secret"},
        {"query": "study techniques"},
    )
    assert response.status == 200
    assert seen[0].method == "POST"
    assert seen[0].url.host == RESOLVER_IP
    assert seen[0].headers["host"] == "api.tavily.com"
    assert seen[0].headers["authorization"] == "Bearer tvly-secret"
    assert json.loads(seen[0].content) == {"query": "study techniques"}


async def test_redirect_is_refused_without_contacting_the_target():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://evil.example/steal"})

    with pytest.raises(PoliteHttpError) as exc:
        await _guarded(handler)(
            "POST",
            "https://api.tavily.com/search",
            {"Authorization": "Bearer tvly-secret"},
            {"query": "q"},
        )
    assert exc.value.code == "provider"
    assert "redirect" in exc.value.detail
    assert seen == [RESOLVER_IP], "the redirect target is never contacted"


async def test_private_target_is_denied_before_any_send():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the SSRF guard must block before the send")

    with pytest.raises(PoliteHttpError) as exc:
        await _guarded(handler)("POST", "http://169.254.169.254/latest/meta-data", {}, {"q": "x"})
    assert exc.value.code == "net-denied"


async def test_domain_scope_blocks_an_undeclared_host():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("outside the declared scope")

    with pytest.raises(PoliteHttpError) as exc:
        await _guarded(handler, domains=frozenset({"api.tavily.com"}))(
            "POST", "https://api.exa.ai/search", {}, {"query": "q"}
        )
    assert exc.value.code == "net-denied"


async def test_response_cap_truncates_the_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 4096)

    response = await _guarded(handler, max_response_bytes=1024)(
        "GET", "https://api.tavily.com/search", {}, None
    )
    assert response.truncated is True
    assert len(response.body) == 1024


# --------------------------------------------------------- settings + order


async def test_provider_key_is_sealed_and_never_returned(db):
    view = await upsert_provider(db, {"type": "brave", "api_key": "BSA-supersecret"})
    assert view["key_set"] is True
    assert "api_key_enc" not in view
    stored = (
        (await db.execute(select(AppSetting).where(AppSetting.key == "web.search_providers")))
        .scalars()
        .first()
    )
    assert stored is not None
    assert "BSA-supersecret" not in json.dumps(stored.value)
    assert stored.value["providers"][0]["api_key_enc"].startswith("enc::")
    assert await provider_api_key(db, view["id"]) == "BSA-supersecret"
    assert "BSA-supersecret" not in json.dumps(await list_providers(db))


async def test_ordered_fallback_uses_the_first_provider_that_answers(db):
    first = await upsert_provider(db, {"type": "tavily", "api_key": "tvly-bad"})
    second = await upsert_provider(db, {"type": "serper", "api_key": "serper-good"})
    assert first["id"] != second["id"]
    calls: list[str] = []

    async def transport(method: str, url: str, headers: dict, body: dict | None = None):
        calls.append(url)
        if "tavily" in url:
            return type(
                "Response",
                (),
                {
                    "status": 401,
                    "body": "{}",
                    "headers": {"content-type": "application/json"},
                    "url": url,
                    "truncated": False,
                },
            )()
        return type(
            "Response",
            (),
            {
                "status": 200,
                "body": json.dumps(payload_for("serper")),
                "headers": {"content-type": "application/json"},
                "url": url,
                "truncated": False,
            },
        )()

    result = await search_with_fallback(db, "photosynthesis", 5, transport=transport)
    assert result is not None
    assert result["available"] is True
    assert result["provider_name"] == "Serper (Google)"
    assert len(calls) == 2, "the failing provider is tried first, then the next one"


async def test_disabled_providers_are_skipped(db):
    await upsert_provider(db, {"type": "tavily", "api_key": "tvly-key", "enabled": False})
    assert await search_with_fallback(db, "query", 5) is None
