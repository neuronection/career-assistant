"""The D20 destructive-confirm runtime funnel (plan 32 follow-up).

Wall for the charter law (D20 / ADR-0011 / ADR-0015 clause 5 +
clause 19): every chat tool carries its ADR-0011 risk class; at RUNTIME
``read-only`` is unchanged, ``state-changing`` rides per-grant
enablement (the tools catalog toggle), and a ``destructive`` tool call
CANNOT execute directly — it becomes an ADR-0015 Class-B card (the
existing proposal machinery: idempotent resolve, notification fanout,
cross-session inbox) and executes exactly once on that card's approval,
never from model output, never grant-bypassed.

The fixture is the charter's own shape: a T1 bundled connector
contributing a destructive chat tool declared in its manifest
(``chat-tools`` + ``tools`` with ``riskClass: destructive``) — the same
path an imported contribution takes once a host routes it here.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.ai.tools import AITool, register_tool, reset_registry, run_tool
from app.ai.tools.base import ToolRiskClass, ToolScope
from app.core.errors import DomainError, ValidationError
from app.extensions.sdk import ChatToolContribution, connector_manifest
from app.models.enums import AITaskType, ProposalStatus
from app.models.profile_proposal_model import ProfileProposal
from app.models.user_model import User


class WipeIn(BaseModel):
    source_key: str


class StateChangingIn(BaseModel):
    note: str


EXECUTIONS: list[dict] = []


async def _wipe_handler(db, ctx, parsed) -> dict:
    EXECUTIONS.append({"user": str(ctx.user_id), "source": parsed.source_key})
    return {"wiped": parsed.source_key}


async def _note_handler(db, ctx, parsed) -> dict:
    return {"noted": parsed.note}


def destructive_tool(key: str = "wipe_source") -> Any:
    return AITool(
        key=key,
        title="Wipe source",
        description="Destructively wipe one job source and its postings.",
        input_model=WipeIn,
        handler=_wipe_handler,
        scope=ToolScope.WRITE,
        risk_class=ToolRiskClass.DESTRUCTIVE,
        requires_user=True,
    )


@pytest.fixture
async def user(client, db) -> User:
    email = f"funnel-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret1"},
    )
    assert response.status_code == 201, response.text
    rows = await db.execute(select(User).where(User.email == email))
    return rows.scalars().one()


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_registry()
    EXECUTIONS.clear()
    yield
    reset_registry()
    EXECUTIONS.clear()


@pytest.fixture
def destructive_registered():
    register_tool(destructive_tool())


@pytest.fixture
def _clean_connectors():
    """The bridge fixtures register test connectors — the connector
    registry resets after each so a drift fixture can't poison later
    registries (its manifest is invalid by construction)."""
    from app.extensions.registry import reset_registry as reset_connectors

    yield
    reset_connectors()


@pytest.fixture
def demo_connector(_clean_connectors):
    """A T1 bundled connector contributing the destructive chat tool —
    manifest declares it (the law), code implements it; the bridge
    registers both as one namespaced chat tool."""
    from app.extensions.registry import register_connector

    class WipeConnector:
        key = "demo_wipe"
        title = "Demo wipe"

        def config_model(self):
            class Config(BaseModel):
                pass

            return Config

        def manifest(self):
            return connector_manifest(
                manifest_id="career-demo-wipe",
                title="Demo wipe",
                config_schema={"type": "object", "properties": {}},
                capabilities=["chat-tools"],
                supports_incremental=False,
                description="test fixture",
                tools=[
                    {
                        "id": "purge-source",
                        "riskClass": "destructive",
                        "titleKey": "demo.purge.title",
                        "descriptionKey": "demo.purge.desc",
                    }
                ],
            )

        def chat_tools(self):
            return [
                ChatToolContribution(
                    id="purge-source",
                    title="Purge source",
                    description="Purge every posting of one source.",
                    risk_class="destructive",
                    input_model=WipeIn,
                    handler=_wipe_handler,
                )
            ]

    register_connector(WipeConnector())
    reset_registry()  # re-derive the tool registry over the new connector
    yield
    reset_registry()


# ------------------------------------------------- registration gate (D20)


def test_registration_rejects_risk_scope_mismatch():
    with pytest.raises(ValidationError, match="read-only class requires read scope"):
        register_tool(
            AITool(
                key="bad_readonly",
                title="t",
                description="d",
                input_model=WipeIn,
                handler=_wipe_handler,
                scope=ToolScope.WRITE,
                risk_class=ToolRiskClass.READ_ONLY,
            )
        )
    with pytest.raises(ValidationError, match="requires write scope"):
        register_tool(
            AITool(
                key="bad_destructive",
                title="t",
                description="d",
                input_model=WipeIn,
                handler=_wipe_handler,
                scope=ToolScope.READ,
                risk_class=ToolRiskClass.DESTRUCTIVE,
            )
        )


def test_list_tools_carries_risk_class():
    from app.ai.tools.registry import list_tools

    register_tool(destructive_tool("probe_risk"))
    rows = {r["key"]: r for r in list_tools()}
    assert rows["probe_risk"]["risk_class"] == "destructive"
    assert all("risk_class" in row for row in rows.values()), (
        "every chat tool carries its ADR-0011 class in the metadata"
    )


# --------------------------------------------- extension bridge (manifest law)


def test_extension_contribution_bridges_with_manifest_risk_class(demo_connector):
    from app.ai.tools.registry import get_tool, list_tools

    key = "career-demo-wipe:purge-source"
    tool = get_tool(key)
    assert tool.effective_risk_class is ToolRiskClass.DESTRUCTIVE
    listed = {r["key"]: r for r in list_tools()}
    assert listed[key]["risk_class"] == "destructive"
    assert listed[key]["builtin"] is False


def test_extension_bridge_throws_on_risk_class_drift(_clean_connectors):
    from app.extensions.registry import register_connector

    class DriftingConnector:
        key = "demo_drift"
        title = "Drift"

        def config_model(self):
            class Config(BaseModel):
                pass

            return Config

        def manifest(self):
            return connector_manifest(
                manifest_id="career-demo-drift",
                title="Drift",
                config_schema={"type": "object", "properties": {}},
                capabilities=["chat-tools"],
                supports_incremental=False,
                tools=[{"id": "purge-source", "riskClass": "read-only"}],
            )

        def chat_tools(self):
            return [
                ChatToolContribution(
                    id="purge-source",
                    title="Purge source",
                    description="d",
                    risk_class="destructive",
                    input_model=WipeIn,
                    handler=_wipe_handler,
                )
            ]

    register_connector(DriftingConnector())
    with pytest.raises(ValidationError, match="manifest is the law"):
        reset_registry()


def test_extension_bridge_throws_on_undeclared_contribution(_clean_connectors):
    from app.extensions.registry import register_connector

    class UndeclaredConnector:
        key = "demo_undecl"
        title = "Undeclared"

        def config_model(self):
            class Config(BaseModel):
                pass

            return Config

        def manifest(self):
            return connector_manifest(
                manifest_id="career-demo-undecl",
                title="Undecl",
                config_schema={"type": "object", "properties": {}},
                capabilities=["chat-tools"],
                supports_incremental=False,
                tools=[],
            )

        def chat_tools(self):
            return [
                ChatToolContribution(
                    id="ghost",
                    title="Ghost",
                    description="d",
                    risk_class="read-only",
                    input_model=WipeIn,
                    handler=_note_handler,
                )
            ]

    register_connector(UndeclaredConnector())
    with pytest.raises(ValidationError, match="not declared in the manifest"):
        reset_registry()


def test_bind_alias_round_trips(demo_connector):
    """The charter-namespaced key binds as an OpenAI-safe alias and the
    registry resolves it back (execute_tools passes model-echoed names)."""
    from app.ai.tools.langchain import tool_spec

    spec = tool_spec("career-demo-wipe:purge-source")
    assert spec is not None
    assert spec["function"]["name"] == "career-demo-wipe__purge-source"
    from app.ai.tools.registry import get_tool

    assert get_tool("career-demo-wipe__purge-source").key == ("career-demo-wipe:purge-source")


# ------------------------------------------------- the destructive funnel


async def test_direct_call_never_executes_emits_card(db, user, destructive_registered):
    result = await run_tool(db, "wipe_source", user.id, {"source_key": "rss"})
    assert EXECUTIONS == [], "a destructive call cannot execute directly"
    assert result["status"] == "awaiting_approval"
    proposal = (
        (await db.execute(select(ProfileProposal).where(ProfileProposal.kind == "tool_execution")))
        .scalars()
        .one()
    )
    assert proposal.status == "pending"
    assert proposal.payload_json["tool"] == "wipe_source"
    assert proposal.payload_json["args"] == {"source_key": "rss"}
    assert {row["field"] for row in proposal.diff_json} >= {"tool", "source_key"}


async def test_approve_executes_exactly_once(db, user, destructive_registered):
    result = await run_tool(db, "wipe_source", user.id, {"source_key": "rss"})
    from app.services.profile_proposal_service import ProfileProposalService

    service = ProfileProposalService(db)
    proposal = await service.get(user.id, uuid.UUID(result["proposal_id"]))
    _, applied, already = await service.approve(user.id, proposal.id)
    assert already is False
    assert applied["result"] == {"wiped": "rss"}
    assert len(EXECUTIONS) == 1, "the approved call executes exactly once"

    # Idempotent resolve: a second approve is a no-op, not a re-run.
    _, applied_again, already_again = await service.approve(user.id, proposal.id)
    assert already_again is True
    assert applied_again is None
    assert len(EXECUTIONS) == 1
    await db.refresh(proposal)
    assert proposal.status == "approved"


async def test_reject_never_executes(db, user, destructive_registered):
    result = await run_tool(db, "wipe_source", user.id, {"source_key": "rss"})
    from app.services.profile_proposal_service import ProfileProposalService

    service = ProfileProposalService(db)
    proposal = await service.get(user.id, uuid.UUID(result["proposal_id"]))
    await service.reject(user.id, proposal.id)
    assert EXECUTIONS == []
    await db.refresh(proposal)
    assert proposal.status == "rejected"

    # A rejected card can never be approved into execution.
    with pytest.raises(ValidationError, match="Cannot approve a rejected proposal"):
        await service.approve(user.id, proposal.id)
    assert EXECUTIONS == []


async def test_model_output_cannot_arm_execution(db, user, destructive_registered):
    """The ADR-0011 law: nothing in the model-facing result (or the args
    the model controls) can trigger the handler — every re-call emits
    another card at most."""
    result = await run_tool(db, "wipe_source", user.id, {"source_key": "rss"})
    assert set(result) == {"status", "proposal_id", "tool", "detail"}
    assert "result" not in result and "ok" not in result

    # Feed the awaiting-approval result BACK as tool args: still just a card.
    armed = await run_tool(
        db,
        "wipe_source",
        user.id,
        {"source_key": "rss", "confirmation": result},
    )
    assert armed["status"] == "awaiting_approval"
    assert len(EXECUTIONS) == 0
    cards = (
        (await db.execute(select(ProfileProposal).where(ProfileProposal.kind == "tool_execution")))
        .scalars()
        .all()
    )
    assert len(cards) == 2, "each destructive call confirms — none executed"


async def test_grants_cannot_bypass_destructive_confirm(db, user, destructive_registered):
    """The toggle law: even with a grant row forced into the store, the
    destructive tool still confirms; the grant endpoint itself refuses
    destructive keys."""
    from app.ai.tools.grants import grant, has_grant
    from app.models.tool_grant_model import UserToolGrant

    with pytest.raises(ValidationError, match="never grant-bypassable"):
        await grant(db, user.id, "wipe_source")

    db.add(UserToolGrant(user_id=user.id, tool_key="wipe_source"))
    await db.commit()
    assert await has_grant(db, user.id, "wipe_source")

    result = await run_tool(db, "wipe_source", user.id, {"source_key": "rss"})
    assert result["status"] == "awaiting_approval"
    assert EXECUTIONS == [], "grants never bypass the destructive confirm"


async def test_state_changing_requires_grant(db, user):
    register_tool(
        AITool(
            key="add_note",
            title="Add note",
            description="d",
            input_model=StateChangingIn,
            handler=_note_handler,
            scope=ToolScope.WRITE,
        )
    )
    with pytest.raises(DomainError, match="not enabled by this user"):
        await run_tool(db, "add_note", user.id, {"note": "x"})

    from app.ai.tools.grants import grant, revoke

    await grant(db, user.id, "add_note")
    result = await run_tool(db, "add_note", user.id, {"note": "x"})
    assert result == {"noted": "x"}

    await revoke(db, user.id, "add_note")
    with pytest.raises(DomainError, match="not enabled by this user"):
        await run_tool(db, "add_note", user.id, {"note": "y"})


async def test_proposal_and_execution_audit_rows(db, user, destructive_registered):
    result = await run_tool(db, "wipe_source", user.id, {"source_key": "rss"})
    from app.models.ai_model import AIGeneration
    from app.services.profile_proposal_service import ProfileProposalService

    service = ProfileProposalService(db)
    proposal = await service.get(user.id, uuid.UUID(result["proposal_id"]))
    # Proposal-side audit: the card row carries chat lineage + the notification
    # rode the funnel (assert the row shape here, notification in the API test).
    assert proposal.chat_session_id is None  # direct funnel call, no session
    assert proposal.resolve_error == ""

    await service.approve(user.id, proposal.id)
    rows = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == AITaskType.TOOL_RUN.value)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "one audit row for the one execution"
    audit = rows[0]
    assert audit.status == "ok"
    assert audit.prompt == "tool:wipe_source"
    assert audit.output["ok"] is True


async def test_card_flows_through_proposal_out_schema(db, user, destructive_registered):
    """The card renders through the ONE serializer (chat stream == list
    endpoint): destructive=true arms the confirm button client-side."""
    result = await run_tool(db, "wipe_source", user.id, {"source_key": "rss"})
    from app.services.profile_proposal_service import (
        ProfileProposalService,
        proposal_event,
    )

    proposal = await ProfileProposalService(db).get(user.id, uuid.UUID(result["proposal_id"]))
    event = proposal_event(proposal)
    assert event["kind"] == "tool_execution"
    assert event["destructive"] is True
    assert event["title"].startswith("Run destructive tool")
    assert event["status"] == ProposalStatus.PENDING.value
