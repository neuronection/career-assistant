"""MCP connection surface (plan 119.2): token auth over ``mcp_tokens``,
the read-scope registry projection, rotation/revocation and the audit
ledger — all over the ASGI transport (never a real socket).
"""

from uuid import UUID

import pytest
from sqlalchemy import select

from app.ai.tools import list_tools
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType
from app.services import mcp_tokens
from app.services.applications_service import ApplicationService
from tests.conftest import _make_posting, _uid
from tests.mcp_probe import mcp_probe, read_token, tool_payload


async def test_mounted_endpoint_routes_mcp_without_a_redirect(client):
    """The FastAPI mount must reach the MCP app at ``/mcp`` (a 405 here
    was the mount/trailing-slash bug: the mounted app served at its root
    while Starlette stripped the prefix)."""
    from tests.mcp_probe import INITIALIZE

    response = await client.post(
        "/mcp",
        json=INITIALIZE,
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 401, "expected the MCP auth challenge, not a routing error"


async def test_anonymous_requests_are_rejected(client, db, monkeypatch):
    async with mcp_probe(db, None, monkeypatch) as probe:
        assert probe.initialize is not None
        assert probe.initialize.status_code == 401


async def test_read_token_sees_the_read_scope_registry_projection(
    client, auth_headers, db, monkeypatch
):
    token = await read_token(db, auth_headers)
    async with mcp_probe(db, token, monkeypatch) as probe:
        tools = set(await probe.tools())
    expected = {
        entry["key"]
        for entry in list_tools()
        if entry.get("kind") == "tool" and entry["scope"] == "read"
    }
    assert tools == expected, "MCP surface = the read-scope registry projection"
    assert "profile_update" not in tools
    assert "application_transition" not in tools
    assert "cv_ops" not in tools


async def test_instance_token_cannot_use_user_scoped_tools(client, db, monkeypatch):
    _row, plaintext = await mcp_tokens.mint(db, None, label="Unbound", scopes=["read"])
    await db.commit()
    async with mcp_probe(db, plaintext, monkeypatch) as probe:
        result = await probe.call("my_applications", {})
    assert (result.get("result") or {}).get("isError") is True or "error" in result


async def test_read_call_is_grounded_and_audited(client, auth_headers, db, source, monkeypatch):
    posting = await _make_posting(db, source, external_id="mcp-surface-1")
    await ApplicationService(db).create(UUID(_uid(auth_headers)), posting.id)
    token = await read_token(db, auth_headers, label="Claude Desktop")

    async with mcp_probe(db, token, monkeypatch) as probe:
        response = await probe.call("my_applications", {"open_only": True})
    payload = tool_payload(response)
    assert payload["applications"][0]["posting_ref"] == posting.ref

    audit = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.MCP_TOOL_CALL.value,
                    AIGeneration.provider == "mcp",
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.prompt == "mcp-server:Claude Desktop:my_applications"
    assert audit.status == "ok"
    assert (audit.output or {})["tool"] == "my_applications"
    assert (audit.output or {})["request_id"]


async def test_rotated_and_revoked_tokens_stop_authenticating(
    client, auth_headers, db, monkeypatch
):
    token = await read_token(db, auth_headers)
    row = (
        (await db.execute(select(mcp_tokens.McpToken).order_by(mcp_tokens.McpToken.created_at)))
        .scalars()
        .first()
    )
    successor, new_token = await mcp_tokens.rotate(db, row.id)
    await db.commit()

    async with mcp_probe(db, token, monkeypatch) as probe:
        assert probe.initialize.status_code == 401
    async with mcp_probe(db, new_token, monkeypatch) as probe:
        assert probe.initialize.status_code == 200
    await db.refresh(successor)
    assert successor.rotated_from_id == row.id

    await mcp_tokens.revoke(db, successor.id)
    await db.commit()
    async with mcp_probe(db, new_token, monkeypatch) as probe:
        assert probe.initialize.status_code == 401


def test_token_scope_vocabulary_is_closed():
    from app.core.errors import ValidationError

    assert mcp_tokens.normalize_scopes([]) == ["read"]
    assert mcp_tokens.normalize_scopes(["read", "write"]) == ["read", "write"]
    with pytest.raises(ValidationError):
        mcp_tokens.normalize_scopes(["admin"])
