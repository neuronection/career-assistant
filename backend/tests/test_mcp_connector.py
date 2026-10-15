"""The T3 script-tier wall (plan 32 Phase 2 / ADR-0040 D9+D22).

Covers the ``mcp`` builtin connector end to end:

* structural: allowlist-off ⇒ the connector is invisible (the tier is
  disabled by default); allowlist-on ⇒ registered with an honest
  manifest (no ``net`` domains — the script process's sockets are
  outside the host perimeter, D22);
* config: transport fields, per-tool allowlist, 5-120 s timeout bound,
  the x-secret law (a token value in config is a registration throw);
* app-side validation: EVERY returned row is checked against
  RawPosting (required fields, http(s) urls, char/size caps, 300-item
  cap) — malformed rows become typed ``invalid`` errors and never
  persist; envelope violations are typed ``protocol`` errors;
* e2e: the connector-template reference server (spawned as a REAL
  local stdio subprocess — no external network) feeds postings through
  sync_source → upsert → dedup with source attribution, and every tool
  call lands on the audit funnel (one ``mcp_tool_call`` row);
* resilience: a tool that outlives its timeout fails the source with a
  typed error — the source is marked failing and other sources keep
  syncing (never a crash).

The byte-identical fixture ``fixtures/mcp_template_server.py`` is the
CI-safe copy of ``../career-connector-template/server.py``; when the
sibling template repo is checked out (family development layout) the
canonical copy is drift-checked and exercised too.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.errors import ValidationError
from app.extensions.registry import (
    get_connector,
    list_connectors,
    reset_registry,
    validate_manifest,
)
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType
from app.models.posting_model import JobPosting, JobSource
from app.services.postings_service import sync_source

TEMPLATE_DIR = Path(__file__).resolve().parents[2].parent / "career-connector-template"
FIXTURE_SERVER = Path(__file__).resolve().parent / "fixtures" / "mcp_template_server.py"

GOOD_ROW = {
    "external_id": "good-1",
    "title": "Platform Engineer",
    "org": "FakeCo",
    "url": "https://jobs.example.com/good-1",
    "skills_raw": ["python"],
    "raw": {"description": "Build the platform."},
}


@pytest.fixture
def mcp_connector(monkeypatch):
    """The mcp connector, allowlisted (its default state is invisible)."""
    monkeypatch.setattr(settings, "connector_plugins_allowlist", ["mcp"])
    reset_registry()
    yield get_connector("mcp")
    reset_registry()


@pytest.fixture
def fake_server(mcp_connector, monkeypatch):
    """Install an in-memory FastMCP server as the connector's endpoint
    (transport injection — no subprocess, no network). Whatever the
    function is called, it is exposed AS the fetch tool so the default
    config contract holds."""

    def install(tool_fn, *, name="fake") -> None:
        from fastmcp import Client, FastMCP

        remote = FastMCP(name)
        remote.tool(tool_fn, name="fetch_postings")
        monkeypatch.setattr(mcp_connector, "_client_for", lambda cfg, token: Client(remote))

    return install


async def _make_source(db, *, key: str, config: dict) -> JobSource:
    source = JobSource(key=key, connector_key="mcp", config=config, enabled=True)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


def _stdio_command(script: Path) -> str:
    return f'"{sys.executable}" "{script}"'


# ------------------------------------------------------------- structural


async def test_allowlist_off_makes_the_script_tier_invisible():
    """Default state: the mcp connector is unknown — the catalog does
    not list it and the registry refuses it (structurally disabled)."""
    keys = [entry["key"] for entry in list_connectors()]
    assert "mcp" not in keys
    with pytest.raises(ValidationError):
        get_connector("mcp")


async def test_allowlist_on_registers_an_honest_manifest(mcp_connector):
    manifest = validate_manifest(mcp_connector)
    assert manifest["id"] == "career-mcp"
    assert manifest["kind"] == "connector"
    # D22 honesty: the T3 perimeter is disclosed in prose, never
    # smuggled in as a host-side net capability.
    assert "net" not in manifest["capabilities"]
    assert not manifest.get("domains")
    assert manifest["capabilities"] == ["sync", "secrets"]
    assert "perimeter" in manifest["description"]
    entry = next(e for e in list_connectors() if e["key"] == "mcp")
    assert entry["builtin"] is True
    assert entry["secret_fields"] == ["token"]


# ---------------------------------------------------------------- config


async def test_config_round_trip_and_transport_rules(mcp_connector):
    validated = mcp_connector.validate_config({"transport": "stdio", "command": "python server.py"})
    assert validated == mcp_connector.validate_config(validated)
    assert validated["tool"] == "fetch_postings"
    assert validated["timeout_seconds"] == 30

    with pytest.raises(ValidationError):
        mcp_connector.validate_config({"transport": "stdio"})
    with pytest.raises(ValidationError):
        mcp_connector.validate_config({"transport": "http", "url": "ftp://x"})
    with pytest.raises(ValidationError):
        mcp_connector.validate_config(
            {
                "transport": "stdio",
                "command": "python s.py",
                "tool": "other_tool",
                "allowed_tools": "fetch_postings,fetch_full",
            }
        )
    with pytest.raises(ValidationError):
        mcp_connector.validate_config(
            {"transport": "stdio", "command": "python s.py", "timeout_seconds": 4}
        )
    with pytest.raises(ValidationError):
        mcp_connector.validate_config(
            {"transport": "stdio", "command": "python s.py", "timeout_seconds": 121}
        )


async def test_secret_values_never_live_in_config(mcp_connector):
    with pytest.raises(ValidationError):
        mcp_connector.validate_config(
            {"transport": "stdio", "command": "python s.py", "token": "tok-123"}
        )


# --------------------------------------------------- app-side row validation


async def test_malformed_rows_become_typed_errors_and_never_persist(
    db, seeded_catalog, fake_server
):
    def bad_rows(config: dict, state: dict) -> dict:
        return {
            "items": [
                GOOD_ROW,
                {"title": "missing external id"},
                {"external_id": "bad-url", "title": "FTP link", "url": "ftp://jobs.example/1"},
                "not-an-object",
                {
                    "external_id": "fat-raw",
                    "title": "Oversized raw bag",
                    "raw": {"blob": "x" * 9_000},
                },
            ],
            "next_state": {},
        }

    fake_server(bad_rows)
    source = await _make_source(
        db, key="mcp-bad", config={"transport": "stdio", "command": "unused"}
    )
    result = await sync_source(db, source)
    assert result["synced"] == 1
    codes = {error["code"] for error in result["errors"]}
    assert codes == {"invalid"}
    assert len(result["errors"]) == 4
    postings = (
        (await db.execute(select(JobPosting).where(JobPosting.source_id == source.id)))
        .scalars()
        .all()
    )
    assert [p.external_id for p in postings] == ["good-1"]


async def test_item_cap_drops_excess_rows_with_one_typed_error(db, seeded_catalog, fake_server):
    def flood(config: dict, state: dict) -> dict:
        return {
            "items": [
                {
                    "external_id": f"row-{i}",
                    "title": f"Job {i}",
                    "url": "https://jobs.example.com/x",
                }
                for i in range(302)
            ],
            "next_state": {},
        }

    fake_server(flood)
    source = await _make_source(
        db, key="mcp-flood", config={"transport": "stdio", "command": "unused"}
    )
    result = await sync_source(db, source)
    assert result["synced"] == 300
    assert [error["code"] for error in result["errors"]] == ["invalid"]
    assert "300-item cap" in result["errors"][0]["detail"]


async def test_envelope_violations_are_typed_protocol_errors(mcp_connector, fake_server):
    def not_json(config: dict, state: dict) -> str:
        return "definitely not json"

    fake_server(not_json)
    result = await mcp_connector.fetch({"transport": "stdio", "command": "unused"}, {}, secrets={})
    assert not result.items
    assert result.partial_errors[0].code == "protocol"

    def bare_list(config: dict, state: dict) -> list:
        return [GOOD_ROW]

    fake_server(bare_list)
    result = await mcp_connector.fetch({"transport": "stdio", "command": "unused"}, {}, secrets={})
    assert result.partial_errors[0].code == "protocol"

    def raising(config: dict, state: dict) -> dict:
        raise RuntimeError("upstream exploded")

    fake_server(raising)
    result = await mcp_connector.fetch({"transport": "stdio", "command": "unused"}, {}, secrets={})
    assert result.partial_errors[0].code == "provider"


async def test_secrets_never_cross_to_the_tool(mcp_connector, fake_server):
    seen: dict = {}

    def fetch(config: dict, state: dict) -> dict:
        seen.update(config)
        return {"items": [GOOD_ROW], "next_state": {}}

    fake_server(fetch)
    result = await mcp_connector.fetch(
        {"transport": "stdio", "command": "python s.py"},
        {},
        secrets={"token": "sealed-slot-value"},
    )
    assert len(result.items) == 1
    assert "token" not in seen
    assert "sealed-slot-value" not in json.dumps(seen)


async def test_every_tool_call_writes_one_audit_row(db, seeded_catalog, fake_server):
    def fetch(config: dict, state: dict) -> dict:
        return {"items": [GOOD_ROW], "next_state": {}}

    fake_server(fetch)
    source = await _make_source(
        db, key="mcp-audit", config={"transport": "stdio", "command": "unused"}
    )
    await sync_source(db, source)
    rows = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == AITaskType.MCP_TOOL_CALL.value)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].prompt == "mcp:mcp-audit:fetch_postings"
    assert rows[0].provider == "mcp"


# ------------------------------------------------------- the e2e subprocess


def _server_paths() -> list[Path]:
    """The CI-safe fixture copy always runs; the canonical template repo
    joins when the sibling checkout exists (family dev layout)."""
    paths = [FIXTURE_SERVER]
    if (TEMPLATE_DIR / "server.py").exists():
        paths.append(TEMPLATE_DIR / "server.py")
    return paths


@pytest.fixture(params=_server_paths(), ids=lambda p: p.parent.name)
def template_server(request) -> Path:
    return request.param


async def test_template_server_feeds_postings_end_to_end(
    db, seeded_catalog, mcp_connector, template_server
):
    """The Phase-2 wall: a template-derived script spawns as a local
    stdio subprocess, syncs through the REAL sync_source → upsert →
    dedup path, postings land attributed to the source, the etag cursor
    short-circuits the second sync, and the tool call is audited."""
    assert template_server.exists(), f"template server missing: {template_server}"
    source = await _make_source(
        db,
        key="template",
        config={"transport": "stdio", "command": _stdio_command(template_server)},
    )

    first = await sync_source(db, source)
    assert first["errors"] == []
    assert first["synced"] == 3
    postings = (
        (
            await db.execute(
                select(JobPosting)
                .where(JobPosting.source_id == source.id)
                .order_by(JobPosting.external_id)
            )
        )
        .scalars()
        .all()
    )
    assert [p.external_id for p in postings] == ["default-1", "default-2", "default-3"]
    for posting in postings:
        assert posting.source_id == source.id
        assert posting.org == "Reference Systems"
        assert posting.url.startswith("https://jobs.example.com/")
        assert posting.mapping_reason  # the fast mapping pass ran
    assert source.sync_state.get("etag")

    second = await sync_source(db, source)
    assert second["synced"] == 0, "the etag cursor must short-circuit the second sync"

    audit = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == AITaskType.MCP_TOOL_CALL.value)
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 2, "one audit row per tool call"
    assert all(row.prompt == "mcp:template:fetch_postings" for row in audit)


async def test_slow_tool_times_out_typed_and_source_keeps_going(
    db, seeded_catalog, mcp_connector, tmp_path
):
    """The timeout wall: a tool that outlives its 5 s budget fails its
    own source with a typed error (unreachable, retryable) — the source
    is marked failing and a healthy source syncs fine right after."""
    slow = tmp_path / "slow_server.py"
    slow.write_text(
        "import asyncio\n"
        "from fastmcp import FastMCP\n\n"
        "mcp = FastMCP('slow')\n\n\n"
        "@mcp.tool\n"
        "async def fetch_postings(config: dict, state: dict) -> dict:\n"
        "    await asyncio.sleep(60)\n"
        "    return {'items': [], 'next_state': {}}\n\n\n"
        "if __name__ == '__main__':\n"
        "    mcp.run()\n",
        encoding="utf-8",
    )
    stuck = await _make_source(
        db,
        key="slow",
        config={
            "transport": "stdio",
            "command": _stdio_command(slow),
            "timeout_seconds": 5,
        },
    )
    healthy = await _make_source(
        db,
        key="healthy",
        config={"transport": "stdio", "command": _stdio_command(FIXTURE_SERVER)},
    )
    result = await sync_source(db, stuck)
    assert result["synced"] == 0
    assert result["errors"][0]["code"] == "unreachable"
    assert "timed out" in result["errors"][0]["detail"]
    assert "unreachable" in stuck.error

    after = await sync_source(db, healthy)
    assert after["synced"] == 3, "a failing T3 source never takes the sync path down"


# ------------------------------------------------- the generic admin API path


async def test_mcp_source_registers_and_probes_through_the_generic_api(
    client, auth_headers, db, seeded_catalog, mcp_connector, profile_ready
):
    """Zero-UI-change surfacing: the allowlisted mcp connector rides the
    SAME catalog-driven source form + probe endpoint as every other
    connector — and the probe writes its audit row too."""
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().first()
    user.is_admin = True
    await db.commit()

    created = await client.post(
        "/api/v1/admin/postings/sources",
        json={
            "key": "template-api",
            "connector_key": "mcp",
            "config": {
                "transport": "stdio",
                "command": _stdio_command(FIXTURE_SERVER),
            },
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    catalog = await client.get("/api/v1/admin/postings/connectors", headers=auth_headers)
    entry = next(c for c in catalog.json() if c["key"] == "mcp")
    assert entry["secret_fields"] == ["token"]
    assert entry["manifest"]["capabilities"] == ["sync", "secrets"]

    source_id = created.json()["id"]
    probe = await client.post(
        f"/api/v1/admin/postings/sources/{source_id}/probe", headers=auth_headers
    )
    assert probe.status_code == 200, probe.text
    assert probe.json()["ok"] is True
    assert probe.json()["items"] == 3

    audit = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == AITaskType.MCP_TOOL_CALL.value)
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1, "the probe's tool call is audited"
    assert audit[0].prompt == "mcp:template-api:fetch_postings"

    bad = await client.post(
        "/api/v1/admin/postings/sources",
        json={
            "key": "bad-mcp",
            "connector_key": "mcp",
            "config": {"transport": "stdio", "command": "x", "token": "in-config"},
        },
        headers=auth_headers,
    )
    assert bad.status_code == 400, "the x-secret law rejects plaintext tokens"


# ------------------------------------------------- template-repo fidelity


def test_fixture_copy_matches_the_canonical_template():
    """The CI-safe fixture is a byte-identical copy of the template
    repo's server — skipped loudly when the sibling checkout is absent
    (CI); the copy itself always runs in the e2e wall above."""
    canonical = TEMPLATE_DIR / "server.py"
    if not canonical.exists():
        pytest.skip(f"sibling template repo not checked out: {TEMPLATE_DIR}")
    assert FIXTURE_SERVER.read_bytes() == canonical.read_bytes(), (
        "fixtures/mcp_template_server.py drifted from career-connector-template/server.py"
    )


def test_template_manifest_validates_against_the_vendored_envelope():
    """Phase 3 will import this repo by git URL — its manifest must
    clear the vendored root (imported) schema today."""
    manifest_path = TEMPLATE_DIR / "manifest.json"
    if not manifest_path.exists():
        pytest.skip(f"sibling template repo not checked out: {TEMPLATE_DIR}")
    from app.extensions import contract

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2] / "contracts" / "extension-manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert contract.validate_manifest(manifest, schema) is None
