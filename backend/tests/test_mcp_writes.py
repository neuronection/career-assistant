"""MCP write scope (plan 119.4): opt-in, proposal-backed.

A write token + the admin switch are the two keys. Every write call is an
ADR-0015 Class-B card — its origin carries the MCP token label and request
id, and approval resolves through the same service the REST forms use.
Read-only tokens never see (and cannot call) write tools.
"""

from uuid import UUID

from sqlalchemy import select

from app.models.profile_proposal_model import ProfileProposal
from app.services.admin import mcp_tokens
from app.services.postings.applications_service import ApplicationService
from app.services.profile_proposal_service import ProfileProposalService
from tests.conftest import _make_posting, _uid
from tests.mcp_probe import mcp_probe, read_token, tool_payload, write_token


async def test_write_tools_need_scope_and_the_admin_switch(client, auth_headers, db, monkeypatch):
    token = await read_token(db, auth_headers)
    async with mcp_probe(db, token, monkeypatch) as probe:
        assert "application_transition" not in await probe.tools()

    write = await write_token(db, auth_headers)
    async with mcp_probe(db, write, monkeypatch) as probe:
        tools = set(await probe.tools())
    assert {"profile_update", "application_transition", "cv_ops"} <= tools

    await mcp_tokens.set_write_enabled(db, False)
    await db.commit()
    async with mcp_probe(db, write, monkeypatch) as probe:
        tools = set(await probe.tools())
    assert "application_transition" not in tools, "write off ⇒ write tools absent"


async def test_read_token_cannot_call_a_write_tool(client, auth_headers, db, monkeypatch):
    await mcp_tokens.set_write_enabled(db, True)
    await db.commit()
    token = await read_token(db, auth_headers)
    async with mcp_probe(db, token, monkeypatch) as probe:
        result = await probe.call("profile_update", {"kind": "user_skill", "action": "create"})
    assert (result.get("result") or {}).get("isError") is True or "error" in result


async def test_write_call_is_a_proposal_that_resolves_through_the_service(
    client, auth_headers, db, source, monkeypatch
):
    posting = await _make_posting(db, source, external_id="mcp-write-1")
    application = await ApplicationService(db).create(UUID(_uid(auth_headers)), posting.id)
    token = await write_token(db, auth_headers, label="MCP CLI")

    async with mcp_probe(db, token, monkeypatch) as probe:
        response = await probe.call(
            "application_transition",
            {"application_id": str(application.id), "stage": "interview"},
        )
    payload = tool_payload(response)
    assert payload["status"] == "awaiting_approval"

    proposal = (
        (
            await db.execute(
                select(ProfileProposal).where(ProfileProposal.id == UUID(payload["proposal_id"]))
            )
        )
        .scalars()
        .one()
    )
    assert proposal.source == "mcp"
    assert proposal.origin["channel"] == "mcp"
    assert proposal.origin["token_label"] == "MCP CLI"
    assert proposal.origin["request_id"]
    await db.refresh(application)
    assert application.stage == "applied", "the write tool never mutates directly"

    resolved, applied, _already = await ProfileProposalService(db).approve(
        UUID(_uid(auth_headers)), proposal.id
    )
    assert resolved.status == "approved"
    assert applied["kind"] == "tool_execution"
    await db.refresh(application)
    assert application.stage == "interview"


async def test_profile_update_emits_a_real_class_b_profile_card(
    client, auth_headers, db, profile_ready, seeded_catalog, monkeypatch
):
    token = await write_token(db, auth_headers, label="Profile Client")
    async with mcp_probe(db, token, monkeypatch) as probe:
        response = await probe.call(
            "profile_update",
            {
                "kind": "user_skill",
                "action": "create",
                "payload": {"skill_key": "programming", "level": 4},
            },
        )
    payload = tool_payload(response)
    assert payload["status"] == "awaiting_approval"

    proposal = (
        (
            await db.execute(
                select(ProfileProposal).where(ProfileProposal.id == UUID(payload["proposal_id"]))
            )
        )
        .scalars()
        .one()
    )
    assert proposal.kind == "user_skill"
    assert proposal.source == "mcp"
    assert proposal.origin["token_label"] == "Profile Client"
    assert proposal.status == "pending"


async def test_write_call_is_audited_with_the_origin_request(
    client, auth_headers, db, source, monkeypatch
):
    from app.models.ai_model import AIGeneration
    from app.models.enums import AITaskType

    posting = await _make_posting(db, source, external_id="mcp-write-2")
    application = await ApplicationService(db).create(UUID(_uid(auth_headers)), posting.id)
    token = await write_token(db, auth_headers, label="Audit CLI")
    async with mcp_probe(db, token, monkeypatch) as probe:
        await probe.call(
            "application_transition", {"application_id": str(application.id), "note": "Called"}
        )

    audit = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.MCP_TOOL_CALL.value,
                    AIGeneration.prompt == "mcp-server:Audit CLI:application_transition",
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.status == "ok"
    assert (audit.output or {})["tool"] == "application_transition"
    proposal_origin = (
        (await db.execute(select(ProfileProposal).where(ProfileProposal.source == "mcp")))
        .scalars()
        .first()
    )
    assert proposal_origin is not None
    assert proposal_origin.origin["request_id"] == (audit.output or {})["request_id"]
