"""Plan 99.1 — read-before-edit grounding: read tools, the gate, and
the session read cache."""

import json
import uuid

import pytest

from sqlalchemy import select

from app.ai import gateway as gateway_module
from app.ai.mock_chat import mock_chat_reply, mock_read_calls, mock_profile_ops
from app.ai.tools import run_tool
from app.core.errors import DomainError
from app.models.enums import AITaskType
from app.models.chat_model import ChatSession
from app.models.experience_model import ExperienceItem
from app.models.profile_proposal_model import ProfileProposal
from app.services.chat_digest_cache import (
    context_without_cache,
    entity_signature,
    fresh_entry,
    grounded_read_keys,
    load_reads,
    read_cache_key,
    save,
)
from app.services.experience_service import ExperienceService
from app.services.profile_proposal_service import ProfileProposalService

from tests.test_chat_profile_ops import _auth_user, _send, _session

LONG_DESCRIPTION = (
    "Worked as Application Support for ICT projects and later transitioned "
    "to the Provisioning Department. Ensured availability, performance and "
    "maintenance for enterprise applications. Managed monitoring, alerting "
    "and incident response across the whole landscape."
)


async def _rich_item(db, user) -> ExperienceItem:
    return await ExperienceService(db).create_item(
        user.id,
        {
            "title": "Application Support",
            "kind": "job",
            "org_name": "OTE Group",
            "start": "2024-01-01",
            "open_ended": True,
            "description": LONG_DESCRIPTION,
            "skills": [
                {"skill_key": "electron", "role_in_item": "primary"},
                {"skill_key": "typescript", "role_in_item": "secondary"},
            ],
            "achievements": [
                {
                    "text": "Cut deploy time 40%",
                    "metric": {"kind": "time_saved", "value": 40, "unit": "%"},
                }
            ],
            "links": ["https://github.com/example/support"],
        },
    )


async def test_read_profile_item_returns_full_content(db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)

    result = await run_tool(
        db,
        "read_profile_item",
        user.id,
        {"kind": "experience_item", "entity_id": str(item.id)},
    )
    assert "error" not in result
    assert result["kind"] == "experience_item"
    assert result["entity_id"] == str(item.id)
    content = result["content"]
    assert content["description"] == LONG_DESCRIPTION
    assert len(content["description"]) > 140, "no digest truncation"
    assert content["org_name"] == "OTE Group"
    assert [s["skill_key"] for s in content["skills"]] == [
        "electron",
        "typescript",
    ]
    assert content["skills"][0]["role_in_item"] == "primary"
    assert content["achievements"][0]["text"] == "Cut deploy time 40%"
    assert content["achievements"][0]["metric"]["value"] == 40
    assert content["links"] and "github.com" in json.dumps(content["links"])
    assert result["updated_at"]


async def test_read_profile_item_rejects_bad_targets(db, auth_headers):
    user = await _auth_user(db)
    invalid = await run_tool(
        db,
        "read_profile_item",
        user.id,
        {"kind": "experience_item", "entity_id": "not-a-uuid"},
    )
    assert "error" in invalid
    with pytest.raises(DomainError, match="read_profile_item"):
        await run_tool(
            db,
            "read_profile_item",
            user.id,
            {"kind": "user_skill", "entity_id": str(uuid.uuid4())},
        )
    missing = await run_tool(
        db,
        "read_profile_item",
        user.id,
        {"kind": "experience_item", "entity_id": str(uuid.uuid4())},
    )
    assert "error" in missing


async def test_read_profile_section_returns_full_json(db, auth_headers):
    from app.services.profile_service import ProfileService

    user = await _auth_user(db)
    profile = await ProfileService(db).get(user.id)
    profile.academics = {
        "languages": [{"code": "en", "level": "native"}],
        "university_id": None,
        "department_id": None,
    }
    db.add(profile)
    await db.commit()

    result = await run_tool(
        db, "read_profile_section", user.id, {"section": "academics"}
    )
    assert result["section"] == "academics"
    assert result["content"]["languages"] == [{"code": "en", "level": "native"}]
    with pytest.raises(DomainError, match="read_profile_section"):
        await run_tool(db, "read_profile_section", user.id, {"section": "interests"})


async def test_gate_drops_unread_update_and_allows_read(db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    service = ProfileProposalService(db)
    op = {
        "kind": "experience_item",
        "action": "update",
        "entity_id": str(item.id),
        "payload": {"description": "Rewritten without reading."},
    }

    created, dropped = await service.create_from_ops(user.id, [op], grounding=set())
    assert created == []
    assert len(dropped) == 1
    assert dropped[0]["reason"].startswith("unread_target")

    grounded, dropped2 = await service.create_from_ops(
        user.id, [op], grounding={read_cache_key("experience_item", item.id)}
    )
    assert dropped2 == []
    assert grounded[0].kind == "experience_item"


async def test_gate_exempts_creates_and_cv_synth(db, auth_headers):
    user = await _auth_user(db)
    ops = [
        {
            "kind": "experience_item",
            "action": "create",
            "payload": {"title": "Fresh", "kind": "project", "open_ended": True},
        },
        {
            "kind": "cv_synth",
            "action": "create",
            "payload": {
                "refs": [{"source_key": "projects", "item_id": "item-1"}],
                "action": "summarize",
            },
        },
    ]
    created, dropped = await ProfileProposalService(db).create_from_ops(
        user.id, ops, grounding=set()
    )
    assert dropped == []
    assert {p.kind for p in created} == {"experience_item", "cv_synth"}


async def test_gate_requires_section_read(db, auth_headers):
    user = await _auth_user(db)
    op = {
        "kind": "profile_section",
        "action": "update",
        "payload": {"section": "academics", "value": {"languages": []}},
    }
    created, dropped = await ProfileProposalService(db).create_from_ops(
        user.id, [op], grounding=set()
    )
    assert created == []
    assert dropped[0]["reason"].startswith("unread_target")

    grounded, dropped2 = await ProfileProposalService(db).create_from_ops(
        user.id, [op], grounding={"read:profile_section:academics"}
    )
    assert dropped2 == []
    assert grounded[0].kind == "profile_section"


async def test_cached_read_gates_only_while_fresh(db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    key = read_cache_key("experience_item", item.id)

    assert await grounded_read_keys(db, None, []) == set()

    session_row = ChatSession(user_id=user.id, title="reads", context={})
    db.add(session_row)
    await db.commit()
    sig = await entity_signature(db, "experience_item", item.id)
    assert sig
    assert save(session_row, {key: fresh_entry({"kind": "experience_item"}, sig)})
    grounded = await grounded_read_keys(db, session_row, [])
    assert key in grounded

    await ExperienceService(db).update_item(
        user.id, item.id, {"description": "changed"}
    )
    grounded_stale = await grounded_read_keys(db, session_row, [])
    assert key not in grounded_stale
    assert load_reads(session_row).get(key)


async def test_context_without_cache_strips_read_entries():
    context = {
        "page": "profile",
        "profile_digests": {
            "read:experience_item:" + str(uuid.uuid4()): {"sig": "x"},
            "my_experience": {"sig": "y"},
        },
    }
    assert context_without_cache(context) == {"page": "profile"}
    assert context_without_cache({"page": "x"}) == {"page": "x"}


def test_mock_reads_mirror_the_ops():
    items = [{"id": "item-1", "kind": "project", "title": "Crew"}]
    tools = {"my_experience": {"items": items}}
    message = "delete the project"
    assert mock_profile_ops(tools, message) == [], "unread target: no ops"
    assert mock_read_calls(tools, message) == [
        {
            "name": "read_profile_item",
            "args": {"kind": "experience_item", "entity_id": "item-1"},
        }
    ]
    read_tools = {
        **tools,
        "read_profile_item": [
            {"kind": "experience_item", "entity_id": "item-1", "content": {}}
        ],
    }
    ops = mock_profile_ops(read_tools, message)
    assert ops and ops[0]["action"] == "delete"
    assert mock_read_calls(read_tools, message) == [], "already read"


def test_mock_section_read_mirrors_language_ops():
    digest = {
        "full_name": "Ann",
        "languages": [{"code": "en", "level": "native"}],
        "counts": {},
        "sections": [],
    }
    tools = {"my_profile_digest": digest}
    message = "set german to native"
    assert mock_profile_ops(tools, message) == [], "unread section: no ops"
    assert mock_read_calls(tools, message) == [
        {"name": "read_profile_section", "args": {"section": "academics"}}
    ]


async def test_turn_without_read_drops_update_op(client, db, auth_headers):
    """An agent that never opens the item: the update op is dropped with
    a visible unread_target reason — no card, no silent overwrite."""
    user = await _auth_user(db)
    item = await _rich_item(db, user)

    def digest_only(user_text, tool_names):
        import re as _re

        match = _re.search(r"CONTEXT_JSON: (\{.*\})", user_text, _re.S)
        ctx = json.loads(match.group(1)) if match else {}
        if "my_experience" in (ctx.get("tool_results") or {}):
            return {"content": "", "tool_calls": []}
        return {
            "content": "",
            "tool_calls": [{"name": "my_experience", "args": {}, "id": "call-0"}],
        }

    def unread_update(schema, user_prompt):
        ctx = json.loads(user_prompt.split("CONTEXT_JSON: ", 1)[1])
        items = (ctx["tool_results"].get("my_experience") or {}).get("items") or []
        if not items:
            return {"answer": "plain"}
        return {
            "answer": "proposing an unread edit",
            "profile_ops": [
                {
                    "kind": "experience_item",
                    "action": "update",
                    "entity_id": items[0]["id"],
                    "payload": {"description": "Overwrite attempt."},
                }
            ],
        }

    session = await _session(client, auth_headers)
    gateway_module.register_agent_mock(AITaskType.CHAT.value, digest_only)
    gateway_module.register_mock_fixture(AITaskType.CHAT, unread_update)
    try:
        events = await _send(client, session["id"], auth_headers, "update my item: now")
    finally:
        gateway_module.AGENT_MOCK_SCRIPTS.pop(AITaskType.CHAT.value, None)
        gateway_module.register_mock_fixture(AITaskType.CHAT, mock_chat_reply)

    assert not [p for n, p in events if n == "proposal"]
    rows = (
        (
            await db.execute(
                select(ProfileProposal).where(ProfileProposal.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []
    meta = next(p for n, p in events if n == "meta")
    assert meta["proposals_dropped"] == 1
    assert "unread_target" in json.dumps(meta.get("proposals_dropped_reasons"))
    await db.refresh(item)
    assert item.description == LONG_DESCRIPTION
