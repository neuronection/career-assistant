"""The Workable connector wall (plan 177): the public careers-widget API
as a bundled T1 source — the same free, no-credentials shape as the
Recruitee/Teamtailor feeds.

Fixtures are CAPTURED REAL payloads (2026-11-01, the skroutz account —
see ``fixtures/connectors/CAPTURES.md``); every wall rides the REAL
runtime stack (``sync_source`` → polite transport over
``httpx.MockTransport`` + an injected fake resolver — no network in unit
tests).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.extensions.builtin.job_boards import parse_workable_payload
from app.extensions.conformance import ConnectorConformanceTests
from app.extensions.registry import get_connector, list_connectors
from app.extensions.runtime.http import build_transport, reset_runtime
from app.services.postings.postings_service import sync_source

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "connectors"
WORKABLE_BODY = (FIXTURES / "workable_jobs.json").read_text(encoding="utf-8")

RESOLVER_MAP = {"apply.workable.com": ["93.184.216.50"]}


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

    def make_transport(handler, *, domains=None, config=None):
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


async def _make_source(db, *, key: str, config: dict):
    from app.models.posting_model import JobSource

    source = JobSource(key=key, connector_key="workable", config=config, enabled=True)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


def _feed_handler(body: str, etag: str | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path != "/api/v1/widget/accounts/skroutz":
            raise AssertionError(f"unexpected path {request.url.path}")
        headers = {"Content-Type": "application/json"}
        if etag:
            headers["ETag"] = etag
        return httpx.Response(200, text=body, headers=headers)

    return handler


def _scoped_transport(runtime_factory, handler):
    make_transport, _ = runtime_factory
    connector = get_connector("workable")
    return make_transport(handler, domains=frozenset(connector.capabilities.network_scopes or []))


def test_captured_shape():
    items, errors = parse_workable_payload(WORKABLE_BODY)
    assert errors == []
    assert len(items) == 9
    first = items[0]
    assert first.org == "Skroutz S.A"
    assert first.external_id
    assert first.title
    assert first.location.city == "Athens"
    assert first.location.country == "Greece"
    assert first.url.startswith("https://apply.workable.com/j/")
    assert first.posted_at is not None and first.posted_at.tzinfo is not None
    assert isinstance(first.raw.get("work_type"), str)
    # the extraction pipeline reads raw.description — the widget call must
    # always carry details=true or skills starve
    assert len(first.raw["description"]) > 200


def test_registers_with_manifest_and_docs():
    catalog = {entry["key"]: entry for entry in list_connectors()}
    entry = catalog["workable"]
    assert entry["manifest"]["domains"] == ["apply.workable.com"]
    assert entry["manifest"]["capabilities"] == ["net", "sync"]
    assert entry["manifest"]["supportsIncremental"] is True
    assert entry["manifest"]["docs"] == "docs/docs-tree.json"
    assert entry["secret_fields"] == []


class TestWorkableConformance(ConnectorConformanceTests):
    connector = get_connector("workable")
    config = {"account": "skroutz"}  # noqa: RUF012
    body = WORKABLE_BODY


async def test_sync_upserts_and_watermarks(db, runtime_factory):
    handler = _feed_handler(WORKABLE_BODY, '"workable-v1"')
    transport = _scoped_transport(runtime_factory, handler)
    source = await _make_source(db, key="skroutz", config={"account": "skroutz"})
    result = await sync_source(db, source, transport=transport)
    assert result["errors"] == [], result
    jobs = json.loads(WORKABLE_BODY)["jobs"]
    assert result["synced"] == len(jobs)
    dated = [job["published_on"] for job in jobs if job.get("published_on")]
    expected = min(dated)
    assert source.sync_state.get("watermark") == f"{expected}T00:00:00+00:00"


async def test_incremental_sync_uses_conditional_get(db, runtime_factory):
    handler = _feed_handler(WORKABLE_BODY, '"workable-v1"')
    transport = _scoped_transport(runtime_factory, handler)
    source = await _make_source(db, key="skroutz-cond", config={"account": "skroutz"})
    first = await sync_source(db, source, transport=transport)
    assert first["errors"] == []
    second = await sync_source(db, source, transport=transport)
    assert second["synced"] == 0, "the ETag short-circuit returns nothing to ingest"
