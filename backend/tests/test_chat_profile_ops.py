"""Chat profile ops (plan 77.2): digest grounding, proposal SSE events,
metadata persistence, caps, session-delete durability, end-to-end HITL."""

import json
import uuid

import pytest
from sqlalchemy import select

from app.ai.agents.chatbot import _mock_chat_reply
from app.ai import gateway as gateway_module
from app.models.enums import AITaskType
from app.models.experience_model import ExperienceItem
from app.models.profile_proposal_model import ProfileProposal
from app.models.user_model import User
from app.services.experience_service import ExperienceService

from tests.test_chat_streaming import _parse_sse


async def _auth_user(db) -> User:
    from app.core.config import settings

    rows = await db.execute(
        select(User).where(User.email == settings.DEFAULT_USER_EMAIL)
    )
    return rows.scalars().one()


async def _session(client, headers) -> dict:
    return (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "profile-ops"}, headers=headers
        )
    ).json()


async def _send(client, session_id, headers, message: str):
    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": message},
        params={"stream": "true"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return _parse_sse(response.text)


async def test_digest_tools_return_ids(db, auth_headers):
    user = await _auth_user(db)
    item = await ExperienceService(db).create_item(
        user.id,
        {
            "title": "Crew chatbot",
            "kind": "project",
            "org_name": "",
            "open_ended": True,
        },
    )
    from app.ai.tools import run_tool

    digest = await run_tool(db, "my_experience", user.id, {})
    assert digest["items"][0]["id"] == str(item.id)
    assert digest["items"][0]["title"] == "Crew chatbot"
    assert "ids are required verbatim" in digest["note"]

    skills = await run_tool(db, "my_skills", user.id, {})
    assert "row_id" in (skills.get("skills") or [{}])[0] or skills["skills"] == []

    profile = await run_tool(db, "my_profile_digest", user.id, {})
    assert set(profile["counts"]) == {
        "experience",
        "skills",
        "education",
        "certifications",
        "achievements",
    }


async def test_turn_emits_proposal_events_and_persists(
    client, db, auth_headers, monkeypatch
):
    user = await _auth_user(db)
    session = await _session(client, auth_headers)

    events = await _send(
        client, session["id"], auth_headers, "Add a project where I built a chatbot"
    )
    names = [name for name, _ in events]
    assert names[-1] == "done"

    proposals = [payload for name, payload in events if name == "proposal"]
    assert len(proposals) == 1
    card = proposals[0]
    assert card["kind"] == "experience_item"
    assert card["action"] == "create"
    assert card["status"] == "pending"
    assert card["destructive"] is False
    assert card["title"].startswith("Add experience")
    assert any(row["field"] == "title" for row in card["diff"])

    flow = next(p for n, p in events if n == "flow_finished")
    assert flow["proposal_count"] == 1
    meta = next(p for n, p in events if n == "meta")
    assert meta["proposals_dropped"] is None

    rows = (
        (
            await db.execute(
                select(ProfileProposal).where(ProfileProposal.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    proposal = rows[0]
    assert proposal.status == "pending"
    assert proposal.chat_session_id == uuid.UUID(session["id"])
    assert proposal.chat_message_id is not None

    messages = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    stored = messages[-1]["metadata_json"]["proposals"]
    assert stored[0]["id"] == card["id"]


async def test_approve_after_chat_turn_applies(client, db, auth_headers):
    user = await _auth_user(db)
    session = await _session(client, auth_headers)
    events = await _send(
        client, session["id"], auth_headers, "Add a project where I built a chatbot"
    )
    card = next(p for n, p in events if n == "proposal")

    approved = await client.post(
        f"/api/v1/me/profile-proposals/{card['id']}/approve", headers=auth_headers
    )
    assert approved.status_code == 200, approved.text
    items = (
        (
            await db.execute(
                select(ExperienceItem).where(ExperienceItem.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert [i.title for i in items] == ["New project"]


async def test_question_turn_creates_no_proposals(client, db, auth_headers):
    user = await _auth_user(db)
    session = await _session(client, auth_headers)
    events = await _send(
        client, session["id"], auth_headers, "What do you think about my experience?"
    )
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


async def test_ops_cap_drops_overflow_with_note(client, db, auth_headers, monkeypatch):
    user = await _auth_user(db)
    session = await _session(client, auth_headers)

    def many_ops(schema, user_prompt: str) -> dict:
        ctx = json.loads(user_prompt.split("CONTEXT_JSON: ", 1)[1])
        if "my_experience" not in ctx.get("tool_results", {}):
            return {"answer": "plain"}
        return {
            "answer": "seven changes proposed",
            "profile_ops": [
                {
                    "kind": "experience_item",
                    "action": "create",
                    "payload": {
                        "title": f"P{i}",
                        "kind": "project",
                        "open_ended": True,
                    },
                }
                for i in range(7)
            ],
        }

    gateway_module.register_mock_fixture(AITaskType.CHAT, many_ops)
    try:
        events = await _send(
            client, session["id"], auth_headers, "add experience items now"
        )
    finally:
        gateway_module.register_mock_fixture(AITaskType.CHAT, _mock_chat_reply)

    proposals = [p for n, p in events if n == "proposal"]
    assert len(proposals) == 5
    meta = next(p for n, p in events if n == "meta")
    assert meta["proposals_dropped"] == 2
    rows = (
        (
            await db.execute(
                select(ProfileProposal).where(ProfileProposal.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 5
    messages = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    assert messages[-1]["metadata_json"]["proposals_dropped"] == 2


async def test_session_delete_keeps_pending_proposals(client, db, auth_headers):
    session = await _session(client, auth_headers)
    events = await _send(
        client, session["id"], auth_headers, "Add a project where I built a chatbot"
    )
    card = next(p for n, p in events if n == "proposal")

    deleted = await client.delete(
        f"/api/v1/chat/sessions/{session['id']}", headers=auth_headers
    )
    assert deleted.status_code == 204

    proposal = (
        (
            await db.execute(
                select(ProfileProposal).where(
                    ProfileProposal.id == uuid.UUID(card["id"])
                )
            )
        )
        .scalars()
        .one()
    )
    assert proposal.status == "pending"
    assert proposal.chat_session_id is None
    assert proposal.chat_message_id is None

    listing = await client.get(
        "/api/v1/me/profile-proposals?status=pending", headers=auth_headers
    )
    assert card["id"] in [p["id"] for p in listing.json()["proposals"]]


async def test_mock_update_end_date_flow(client, db, auth_headers):
    user = await _auth_user(db)
    item = await ExperienceService(db).create_item(
        user.id,
        {
            "title": "Siemens internship",
            "kind": "internship",
            "org_name": "Siemens",
            "start": "2025-09-01",
            "open_ended": True,
        },
    )
    session = await _session(client, auth_headers)
    events = await _send(
        client, session["id"], auth_headers, "I finished my internship last month"
    )
    card = next(p for n, p in events if n == "proposal")
    assert card["kind"] == "experience_item"
    assert card["action"] == "update"
    assert card["entity_id"] == str(item.id)

    approved = await client.post(
        f"/api/v1/me/profile-proposals/{card['id']}/approve", headers=auth_headers
    )
    assert approved.status_code == 200
    await db.refresh(item)
    assert str(item.end) == "2026-06-30"
    assert item.open_ended is False


async def test_mock_fixture_no_ops_without_digest(db, auth_headers):
    ops = _mock_profile_ops_guarded()
    assert ops == []


def _mock_profile_ops_guarded():
    from app.ai.agents.chatbot import _mock_profile_ops

    return _mock_profile_ops({}, "please add a project about ML")


def test_profile_op_schema_caps():
    from app.ai.schemas import ChatReply, ProfileOp

    reply = ChatReply.model_validate(
        {
            "answer": "ok",
            "profile_ops": [
                {
                    "kind": "user_skill",
                    "action": "create",
                    "payload": {"skill_key": "sql", "level": 3},
                }
            ]
            * 8,
        }
    )
    assert len(reply.profile_ops) == 8
    with pytest.raises(Exception):
        ChatReply.model_validate(
            {
                "answer": "ok",
                "profile_ops": [
                    {"kind": "user_skill", "action": "create", "payload": {}}
                ]
                * 9,
            }
        )
    op = ProfileOp.model_validate(
        {
            "kind": "profile_section",
            "action": "update",
            "payload": {"section": "academics"},
        }
    )
    assert op.entity_id is None
