"""MCP v2 (plan 119): token lifecycle, client setup, read-only scope and
proposal-backed writes.

The MCP protocol calls go through the app's own ASGI endpoint over the
suite's loopback base URL (the same transport every REST call uses) —
never an external MCP server process.
"""

import json
import uuid

import pytest

from conftest import API, BASE_URL, api_headers


def _json(response) -> dict:
    for line in response.text().splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return response.json() if response.text().strip() else {}


def _mcp(page, token: str, method: str, params: dict | None = None, *, session: str | None = None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if session:
        headers["mcp-session-id"] = session
    response = page.request.post(
        f"{BASE_URL}/mcp",
        data=json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        ),
        headers=headers,
    )
    return response


def _connect(page, token: str) -> tuple[str, list[str]]:
    init = _mcp(
        page,
        token,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "e2e", "version": "0"},
        },
    )
    assert init.status == 200, init.text()
    session = init.headers.get("mcp-session-id")
    assert session
    listing = _mcp(page, token, "tools/list", session=session)
    assert listing.status == 200, listing.text()
    tools = [entry["name"] for entry in _json(listing)["result"]["tools"]]
    return session, tools


def _reset_tokens(page) -> None:
    rows = page.request.get(f"{API}/ai/mcp/tokens", headers=api_headers()).json()
    for row in rows:
        if row["active"]:
            page.request.delete(f"{API}/ai/mcp/tokens/{row['id']}", headers=api_headers())


def test_mcp_token_lifecycle_scope_and_proposal_write(page) -> None:
    status = page.request.get(f"{API}/ai/mcp/status", headers=api_headers())
    if status.status == 403:
        pytest.skip("e2e user is not an admin")
    assert status.ok, status.text()
    _reset_tokens(page)

    # Settings surface renders the endpoint + snippets.
    page.goto(f"{BASE_URL}/settings/tools?section=connectors")
    page.wait_for_selector('[data-testid="mcp-server-section"]')
    endpoint = page.get_by_test_id("mcp-endpoint").inner_text()
    assert endpoint.endswith("/mcp")
    assert "mcp-remote" in page.get_by_test_id("mcp-snippet").inner_text()

    # Mint a read token through the UI; the secret is shown once.
    page.get_by_test_id("mcp-token-label").fill("E2E laptop")
    page.get_by_test_id("mcp-mint-token").click()
    page.get_by_test_id("mcp-minted-token").wait_for(state="visible", timeout=20_000)
    read_secret = (
        page.get_by_test_id("mcp-minted-token").locator("code").first.inner_text().strip()
    )
    assert read_secret and "YOUR_MCP_TOKEN" not in read_secret

    # Read-only token: read tools are visible, write tools are absent.
    _session, tools = _connect(page, read_secret)
    assert "my_applications" in tools
    assert "application_transition" not in tools
    assert "profile_update" not in tools

    # Rotation invalidates the predecessor immediately (no-BC).
    tokens = page.request.get(f"{API}/ai/mcp/tokens", headers=api_headers()).json()
    read_row = next(row for row in tokens if row["label"] == "E2E laptop")
    rotated = page.request.post(
        f"{API}/ai/mcp/tokens/{read_row['id']}/rotate", headers=api_headers()
    )
    assert rotated.ok, rotated.text()
    new_secret = rotated.json()["token"]
    stale = _mcp(
        page,
        read_secret,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "e2e", "version": "0"},
        },
    )
    assert stale.status == 401, "the rotated-out token must die"

    # Admin write switch + a write-scope token: the write tool appears.
    enabled = page.request.put(
        f"{API}/ai/mcp/settings",
        data=json.dumps({"write_enabled": True}),
        headers=api_headers({"Content-Type": "application/json"}),
    )
    assert enabled.ok, enabled.text()
    assert "application_transition" in enabled.json()["write_tools"]

    minted = page.request.post(
        f"{API}/ai/mcp/tokens",
        data=json.dumps({"label": "E2E writer", "scopes": ["read", "write"]}),
        headers=api_headers({"Content-Type": "application/json"}),
    )
    assert minted.status == 201, minted.text()
    write_secret = minted.json()["token"]
    session, tools = _connect(page, write_secret)
    assert "application_transition" in tools

    # Track a posting, then make the MCP write call: it must be a card.
    posting = page.request.get(f"{API}/postings", headers=api_headers()).json()["items"]
    posting_id = next(item["id"] for item in posting if item.get("ref") == "E2E00001")
    application = page.request.post(
        f"{API}/me/applications",
        data=json.dumps({"posting_id": posting_id}),
        headers=api_headers({"Content-Type": "application/json"}),
    ).json()

    call = _mcp(
        page,
        write_secret,
        "tools/call",
        {
            "name": "application_transition",
            "arguments": {"application_id": application["id"], "stage": "interview"},
        },
        session=session,
    )
    assert call.status == 200, call.text()
    payload = json.loads(_json(call)["result"]["content"][0]["text"])
    assert payload["status"] == "awaiting_approval"
    detail = page.request.get(
        f"{API}/me/applications/{application['id']}", headers=api_headers()
    ).json()
    assert detail["stage"] == "applied", "the write tool never mutates directly"

    # The card renders with its MCP origin and resolves through the service.
    page.reload()
    page.wait_for_selector('[data-testid="mcp-server-section"]')
    card = page.get_by_test_id(f"mcp-proposal-{payload['proposal_id']}")
    card.wait_for(state="visible", timeout=20_000)
    assert "E2E writer" in card.inner_text()
    page.get_by_test_id(f"mcp-approve-{payload['proposal_id']}").click()
    page.wait_for_selector(f'[data-testid="mcp-proposal-{payload["proposal_id"]}"]', state="detached")
    detail = page.request.get(
        f"{API}/me/applications/{application['id']}", headers=api_headers()
    ).json()
    assert detail["stage"] == "interview"

    # Revoke both tokens: subsequent MCP calls are rejected.
    rows = page.request.get(f"{API}/ai/mcp/tokens", headers=api_headers()).json()
    for row in rows:
        if row["active"]:
            assert page.request.delete(
                f"{API}/ai/mcp/tokens/{row['id']}", headers=api_headers()
            ).status == 204
    dead = _mcp(
        page,
        write_secret,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "e2e", "version": "0"},
        },
    )
    assert dead.status == 401

    # Audit rows exist for the write call.
    audit = page.request.get(f"{API}/ai/mcp/audit", headers=api_headers()).json()
    assert any(
        row["tool"] == "application_transition" and row["label"] == "E2E writer"
        for row in audit
    )
    assert uuid.UUID(payload["proposal_id"])
