"""The real-content job-board connector wall (Arbeitnow, Remotive,
Jobicy — bundled T1, live public JSON APIs).

Fixtures are CAPTURED REAL payloads (2026-10-17 probes, no invention):
``fixtures/connectors/{arbeitnow_job_board,remotive_remote_jobs,
jobicy_remote_jobs}.json`` carry verbatim rows + meta from the live
endpoints (Arbeitnow's is ``/api/job-board-api`` — the documented
``/api/job-board`` now 302s home, the captured drift), plus the REAL
``robots_remotive_com.txt`` whose ``Disallow: /api/*`` pins the
fail-closed robots law against reality.

Every wall rides the REAL runtime stack (``sync_source`` → polite
transport over ``httpx.MockTransport`` + an injected fake resolver — no
network in unit tests): happy path with dedup + watermark second sync,
newer-item incremental, malformed rows → typed ``invalid`` (never
persisted), 429 → typed ``rate-limited``, robots denial → typed
``net-denied`` (the captured remotive robots body), domain-drift
redirect → typed ``net-denied``, and the offline family conformance
kit per connector.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.extensions.builtin.job_boards import (
    ARBEITNOW_URL,
    JOBICY_URL,
    REMOTIVE_URL,
)
from app.extensions.conformance import ConnectorConformanceTests
from app.extensions.polite_http import NetGuardConfig, PoliteHttpConfig
from app.extensions.registry import get_connector, list_connectors, reset_registry
from app.extensions.runtime.http import build_transport, reset_runtime
from app.models.posting_model import JobPosting, JobSource
from app.services.postings_service import sync_source

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "connectors"
ARBEITNOW_BODY = (FIXTURES / "arbeitnow_job_board.json").read_text(encoding="utf-8")
REMOTIVE_BODY = (FIXTURES / "remotive_remote_jobs.json").read_text(encoding="utf-8")
JOBICY_BODY = (FIXTURES / "jobicy_remote_jobs.json").read_text(encoding="utf-8")
REMOTIVE_ROBOTS = (FIXTURES / "robots_remotive_com.txt").read_text(encoding="utf-8")

ARBEITNOW_PATH = ARBEITNOW_URL.removeprefix("https://www.arbeitnow.com")
REMOTIVE_PATH = REMOTIVE_URL.removeprefix("https://remotive.com")
JOBICY_PATH = JOBICY_URL.removeprefix("https://jobicy.com")

RESOLVER_MAP = {
    "www.arbeitnow.com": ["93.184.216.34"],
    "remotive.com": ["93.184.216.35"],
    "jobicy.com": ["93.184.216.36"],
    "drift.example": ["93.184.216.37"],
}


def fake_resolver(host: str) -> list[str]:
    return RESOLVER_MAP[host]


@pytest.fixture(autouse=True)
def _fresh_runtime():
    """Drop the shared robots cache + per-rpm limiters between tests so
    token buckets never bleed across walls (each wall is self-contained)."""
    reset_runtime()
    yield
    reset_runtime()


@pytest.fixture
def runtime_factory():
    """build_transport over a MockTransport recording every request."""
    seen: list[httpx.Request] = []

    def make_transport(handler, *, domains: frozenset[str] | None = None, config=None):
        def wrapped(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        return build_transport(
            client=httpx.AsyncClient(transport=httpx.MockTransport(wrapped)),
            resolver=fake_resolver,
            domains=domains,
            config=config,
        )

    yield make_transport, seen


async def _make_source(
    db, *, key: str, config: dict, connector_key: str | None = None
) -> JobSource:
    source = JobSource(key=key, connector_key=connector_key or key, config=config, enabled=True)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


def _scoped_transport(runtime_factory, connector_key: str, handler):
    """The transport exactly as sync_source would build it: domains from
    the connector's own declared network scopes."""
    make_transport, _ = runtime_factory
    connector = get_connector(connector_key)
    return make_transport(handler, domains=frozenset(connector.capabilities.network_scopes or []))


def _json_response(body: str, etag: str | None = None) -> httpx.Response:
    headers = {"Content-Type": "application/json"}
    if etag:
        headers["ETag"] = etag
    return httpx.Response(200, text=body, headers=headers)


def _allow_all_robots(_: httpx.Request) -> httpx.Response:
    return httpx.Response(404)


# ------------------------------------------------- offline conformance kit


class TestArbeitnowConformance(ConnectorConformanceTests):
    connector = get_connector("arbeitnow")
    config = {}  # noqa: RUF012 -- zero-config by design
    body = ARBEITNOW_BODY


class TestRemotiveConformance(ConnectorConformanceTests):
    connector = get_connector("remotive")
    config = {}  # noqa: RUF012 -- zero-config by design
    body = REMOTIVE_BODY


class TestJobicyConformance(ConnectorConformanceTests):
    connector = get_connector("jobicy")
    config = {}  # noqa: RUF012 -- zero-config by design
    body = JOBICY_BODY


# ------------------------------------------------------- registration law


def test_registered_with_net_sync_and_no_secret_slots():
    catalog = {entry["key"]: entry for entry in list_connectors()}
    for key, domain in (
        ("arbeitnow", "www.arbeitnow.com"),
        ("remotive", "remotive.com"),
        ("jobicy", "jobicy.com"),
    ):
        assert key in catalog, f"{key} missing from the registry"
        manifest = catalog[key]["manifest"]
        assert manifest["capabilities"] == ["net", "sync"]
        assert domain in manifest["domains"], "net requires the REAL api host declared"
        assert catalog[key]["secret_fields"] == [], "no credentials — no secret slots"
        assert manifest["supportsIncremental"] is True
        connector = get_connector(key)
        assert connector.secret_slots() == {}
        assert connector.validate_config({}) == connector.validate_config(
            connector.validate_config({})
        ), "zero-config round-trips"


async def test_catalog_feeds_the_admin_surface(client, auth_headers):
    """The settings UI is generic over the registry — the three boards
    appear through the same listing endpoint with zero UI changes."""
    response = await client.get("/api/v1/admin/postings/connectors", headers=auth_headers)
    assert response.status_code == 200
    keys = {entry["key"] for entry in response.json()}
    assert {"arbeitnow", "remotive", "jobicy"} <= keys


# ------------------------------------------------------------- happy paths


async def test_arbeitnow_sync_dedup_and_watermark(db, seeded_catalog, runtime_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return _json_response(ARBEITNOW_BODY, etag='"an-v1"')

    transport = _scoped_transport(runtime_factory, "arbeitnow", handler)
    source = await _make_source(db, key="arbeitnow", config={})
    first = await sync_source(db, source, transport=transport)
    assert first["errors"] == [], first
    assert first["synced"] == 6
    assert source.sync_state.get("watermark")
    rows = (await db.execute(select(JobPosting))).scalars().all()
    assert len(rows) == 6
    by_ext = {row.external_id: row for row in rows}
    analyst = by_ext["remote-technical-analystin-homeoffice-364462"]
    assert analyst.location["remote"] is True
    assert analyst.employment_type == "full_time"
    assert analyst.raw["description"]

    second = await sync_source(db, source, transport=transport)
    assert second["synced"] == 0, "same body + watermark → nothing new (content-hash dedup too)"

    _, seen = runtime_factory
    conditional = [r for r in seen if r.url.path == ARBEITNOW_PATH]
    assert len(conditional) == 2
    assert conditional[1].headers.get("If-None-Match") == '"an-v1"'
    assert sum(1 for r in seen if r.url.path == "/robots.txt") == 1, "robots cached per host"


async def test_arbeitnow_watermark_returns_only_newer_items(db, seeded_catalog, runtime_factory):
    payload = json.loads(ARBEITNOW_BODY)
    newest = max(int(row["created_at"]) for row in payload["data"])
    fresh = dict(payload["data"][0])
    fresh["slug"] = f"{fresh['slug']}-reposted"
    fresh["created_at"] = newest + 3600
    grown = {**payload, "data": [fresh, *payload["data"]]}

    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls["count"] += 1
        body = payload if calls["count"] == 1 else grown
        etag = '"an-v1"' if calls["count"] == 1 else '"an-v2"'
        return _json_response(json.dumps(body), etag=etag)

    transport = _scoped_transport(runtime_factory, "arbeitnow", handler)
    source = await _make_source(db, key="arbeitnow", config={})
    first = await sync_source(db, source, transport=transport)
    assert first["synced"] == 6
    second = await sync_source(db, source, transport=transport)
    assert second["synced"] == 1
    assert second["errors"] == []
    rows = (await db.execute(select(JobPosting))).scalars().all()
    assert len(rows) == 7


async def test_arbeitnow_tag_filter_and_cap(db, seeded_catalog, runtime_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return _json_response(ARBEITNOW_BODY)

    source = await _make_source(db, key="arbeitnow", config={"tags": ["quality assurance"]})
    result = await sync_source(
        db, source, transport=_scoped_transport(runtime_factory, "arbeitnow", handler)
    )
    assert result["errors"] == []
    rows = (await db.execute(select(JobPosting))).scalars().all()
    assert [row.external_id for row in rows] == [
        "software-testautomatisierer-mit-karriereambitionen-markt-indersdorf-86749"
    ], "client-side tag filter keeps only matching real rows"

    capped = await _make_source(
        db, key="arbeitnow-capped", config={"max_items": 2}, connector_key="arbeitnow"
    )
    result = await sync_source(
        db, capped, transport=_scoped_transport(runtime_factory, "arbeitnow", handler)
    )
    assert result["synced"] == 2, "newest-first cap honored"


async def test_remotive_sync_maps_salary_and_remote(db, seeded_catalog, runtime_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:")
        return _json_response(REMOTIVE_BODY, etag='"rm-v1"')

    transport = _scoped_transport(runtime_factory, "remotive", handler)
    source = await _make_source(db, key="remotive", config={})
    first = await sync_source(db, source, transport=transport)
    assert first["errors"] == [], first
    assert first["synced"] == 6
    rows = {row.external_id: row for row in (await db.execute(select(JobPosting))).scalars().all()}
    lead = rows["2069746"]
    assert lead.salary_currency == "USD"
    assert float(lead.salary_min) == 170000.0
    assert float(lead.salary_max) == 200000.0
    assert lead.salary_period == "year"
    writer = rows["1185979"]
    assert writer.salary_period == "hour" and float(writer.salary_min) == 50.0
    assert writer.employment_type == "contract", "freelance maps onto the contract class"
    assert all(row.location["remote"] for row in rows.values()), "remote-jobs board"
    assert all(row.raw["location_note"] for row in rows.values()), "geo restriction preserved"

    second = await sync_source(db, source, transport=transport)
    assert second["synced"] == 0


async def test_remotive_category_param_reaches_the_wire(db, seeded_catalog, runtime_factory):
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:")
        asked.append(str(request.url.params.get("category")))
        return _json_response(REMOTIVE_BODY)

    source = await _make_source(
        db, key="remotive-cat", config={"category": "software-dev"}, connector_key="remotive"
    )
    result = await sync_source(
        db, source, transport=_scoped_transport(runtime_factory, "remotive", handler)
    )
    assert result["errors"] == []
    assert asked == ["software-dev"]


async def test_jobicy_sync_maps_level_salary_and_cursor_pages(db, seeded_catalog, runtime_factory):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:")
        calls.append(request)
        if request.url.params.get("cursor"):
            return _json_response(json.dumps({"jobs": [], "hasMore": False, "nextCursor": None}))
        return _json_response(JOBICY_BODY, etag='"jb-v1"')

    transport = _scoped_transport(runtime_factory, "jobicy", handler)
    source = await _make_source(db, key="jobicy", config={})
    first = await sync_source(db, source, transport=transport)
    assert first["errors"] == [], first
    assert first["synced"] == 6
    assert [r.url.path for r in calls] == [JOBICY_PATH, JOBICY_PATH], "cursor walked page two"
    assert calls[1].url.params.get("cursor")
    rows = {row.external_id: row for row in (await db.execute(select(JobPosting))).scalars().all()}
    consultant = rows["155615"]
    assert consultant.salary_currency == "GBP"
    assert float(consultant.salary_min) == 190000.0
    assert consultant.salary_period == "year"
    senior = rows["155609"]
    assert senior.seniority == "senior"
    assert senior.salary_period == "hour" and float(senior.salary_min) == 110.0
    coordinator = rows["155562"]
    assert coordinator.seniority == "mid"
    assert coordinator.employment_type == "contract"
    assert coordinator.salary_period == "month"
    assert all(row.location["remote"] for row in rows.values()), "remote-jobs feed"

    second = await sync_source(db, source, transport=transport)
    assert second["synced"] == 0


async def test_jobicy_tag_param_reaches_the_wire(db, seeded_catalog, runtime_factory):
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:")
        asked.append(f"tag={request.url.params.get('tag')} count={request.url.params.get('count')}")
        return _json_response(json.dumps({"jobs": [], "hasMore": False, "nextCursor": None}))

    source = await _make_source(
        db, key="jobicy-tag", config={"tag": "developer"}, connector_key="jobicy"
    )
    result = await sync_source(
        db, source, transport=_scoped_transport(runtime_factory, "jobicy", handler)
    )
    assert result["errors"] == []
    assert asked == ["tag=developer count=50"]


# --------------------------------------------------------- malformed rows


@pytest.mark.parametrize(
    "key,rows_key,mutate",
    [
        ("arbeitnow", "data", lambda row: row.update({"slug": "", "title": ""})),
        ("remotive", "jobs", lambda row: row.update({"id": None})),
        ("jobicy", "jobs", lambda row: row.update({"jobTitle": ""})),
    ],
)
async def test_malformed_row_is_typed_invalid_and_never_persisted(
    db, seeded_catalog, runtime_factory, key, rows_key, mutate
):
    bodies = {
        "arbeitnow": ARBEITNOW_BODY,
        "remotive": REMOTIVE_BODY,
        "jobicy": JOBICY_BODY,
    }
    payload = json.loads(bodies[key])
    mutate(payload[rows_key][0])
    payload["hasMore"] = False
    payload.pop("nextCursor", None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return _json_response(json.dumps(payload))

    source = await _make_source(db, key=key, config={})
    result = await sync_source(
        db, source, transport=_scoped_transport(runtime_factory, key, handler)
    )
    assert result["synced"] == 5, "healthy rows still land"
    assert [error["code"] for error in result["errors"]] == ["invalid"]
    assert result["errors"][0]["retryable"] == "no"
    rows = (await db.execute(select(JobPosting))).scalars().all()
    assert len(rows) == 5


# ----------------------------------------------------- politeness failures


@pytest.mark.parametrize("key", ["arbeitnow", "remotive", "jobicy"])
async def test_429_surfaces_typed_rate_limited(db, seeded_catalog, runtime_factory, key):
    config = PoliteHttpConfig(
        guard=NetGuardConfig(),
        requests_per_minute=30,
        max_retries=1,
        respect_robots=False,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"})

    make_transport, _ = runtime_factory
    source = await _make_source(db, key=key, config={})
    result = await sync_source(db, source, transport=make_transport(handler, config=config))
    assert result["synced"] == 0
    assert result["errors"][0]["code"] == "rate-limited"
    assert result["errors"][0]["retry_after_ms"] == 1000
    assert source.error.startswith("rate-limited:")


async def test_remotive_robots_disallow_is_net_denied_for_real(db, seeded_catalog, runtime_factory):
    """The CAPTURED remotive robots.txt disallows /api/* — the runtime's
    fail-closed robots law denies the fetch (typed net-denied, source
    errors, nothing persisted). Reality pins the law."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=REMOTIVE_ROBOTS)
        raise AssertionError("the robots verdict must block before the API call")

    source = await _make_source(db, key="remotive", config={})
    result = await sync_source(
        db, source, transport=_scoped_transport(runtime_factory, "remotive", handler)
    )
    assert result["synced"] == 0
    assert result["errors"][0]["code"] == "net-denied"
    assert "robots.txt disallows" in result["errors"][0]["detail"]
    rows = (await db.execute(select(JobPosting))).scalars().all()
    assert rows == []


async def test_domain_drift_redirect_is_net_denied(db, seeded_catalog, runtime_factory):
    """A redirect hop off the declared domains dies at the seam — the
    polite runtime re-validates EVERY hop against the manifest scope."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"Location": "https://drift.example/jobs?leak=1"})

    source = await _make_source(db, key="arbeitnow", config={})
    result = await sync_source(
        db, source, transport=_scoped_transport(runtime_factory, "arbeitnow", handler)
    )
    assert result["synced"] == 0
    assert result["errors"][0]["code"] == "net-denied"
    assert "outside the declared domain scope" in result["errors"][0]["detail"]


@pytest.mark.parametrize("key", ["arbeitnow", "remotive", "jobicy"])
async def test_no_transport_fails_closed_not_empty(key):
    connector = get_connector(key)
    result = await connector.fetch({}, {}, transport=None)
    assert result.items == []
    assert result.partial_errors[0].code == "not-ready"


def test_time_bomb_free_fixtures():
    """Fixture rows carry REAL recent timestamps; the 45-day expiry
    window must never detonate on a boundary — assert the newest fixture
    row is inside the window relative to *now*, so a stale capture is
    caught at capture time, not mid-suite years later."""
    for body, rows_key, date_get in (
        (ARBEITNOW_BODY, "data", lambda row: datetime.fromtimestamp(row["created_at"], tz=UTC)),
        (
            REMOTIVE_BODY,
            "jobs",
            lambda row: datetime.fromisoformat(row["publication_date"]).replace(tzinfo=UTC),
        ),
        (JOBICY_BODY, "jobs", lambda row: datetime.fromisoformat(row["pubDate"])),
    ):
        newest = max(date_get(row) for row in json.loads(body)[rows_key])
        assert datetime.now(UTC) - newest < timedelta(days=45), (
            "fixture capture is older than the posting expiry window — re-capture"
        )


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    reset_registry()
