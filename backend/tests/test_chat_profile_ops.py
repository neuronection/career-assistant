"""Chat profile ops (plan 77.2): digest grounding, proposal SSE events,
metadata persistence, caps, session-delete durability, end-to-end HITL."""

import json
import uuid

import pytest
from sqlalchemy import select

from app.ai.mock_chat import mock_chat_reply as _mock_chat_reply
from app.ai import gateway as gateway_module
from app.models.enums import AITaskType
from app.models.chat_model import ChatSession
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


async def test_generic_edit_words_still_ground_the_digest(client, db, auth_headers):
    """'create new items and update existing too' names no entity kind —
    the digests still run so update ops get verbatim ids (create ops
    never needed them)."""
    user = await _auth_user(db)
    await ExperienceService(db).create_item(
        user.id,
        {"title": "AI Launcher", "kind": "project", "open_ended": True},
    )
    session = await _session(client, auth_headers)
    events = await _send(
        client, session["id"], auth_headers, "create new items and update existing too"
    )
    names = [p["name"] for n, p in events if n == "tool_call"]
    assert "my_experience" in names
    assert "my_profile_digest" in names


async def test_cache_primes_and_followup_without_keywords(
    client, db, auth_headers, monkeypatch
):
    """Plan 81 core flow: turn 1 (keyword) primes the session cache; turn 2
    names NO entity keyword at all yet still grounds proposals, reusing
    the cached digest ids."""

    def edit_ops(schema, user_prompt: str) -> dict:
        ctx = json.loads(user_prompt.split("CONTEXT_JSON: ", 1)[1])
        tools = ctx.get("tool_results", {})
        # The cached digest must never leak into the model's page context.
        assert "profile_digests" not in (ctx.get("page_context") or {})
        items = (tools.get("my_experience") or {}).get("items") or []
        if not (tools.get("my_experience") or {}).get("_cached"):
            return {"answer": f"items_count_{len(items)}"}
        return {
            "answer": f"items_count_{len(items)}",
            "profile_ops": [
                {
                    "kind": "experience_item",
                    "action": "delete",
                    "entity_id": items[0]["id"],
                }
            ],
        }

    user = await _auth_user(db)
    item = await ExperienceService(db).create_item(
        user.id, {"title": "AI Launcher", "kind": "project", "open_ended": True}
    )
    session = await _session(client, auth_headers)

    # Session API responses never expose the internal cache (it is only
    # written server-side). Empty sessions are invisible in the list
    # (plan 93) — this session has no messages yet.
    listing = await client.get("/api/v1/chat/sessions", headers=auth_headers)
    assert listing.json() == []

    gateway_module.register_mock_fixture(AITaskType.CHAT, edit_ops)
    try:
        # Turn 1: keyword message ("project") — primes the cache.
        fresh_events = await _send(
            client, session["id"], auth_headers, "tell me about my projects"
        )
        fresh_names = [p["name"] for n, p in fresh_events if n == "tool_call"]
        assert "my_experience" in fresh_names

        # Turn 2: zero keyword matches — cache reuse grounds the op.
        events = await _send(
            client, session["id"], auth_headers, "apply the change to my first row"
        )
    finally:
        gateway_module.register_mock_fixture(AITaskType.CHAT, _mock_chat_reply)

    tool_names = [p["name"] for n, p in events if n == "tool_call"]
    assert "my_experience" not in tool_names  # cached, not re-run
    cards = [p for n, p in events if n == "proposal"]
    assert len(cards) == 1, events
    assert cards[0]["entity_id"] == str(item.id)
    assert "items_count_1" in json.dumps(events, default=str)

    rows = (
        (
            await db.execute(
                select(ChatSession).where(ChatSession.id == uuid.UUID(session["id"]))
            )
        )
        .scalars()
        .one()
    )
    cached = rows.context["profile_digests"]
    assert "my_experience" in cached
    assert cached["my_experience"]["sig"]


async def test_approved_card_staleness_refreshes_cache(
    client, db, auth_headers, monkeypatch
):
    """Approving a card changes the data → the next turn's signature
    mismatch forces a fresh digest; the model sees the NEW item."""

    def count_ops(schema, user_prompt: str) -> dict:
        ctx = json.loads(user_prompt.split("CONTEXT_JSON: ", 1)[1])
        tools = ctx.get("tool_results", {})
        query = (ctx.get("message") or "").strip().split(":", 1)[-1].strip()
        if query == "state1":
            items = (tools.get("my_experience") or {}).get("items") or []
            op = {
                "kind": "experience_item",
                "action": "delete",
                "entity_id": items[0]["id"],
            }
            return {"answer": "state1", "profile_ops": [op]}
        return {"answer": query}

    def refresh_probe(schema, user_prompt: str) -> dict:
        ctx = json.loads(user_prompt.split("CONTEXT_JSON: ", 1)[1])
        items = (ctx["tool_results"]["my_experience"] or {}).get("items") or []
        return {"answer": ctx["message"].strip()[:4] + ":" + str(len(items))}

    user = await _auth_user(db)
    await ExperienceService(db).create_item(
        user.id, {"title": "AI Launcher", "kind": "project", "open_ended": True}
    )
    await ExperienceService(db).create_item(
        user.id, {"title": "Neuronection", "kind": "project", "open_ended": True}
    )
    session = await _session(client, auth_headers)

    gateway_module.register_mock_fixture(AITaskType.CHAT, count_ops)
    try:
        events = await _send(
            client, session["id"], auth_headers, "delete the project: state1"
        )
        card = next(p for n, p in events if n == "proposal")
    finally:
        gateway_module.register_mock_fixture(AITaskType.CHAT, _mock_chat_reply)
    approve = await client.post(
        f"/api/v1/me/profile-proposals/{card['id']}/approve", headers=auth_headers
    )
    assert approve.status_code == 200, approve.text

    # Next turn: message has no keywords ("echo turn"), so grounding can
    # only come from the cache — and it must have refreshed past the
    # approved deletion (2 items before, 1 after) or the probe fails.
    gateway_module.register_mock_fixture(AITaskType.CHAT, refresh_probe)
    try:
        probe = await _send(client, session["id"], auth_headers, "echo turn2: turn2")
    finally:
        gateway_module.register_mock_fixture(AITaskType.CHAT, _mock_chat_reply)
    reply = next(p for n, p in probe if n == "delta")
    assert reply["text"].endswith(":1"), probe
    meta = next(p for n, p in probe if n == "meta")
    turned_cached = meta.get("proposals_dropped") is None
    assert turned_cached


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
    client, db, auth_headers, kinds, monkeypatch
):
    user = await _auth_user(db)
    session = await _session(client, auth_headers)

    events = await _send(
        client, session["id"], auth_headers, "Add a project where I built a chatbot"
    )
    names = [name for name, _ in events]
    assert names[-1] == "flow_finished"

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

    # ADR-0015 fanout: the turn also notifies (survives a closed chat).
    from app.models.engagement_model import Notification, NotificationRecipient

    notification = (
        (
            await db.execute(
                select(Notification)
                .join(
                    NotificationRecipient,
                    NotificationRecipient.notification_id == Notification.id,
                )
                .where(NotificationRecipient.user_id == user.id)
            )
        )
        .scalars()
        .first()
    )
    assert notification is not None
    assert notification.payload["link"] == "/profile"
    assert notification.payload["proposal_ids"] == [card["id"]]


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


async def test_model_secondary_ops_period_normalized(
    client, db, auth_headers, monkeypatch
):
    """Real providers often emit create ops without dates — the service
    normalizes them to open_ended instead of dropping every card (the
    prompt teaches the rule; this is the trust-boundary backstop)."""
    user = await _auth_user(db)
    session = await _session(client, auth_headers)

    def undated_ops(schema, user_prompt: str) -> dict:
        ctx = json.loads(user_prompt.split("CONTEXT_JSON: ", 1)[1])
        if "my_experience" not in ctx.get("tool_results", {}):
            return {"answer": "plain"}
        return {
            "answer": "four projects proposed",
            "profile_ops": [
                {
                    "kind": "experience_item",
                    "action": "create",
                    "payload": {"title": f"Project {i}", "kind": "project"},
                }
                for i in range(4)
            ],
        }

    gateway_module.register_mock_fixture(AITaskType.CHAT, undated_ops)
    try:
        events = await _send(client, session["id"], auth_headers, "create 4 projects")
    finally:
        gateway_module.register_mock_fixture(AITaskType.CHAT, _mock_chat_reply)

    proposals = [p for n, p in events if n == "proposal"]
    assert len(proposals) == 4
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
    assert len(rows) == 4


async def test_loose_skill_shapes_still_grade_a_card(
    client, db, auth_headers, monkeypatch
):
    """Real providers emit skills as label strings / name dicts (the
    logged failure behind 'the data didn't validate') — normalization
    must produce a card, and a create needs no dates either."""

    def loose_ops(schema, user_prompt: str) -> dict:
        ctx = json.loads(user_prompt.split("CONTEXT_JSON: ", 1)[1])
        tools = ctx.get("tool_results", {})
        if "my_experience" not in tools:
            return {"answer": "plain"}
        ops: list[dict] = [
            {
                "kind": "experience_item",
                "action": "create",
                "payload": {
                    "title": "Neuronection",
                    "description": "Founded the ecosystem.",
                    "skills": ["electron", {"name": "Model Context Protocol"}],
                    "achievements": ["Four family assistants"],
                    "links": ["https://neuronection.com"],
                },
            }
        ]
        items = (tools.get("my_experience") or {}).get("items") or []
        if items:
            ops.append(
                {
                    "kind": "experience_item",
                    "action": "update",
                    "entity_id": items[0]["id"],
                    "payload": {
                        "title": f"{items[0]['title']} → Desktop Assistant",
                        "skills": ["electron", "typescript"],
                    },
                }
            )
        return {"answer": "loose shapes", "profile_ops": ops}

    user = await _auth_user(db)
    item = await ExperienceService(db).create_item(
        user.id, {"title": "AI Launcher", "kind": "project", "open_ended": True}
    )
    session = await _session(client, auth_headers)

    gateway_module.register_mock_fixture(AITaskType.CHAT, loose_ops)
    try:
        events = await _send(
            client, session["id"], auth_headers, "add and refresh my projects"
        )
    finally:
        gateway_module.register_mock_fixture(AITaskType.CHAT, _mock_chat_reply)

    meta = next(p for n, p in events if n == "meta")
    assert meta.get("proposals_dropped") is None
    cards = [p for n, p in events if n == "proposal"]
    assert len(cards) == 2
    update_card = next(c for c in cards if c["action"] == "update")
    assert update_card["entity_id"] == str(item.id)

    # Collection fields render as scalar lists (chips in the UI), never
    # raw payload dicts.
    create_card = next(c for c in cards if c["action"] == "create")
    diff = {row["field"]: row for row in create_card["diff"]}
    assert diff["skills"]["after"] == ["electron", "Model Context Protocol"]
    assert diff["links"]["after"] == ["https://neuronection.com"]
    assert diff["achievements"]["after"] == ["Four family assistants"]
    update_diff = {row["field"]: row for row in update_card["diff"]}
    assert update_diff["skills"]["after"] == ["electron", "typescript"]


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
    from app.ai.mock_chat import mock_profile_ops as _mock_profile_ops

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


async def test_chat_cv_synth_op_flows_to_library(client, db, auth_headers):
    """Plan 82A: a variant ask proposes ONE cv_synth card; approving it
    drafts review-only rows in the Synth Library."""
    from app.models.cv_synth_model import CvSynthItem

    user = await _auth_user(db)
    await ExperienceService(db).create_item(
        user.id, {"title": "Neuronection", "kind": "project", "open_ended": True}
    )
    session = await _session(client, auth_headers)
    events = await _send(
        client, session["id"], auth_headers, "generate variants for my projects"
    )
    cards = [p for n, p in events if n == "proposal"]
    assert len(cards) == 1
    assert cards[0]["kind"] == "cv_synth"
    assert cards[0]["title"].startswith("Add CV variants")
    fields = {row["field"]: row for row in cards[0]["diff"]}
    assert fields["action"]["after"] == "summarize"
    assert len(fields["refs"]["after"]) == 1

    response = await client.post(
        f"/api/v1/me/profile-proposals/{cards[0]['id']}/approve",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"]["queued"] is False
    assert len(body["applied"]["items"]) >= 1

    rows = (
        (await db.execute(select(CvSynthItem).where(CvSynthItem.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) >= 1
    assert all(row.status == "active" for row in rows)
