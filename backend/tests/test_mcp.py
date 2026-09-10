"""— MCP server (read-scope exposure, token auth, rate
limiting) and the client bridge (registration, discovery, namespaced +
audited invocation)."""

import asyncio

import pytest
from uuid import UUID
import threading

import httpx
from sqlalchemy import select

from tests.conftest import _uid

from app.ai.mcp_server import MCPTokenStore, build_mcp_asgi_app, build_mcp_server
from app.ai.tools.base import ToolScope
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType
from app.services.mcp_bridge_service import MCPBridgeService


async def test_server_exposes_exactly_the_read_scope_allowlist():
    from app.ai.tools import list_tools

    mcp = build_mcp_server()
    tools = {t.name for t in await mcp.list_tools()}
    read_tools = {t["key"] for t in list_tools() if t["scope"] == ToolScope.READ.value}
    assert tools == read_tools, "MCP surface = read-scope registry tools"
    assert "cv_set_template" not in tools, "write tools never exposed"


async def test_token_store_rotates_and_persists(tmp_path):
    store = MCPTokenStore(directory=tmp_path)
    assert store.read() in (None, {})
    first = store.rotate("11111111-1111-1111-1111-111111111111")
    assert store.read()["token"] == first["token"]
    second = store.rotate("22222222-2222-2222-2222-222222222222")
    assert second["token"] != first["token"], "rotation invalidates the old token"
    assert store.read()["user_id"] == "22222222-2222-2222-2222-222222222222"


async def test_http_transport_rejects_anonymous_and_accepts_token(
    tmp_path, unused_tcp_port, monkeypatch
):
    import uvicorn

    import app.ai.mcp_server as mcp_module

    store = MCPTokenStore(directory=tmp_path)
    info = store.rotate("11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(mcp_module, "_TOKEN_STORE", store)

    app = build_mcp_asgi_app()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=unused_tcp_port, log_level="error"
    )
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    await asyncio.sleep(0.8)
    try:
        base = f"http://127.0.0.1:{unused_tcp_port}/mcp"
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0"},
            },
        }
        async with httpx.AsyncClient(timeout=10) as http:
            anon = await http.post(
                base,
                json=initialize,
                headers={"Accept": "application/json, text/event-stream"},
            )
            assert anon.status_code == 401, "anonymous must be rejected"
            authed = await http.post(
                base,
                json=initialize,
                headers={
                    "Authorization": f"Bearer {info['token']}",
                    "Accept": "application/json, text/event-stream",
                },
            )
            assert authed.status_code == 200
    finally:
        server.should_exit = True


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
    with pytest.raises(Exception):
        await service.invoke(row.id, "echo", {"text": "hi"}, user_id=None)

    refreshed = await service.refresh(row.id)
    assert [t["name"] for t in refreshed.discovered_tools] == ["echo"]
    assert refreshed.enabled_tools == [], "discovery never auto-enables"

    with pytest.raises(Exception):
        await service.invoke(row.id, "echo", {"text": "hi"}, user_id=None)

    await service.set_enabled(row.id, True)
    await service.set_tool_enabled(row.id, "echo", True)
    result = await service.invoke(row.id, "echo", {"text": "hi"}, user_id=None)
    assert result["content"] == ["echo: hi"]
    assert result["is_error"] is False

    audit = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.MCP_TOOL_CALL.value
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.prompt == f"mcp:{row.name}:echo"
    assert audit.provider == "mcp"
    assert audit.model == "external-1"


async def test_bridge_admin_api_round_trip(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().first()
    user.is_admin = True
    await db.commit()

    from app.ai.mcp_server import token_store

    token_store()._file().unlink(missing_ok=True)
    status = await client.get("/api/v1/ai/mcp/token", headers=auth_headers)
    assert status.status_code == 200, status.text
    assert status.json()["provisioned"] is False

    rotated = await client.post("/api/v1/ai/mcp/token", headers=auth_headers)
    assert rotated.status_code == 200, rotated.text
    token = rotated.json()["token"]
    assert token and rotated.json()["bound_user_id"]

    after = await client.get("/api/v1/ai/mcp/token", headers=auth_headers)
    assert after.json()["provisioned"] is True

    registered = await client.post(
        "/api/v1/ai/mcp/servers",
        json={
            "name": "bridge-1",
            "transport": "http",
            "url": "http://127.0.0.1:9/mcp",
        },
        headers=auth_headers,
    )
    assert registered.status_code == 201, registered.text
    listing = await client.get("/api/v1/ai/mcp/servers", headers=auth_headers)
    names = [s["name"] for s in listing.json()]
    assert names == ["bridge-1"]
    assert listing.json()[0]["enabled"] is False
