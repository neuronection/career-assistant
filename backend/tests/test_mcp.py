"""MCP server + client bridge (plan 119.2).

Token lifecycle, scope projection and the per-token tool/resource
surface live in ``test_mcp_surface.py``; this module keeps the client
bridge (registration, discovery, namespaced + audited invocation) and
the admin API round-trip.
"""

from uuid import UUID

import pytest
from sqlalchemy import select

from app.extensions.mcp_bridge import MCPBridgeService
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType
from tests.conftest import _uid


async def test_bridge_registration_discovery_and_invoke(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    from fastmcp import Client, FastMCP

    remote = FastMCP("external")

    @remote.tool
    def echo(text: str) -> str:
        """Echo the text back."""
        return f"echo: {text}"

    service = MCPBridgeService(db)
    monkeypatch.setattr(service, "_client_for", lambda row: (Client(remote), None))

    row = await service.register(
        name="external-1",
        transport="http",
        url="http://127.0.0.1:1/mcp",
        token="bridge-token",
        created_by=UUID(_uid(auth_headers)),
    )
    assert row.enabled is False

    # Invoke before enable/refresh → refused.
    with pytest.raises(Exception):  # noqa: B017 -- intentional broad rejection assertion
        await service.invoke(row.id, "echo", {"text": "hi"}, user_id=None)

    refreshed = await service.refresh(row.id)
    assert [t["name"] for t in refreshed.discovered_tools] == ["echo"]
    assert refreshed.enabled_tools == [], "discovery never auto-enables"

    with pytest.raises(Exception):  # noqa: B017 -- intentional broad rejection assertion
        await service.invoke(row.id, "echo", {"text": "hi"}, user_id=None)

    await service.set_enabled(row.id, True)
    await service.set_tool_enabled(row.id, "echo", True)
    result = await service.invoke(row.id, "echo", {"text": "hi"}, user_id=None)
    assert result["content"] == ["echo: hi"]
    assert result["is_error"] is False

    audit = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == AITaskType.MCP_TOOL_CALL.value)
            )
        )
        .scalars()
        .one()
    )
    assert audit.prompt == f"mcp:{row.name}:echo"
    assert audit.provider == "mcp"
    assert audit.model == "external-1"


async def test_bridge_admin_api_round_trip(
    client, client_admin_headers, profile_ready, seeded_catalog, db
):
    status = await client.get("/api/v1/ai/mcp/status", headers=client_admin_headers)
    assert status.status_code == 200, status.text
    assert status.json()["write_enabled"] is False
    assert status.json()["write_tools"] == []
    assert status.json()["endpoint"].endswith("/mcp")

    minted = await client.post(
        "/api/v1/ai/mcp/tokens",
        json={"label": "Desktop", "scopes": ["read"]},
        headers=client_admin_headers,
    )
    assert minted.status_code == 201, minted.text
    assert minted.json()["token"]
    assert minted.json()["scopes"] == ["read"]

    write_denied = await client.post(
        "/api/v1/ai/mcp/tokens",
        json={"label": "Writer", "scopes": ["read", "write"]},
        headers=client_admin_headers,
    )
    assert write_denied.status_code == 400, "write scope needs the admin switch"

    enabled = await client.put(
        "/api/v1/ai/mcp/settings",
        json={"write_enabled": True},
        headers=client_admin_headers,
    )
    assert enabled.status_code == 200
    assert "application_transition" in enabled.json()["write_tools"]

    listed = await client.get("/api/v1/ai/mcp/tokens", headers=client_admin_headers)
    assert [row["label"] for row in listed.json()] == ["Desktop"]
    token_id = listed.json()[0]["id"]

    rotated = await client.post(
        f"/api/v1/ai/mcp/tokens/{token_id}/rotate", headers=client_admin_headers
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["token"] != minted.json()["token"]
    assert rotated.json()["rotated_from_id"] == token_id

    revoked = await client.delete(
        f"/api/v1/ai/mcp/tokens/{rotated.json()['id']}", headers=client_admin_headers
    )
    assert revoked.status_code == 204

    registered = await client.post(
        "/api/v1/ai/mcp/servers",
        json={
            "name": "bridge-1",
            "transport": "http",
            "url": "http://127.0.0.1:9/mcp",
        },
        headers=client_admin_headers,
    )
    assert registered.status_code == 201, registered.text
    listing = await client.get("/api/v1/ai/mcp/servers", headers=client_admin_headers)
    names = [s["name"] for s in listing.json()]
    assert names == ["bridge-1"]
    assert listing.json()[0]["enabled"] is False


async def test_mcp_admin_surface_requires_an_admin(client):
    from tests.conftest import auth_kit, mint_session_headers

    member_headers = mint_session_headers(email="mcp-member@example.com")
    user = auth_kit().users.get_by_email("mcp-member@example.com")
    if user is not None and user.is_admin:
        auth_kit().users.set_admin(user.id, False)
    for path in ("status", "tokens", "tools", "audit"):
        response = await client.get(f"/api/v1/ai/mcp/{path}", headers=member_headers)
        assert response.status_code == 403, (path, response.text)
