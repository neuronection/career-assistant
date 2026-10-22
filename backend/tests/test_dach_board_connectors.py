"""The DACH board pack wall (plan 122 Phase 1): Personio, JOIN.com,
StepStone/Xing RSS, Recruitee and Teamtailor as bundled T1 connectors.

Fixtures are CAPTURED REAL payloads (2026-10-22 probes; sources recorded in
``fixtures/connectors/CAPTURES.md``): Personio's per-tenant XML feed, JOIN's
public company API, Recruitee's ``offers[]`` feed, Teamtailor's JSON Feed
1.1 and a real RSS 2.0 job-alert feed. Every wall rides the REAL runtime
stack (``sync_source`` → polite transport over ``httpx.MockTransport`` + an
injected fake resolver — no network in unit tests).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.core.encryption import decrypt_secret, encrypt_secret
from app.extensions.builtin.dach_boards import (
    PersonioConnector,
    StepstoneXingConnector,
    parse_join_payload,
    parse_personio_payload,
    parse_recruitee_payload,
    parse_rss_jobs_payload,
    parse_teamtailor_payload,
)
from app.extensions.builtin.job_boards import parse_salary_text
from app.extensions.conformance import ConnectorConformanceTests
from app.extensions.registry import get_connector, list_connectors, reset_registry
from app.extensions.runtime.http import build_transport, reset_runtime
from app.models.posting_model import JobSource
from app.services.postings_service import sync_source

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "connectors"
PERSONIO_BODY = (FIXTURES / "personio_jobs.xml").read_text(encoding="utf-8")
JOIN_BODY = (FIXTURES / "join_com_jobs.json").read_text(encoding="utf-8")
RECRUITEE_BODY = (FIXTURES / "recruitee_offers.json").read_text(encoding="utf-8")
TEAMTAILOR_BODY = (FIXTURES / "teamtailor_jobs.json").read_text(encoding="utf-8")
RSS_BODY = (FIXTURES / "stepstone_xing_jobs.xml").read_text(encoding="utf-8")
SALARY_CASES = json.loads((FIXTURES / "salary_samples.json").read_text(encoding="utf-8"))

RESOLVER_MAP = {
    "personio-gmbh.jobs.personio.de": ["93.184.216.40"],
    "join.com": ["93.184.216.41"],
    "bunq.recruitee.com": ["93.184.216.42"],
    "career.teamtailor.com": ["93.184.216.43"],
    "jobs.example.org": ["93.184.216.44"],
}


def fake_resolver(host: str) -> list[str]:
    return RESOLVER_MAP[host]


@pytest.fixture(autouse=True)
def _fresh_runtime():
    reset_runtime()
    yield
    reset_runtime()


@pytest.fixture
def runtime_factory():
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
    db, *, key: str, config: dict, connector_key: str | None = None, secrets: dict | None = None
) -> JobSource:
    source = JobSource(
        key=key,
        connector_key=connector_key or key,
        config=config,
        secrets=secrets or {},
        enabled=True,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


def _scoped_transport(runtime_factory, connector_key: str, handler):
    make_transport, _ = runtime_factory
    connector = get_connector(connector_key)
    return make_transport(handler, domains=frozenset(connector.capabilities.network_scopes or []))


def _feed_response(body: str, content_type: str, etag: str | None = None) -> httpx.Response:
    headers = {"Content-Type": content_type}
    if etag:
        headers["ETag"] = etag
    return httpx.Response(200, text=body, headers=headers)


def _robots_or_feed(feed_path: str, body: str, content_type: str, etag: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path != feed_path:
            raise AssertionError(f"unexpected path {request.url.path}")
        return _feed_response(body, content_type, etag)

    return handler


# ---------------------------------------------------------------- fixtures


def test_personio_captured_shape():
    items, errors = parse_personio_payload(PERSONIO_BODY, tenant="personio-gmbh")
    assert errors == []
    assert [item.external_id for item in items] == ["1676226", "1676223", "1676224"]
    first = items[0]
    assert first.title == "Initiativbewerbung (Festanstellung)"
    assert first.location.remote is True
    assert first.employment_type == "full_time"
    assert first.seniority == "junior"
    assert first.url == "https://personio-gmbh.jobs.personio.de/job/1676226"
    assert first.posted_at == datetime(2018, 7, 31, 9, 25, 4, tzinfo=UTC)
    assert "jobDescription" not in first.raw["description"]
    assert items[2].employment_type == "internship"


def test_join_captured_shape_and_minor_unit_salary():
    items, errors, pagination = parse_join_payload(JOIN_BODY, company_slug="join")
    assert errors == []
    assert pagination["pageCount"] == 1
    assert len(items) == 3
    first = items[0]
    assert first.salary is not None
    assert first.salary.currency == "EUR"
    assert (first.salary.min, first.salary.max) == (90000.0, 105000.0)
    assert first.salary.period == "year"
    assert first.onsite_policy == "hybrid"
    assert first.location.city == "Barcelona"
    assert first.location.country == "ES"
    assert first.url == "https://join.com/companies/join/16833245-engineering-manager"
    assert first.posted_at == datetime(2025, 8, 29, 16, 34, 57, 775000, tzinfo=UTC)


def test_recruitee_captured_shape():
    items, errors = parse_recruitee_payload(RECRUITEE_BODY)
    assert errors == []
    assert len(items) == 3
    first = items[0]
    assert first.external_id == "2783543"
    assert first.title == "Head of Product"
    assert first.location.city == "Amsterdam"
    assert first.location.country == "NL"
    assert first.onsite_policy == "hybrid"
    assert first.posted_at == datetime(2026, 10, 15, 9, 31, 36, tzinfo=UTC)
    assert first.url == "https://careers.bunq.com/o/head-of-product-6"
    assert first.raw["department"] == "Product"
    assert len(first.raw["description"]) <= 8000


def test_teamtailor_captured_json_feed_shape():
    items, errors = parse_teamtailor_payload(TEAMTAILOR_BODY)
    assert errors == []
    assert len(items) == 2
    first = items[0]
    assert first.title == "UK Account Executive - SMB"
    assert first.org == "Teamtailor"
    assert first.location.city == "London"
    assert first.location.country == "GB"
    assert first.posted_at == datetime(2026, 7, 24, 7, 5, 16, tzinfo=UTC)
    assert first.url == "https://career.teamtailor.com/jobs/8118064-uk-account-executive-smb"


def test_stepstone_xing_rfc822_dates_and_free_text_salary():
    items, errors = parse_rss_jobs_payload(RSS_BODY)
    assert errors == []
    assert len(items) == 2
    first = items[0]
    assert first.posted_at == datetime(2024, 6, 16, 17, 30, 51, tzinfo=UTC)
    assert first.salary is not None
    assert (first.salary.currency, first.salary.min, first.salary.max) == ("USD", 90.0, 170.0)
    assert first.salary.period == "hour"
    assert first.raw["region"] == "Anywhere in the World"


@pytest.mark.parametrize("case", SALARY_CASES["cases"], ids=lambda case: case["text"])
def test_salary_fixtures(case):
    parsed = parse_salary_text(case["text"])
    assert parsed is not None, case["text"]
    assert parsed.currency == case["currency"]
    assert parsed.min == case["min"]
    assert parsed.max == case["max"]
    assert parsed.period == case["period"]


@pytest.mark.parametrize("text", SALARY_CASES["unparseable"])
def test_salary_unparseable(text):
    assert parse_salary_text(text) is None


# ----------------------------------------------------------- registration


def test_new_connectors_register_with_manifests_and_secret_slots():
    catalog = {entry["key"]: entry for entry in list_connectors()}
    expected = {
        "personio": ("*.jobs.personio.de", ["net", "sync"]),
        "join_com": ("join.com", ["net", "sync"]),
        "recruitee": ("*.recruitee.com", ["net", "sync"]),
        "teamtailor": ("*.teamtailor.com", ["net", "sync"]),
    }
    for key, (domain, capabilities) in expected.items():
        entry = catalog[key]
        manifest = entry["manifest"]
        assert manifest["capabilities"] == capabilities
        assert manifest["domains"] == [domain]
        assert entry["secret_fields"] == []
        assert manifest["supportsIncremental"] is True
        assert manifest["docs"] == "docs/docs-tree.json"
    stepstone = catalog["stepstone_xing"]
    assert stepstone["manifest"]["capabilities"] == ["sync", "secrets"]
    assert stepstone["secret_fields"] == ["feed_url"]


def test_stepstone_xing_never_accepts_the_feed_url_in_config():
    connector = StepstoneXingConnector()
    with pytest.raises(Exception, match="never lives in config"):
        connector.validate_config(
            {"provider": "stepstone", "feed_url": "https://jobs.example.org/feed.xml"}
        )
    assert connector.validate_config({"provider": "xing"})["provider"] == "xing"


def test_new_bundle_corrupt_manifest_self_disables(tmp_path):
    from app.core.errors import ValidationError
    from app.extensions.registry import validate_manifest

    bad = tmp_path / "manifest.json"
    bad.write_text("{ not json", encoding="utf-8")

    class Stub(PersonioConnector):
        manifest_file = bad

    with pytest.raises(ValidationError, match="manifest file unavailable"):
        validate_manifest(Stub())


# ------------------------------------------------------- offline conformance


class TestPersonioConformance(ConnectorConformanceTests):
    connector = get_connector("personio")
    config = {"tenant": "personio-gmbh"}  # noqa: RUF012
    body = PERSONIO_BODY


class TestJoinConformance(ConnectorConformanceTests):
    connector = get_connector("join_com")
    config = {"company_id": 54, "company_slug": "join"}  # noqa: RUF012
    body = JOIN_BODY


class TestRecruiteeConformance(ConnectorConformanceTests):
    connector = get_connector("recruitee")
    config = {"company": "bunq"}  # noqa: RUF012
    body = RECRUITEE_BODY


class TestTeamtailorConformance(ConnectorConformanceTests):
    connector = get_connector("teamtailor")
    config = {"company": "career"}  # noqa: RUF012
    body = TEAMTAILOR_BODY


# -------------------------------------------------------------- sync walls


async def test_personio_sync_watermark_and_conditional_get(db, runtime_factory):
    handler = _robots_or_feed("/xml", PERSONIO_BODY, "application/xml", '"personio-v1"')
    transport = _scoped_transport(runtime_factory, "personio", handler)
    source = await _make_source(
        db, key="personio", config={"tenant": "personio-gmbh", "language": "en"}
    )
    first = await sync_source(db, source, transport=transport)
    assert first["errors"] == [], first
    assert first["synced"] == 3
    assert source.sync_state.get("watermark") == "2016-10-10T11:33:38+00:00"
    assert source.sync_state.get("etag") == '"personio-v1"'

    second = await sync_source(db, source, transport=transport)
    assert second["synced"] == 0, "unchanged rows dedup by content hash"
    _, seen = runtime_factory
    conditional = [r for r in seen if r.url.path == "/xml"]
    assert conditional[1].headers.get("If-None-Match") == '"personio-v1"'


async def test_join_sync_pages_and_normalizes_salary(db, runtime_factory):
    handler = _robots_or_feed(
        "/api/public/companies/54/jobs", JOIN_BODY, "application/json", '"join-v1"'
    )
    transport = _scoped_transport(runtime_factory, "join_com", handler)
    source = await _make_source(
        db, key="join_com", config={"company_id": 54, "company_slug": "join"}
    )
    result = await sync_source(db, source, transport=transport)
    assert result["errors"] == [], result
    assert result["synced"] == 3
    assert source.sync_state.get("watermark") == "2025-04-28T08:08:26.215000+00:00"
    _, seen = runtime_factory
    api_calls = [r for r in seen if r.url.path == "/api/public/companies/54/jobs"]
    assert api_calls[0].url.params.get("pageSize") == "5"
    assert api_calls[0].url.params.get("page") == "1"


async def test_recruitee_sync_upserts(db, runtime_factory):
    handler = _robots_or_feed("/api/offers/", RECRUITEE_BODY, "application/json", '"rec-v1"')
    transport = _scoped_transport(runtime_factory, "recruitee", handler)
    source = await _make_source(db, key="recruitee", config={"company": "bunq"})
    result = await sync_source(db, source, transport=transport)
    assert result["errors"] == [], result
    assert result["synced"] == 3
    assert source.sync_state.get("watermark") == "2026-10-12T13:59:52+00:00"


async def test_teamtailor_sync_upserts(db, runtime_factory):
    handler = _robots_or_feed("/jobs.json", TEAMTAILOR_BODY, "application/json", '"tt-v1"')
    transport = _scoped_transport(runtime_factory, "teamtailor", handler)
    source = await _make_source(db, key="teamtailor", config={"company": "career"})
    result = await sync_source(db, source, transport=transport)
    assert result["errors"] == [], result
    assert result["synced"] == 2
    assert source.sync_state.get("watermark") == "2026-07-24T07:05:16+00:00"


async def test_stepstone_xing_sync_uses_the_sealed_slot(db, runtime_factory):
    feed_url = "https://jobs.example.org/stepstone-alert.rss"
    handler = _robots_or_feed("/stepstone-alert.rss", RSS_BODY, "application/rss+xml", '"rss-v1"')
    transport = _scoped_transport(runtime_factory, "stepstone_xing", handler)
    source = await _make_source(
        db,
        key="stepstone_xing",
        config={"provider": "stepstone"},
        secrets={"feed_url": encrypt_secret(feed_url) or ""},
    )
    assert decrypt_secret(source.secrets["feed_url"]) == feed_url
    result = await sync_source(db, source, transport=transport)
    assert result["errors"] == [], result
    assert result["synced"] == 2
    assert source.sync_state.get("watermark") == "2024-06-16T17:30:51+00:00"


async def test_stepstone_xing_without_slot_reports_needs_secret(db):
    source = await _make_source(db, key="stepstone_xing", config={"provider": "xing"})
    result = await sync_source(db, source)
    assert result["synced"] == 0
    assert "needs-secret" in result["error"]


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    reset_registry()
