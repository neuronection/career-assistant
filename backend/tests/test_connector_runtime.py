"""Connector runtime e2e (plan 32 Phase 1 wall): fixture/mock-driven syncs
of ats_api (Greenhouse wire), rss and csv through the REAL sync_source →
upsert → dedup path, riding the polite runtime over an httpx.MockTransport
(injected fake resolver — no network in unit tests). Pins the politeness
behaviors end to end: conditional GET on the second sync, robots preflight
cached per host, DNS pinning on the wire, and the SSRF guard closing the
2026-09-11 audit finding at the sync boundary.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.extensions.registry import reset_registry
from app.extensions.runtime.http import build_transport
from app.models.posting_model import JobSource
from app.services.postings_service import sync_source

RESOLVER_MAP = {
    "boards-api.greenhouse.io": ["93.184.216.34"],
    "jobs.example": ["93.184.216.35"],
}

GREENHOUSE_BODY = json.dumps(
    {
        "jobs": [
            {
                "id": 4242,
                "title": "Frontend Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/4242",
                "content": "<p>Build UIs</p>",
                "updated_at": "2026-08-12T10:00:00+00:00",
                "location": {"name": "Remote, EU"},
            }
        ]
    }
)

RSS_BODY = (
    "<rss><channel><item><title>Platform Engineer</title>"
    "<guid>rss-3</guid><link>https://jobs.example/3</link>"
    "<pubDate>Mon, 10 Aug 2026 08:00:00 GMT</pubDate></item></channel></rss>"
)

CSV_BODY = (
    "external_id,title,org,city,country,remote,url,skills\n"
    "csv-1,Data Engineer,FeedCo,Berlin,DE,false,https://jobs.example/1,python|sql"
)


def fake_resolver(host: str) -> list[str]:
    return RESOLVER_MAP[host]


@pytest.fixture
async def runtime_factory():
    """build_transport over a MockTransport recording every request."""
    seen: list[httpx.Request] = []

    def make_transport(handler) -> object:
        def wrapped(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        return build_transport(
            client=httpx.AsyncClient(transport=httpx.MockTransport(wrapped)),
            resolver=fake_resolver,
        )

    yield make_transport, seen


async def _make_source(db, *, key: str, connector_key: str, config: dict) -> JobSource:
    source = JobSource(key=key, connector_key=connector_key, config=config, enabled=True)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def test_greenhouse_sync_upserts_and_dedups(
    db, seeded_catalog, synthetic_connector, runtime_factory
):
    make_transport, seen = runtime_factory
    calls = {"feed": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/v1/boards/acme/jobs":
            calls["feed"] += 1
            if calls["feed"] == 2:
                return httpx.Response(304, headers={"ETag": '"gh-v1"'})
            return httpx.Response(200, text=GREENHOUSE_BODY, headers={"ETag": '"gh-v1"'})
        return httpx.Response(500, text=f"no route {path}")

    transport = make_transport(handler)
    source = await _make_source(
        db, key="gh", connector_key="ats_api", config={"provider": "greenhouse", "org": "acme"}
    )
    first = await sync_source(db, source, transport=transport)
    assert first["synced"] == 1
    assert first["errors"] == []
    assert source.error == ""

    second = await sync_source(db, source, transport=transport)
    assert second["synced"] == 0

    conditional = [r for r in seen if r.url.path == "/v1/boards/acme/jobs"]
    assert len(conditional) == 2
    assert conditional[1].headers.get("If-None-Match") == '"gh-v1"'
    assert sum(1 for r in seen if r.url.path == "/robots.txt") == 1
    assert conditional[0].url.host == "93.184.216.34"
    assert conditional[0].headers.get("host") == "boards-api.greenhouse.io"


async def test_rss_sync_through_runtime(db, seeded_catalog, synthetic_connector, runtime_factory):
    make_transport, _seen = runtime_factory

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /nothing")
        return httpx.Response(200, text=RSS_BODY, headers={"ETag": '"rss-v1"'})

    source = await _make_source(
        db, key="feed", connector_key="rss", config={"url": "https://jobs.example/feed.xml"}
    )
    result = await sync_source(db, source, transport=make_transport(handler))
    assert result["synced"] == 1
    assert source.sync_state.get("etag") == '"rss-v1"'


async def test_csv_sync_through_runtime(db, seeded_catalog, synthetic_connector, runtime_factory):
    make_transport, _seen = runtime_factory

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=CSV_BODY, headers={"ETag": '"csv-v1"'})

    source = await _make_source(
        db, key="sheet", connector_key="csv", config={"url": "https://jobs.example/feed.csv"}
    )
    result = await sync_source(db, source, transport=make_transport(handler))
    assert result["synced"] == 1


async def test_metadata_endpoint_blocked_at_sync_boundary(
    db, seeded_catalog, synthetic_connector, runtime_factory
):
    """The audit finding closed: a connector URL pointing at cloud metadata
    never leaves the process; the source row records the typed net-denied."""
    make_transport, seen = runtime_factory

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the guard must block before any transport call")

    source = await _make_source(
        db, key="evil", connector_key="csv", config={"url": "http://169.254.169.254/latest"}
    )
    result = await sync_source(db, source, transport=make_transport(handler))
    assert result["synced"] == 0
    assert result["errors"][0]["code"] == "net-denied"
    assert source.error.startswith("net-denied:")
    assert seen == []


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    reset_registry()
