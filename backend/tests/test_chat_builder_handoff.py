"""Builder on-demand handoff (plan 78.2): attachment + build intent runs
the copilot loop for that turn in a NORMAL session; question intent
stays a CHAT turn; legacy bound sessions keep routing."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.chat_model import ChatMessage
from app.models.user_model import User
from app.schemas.cv import CvDocumentCreate
from app.services.cv_service import CvService
from app.seeds.cv_templates import seed_cv_template_bank

from tests.test_chat_streaming import _parse_sse


@pytest.fixture
async def builder_env(db, monkeypatch):
    """Copilot turns need the template bank + an unavailable PDF engine
    (the visual review degrades honestly instead of crashing)."""
    from tests.test_cv_assistant import _raise_engine_unavailable

    monkeypatch.setattr(
        "app.ai.agents.cv_builder_chat.measure_pages",
        _raise_engine_unavailable,
    )
    await seed_cv_template_bank(db)
    return db


async def _auth_user(db) -> User:
    rows = await db.execute(
        select(User).where(User.email == settings.DEFAULT_USER_EMAIL)
    )
    return rows.scalars().one()


async def _cv(db, user, title="Handoff CV"):
    return await CvService(db).create(user.id, CvDocumentCreate(title=title))


async def _session(client, headers, title="handoff"):
    return (
        await client.post(
            "/api/v1/chat/sessions", json={"title": title}, headers=headers
        )
    ).json()


async def _send(client, session_id, headers, message, attachments=None):
    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": message, "attachments": attachments or []},
        params={"stream": "true"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return _parse_sse(response.text)


def _messages(db_rows):
    return sorted(db_rows, key=lambda m: m.created_at)


async def test_build_intent_hands_off_to_builder(client, db, auth_headers, builder_env):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    session = await _session(client, auth_headers)

    events = await _send(
        client,
        session["id"],
        auth_headers,
        "please rewrite the summary section",
        attachments=[{"kind": "cv", "cv_id": str(cv.id)}],
    )
    names = [name for name, _ in events]
    print("DEBUG EVENTS:", names)
    assert "builder_state" in names, "the turn ran the copilot loop"
    assert names[-1] == "flow_finished"

    rows = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session["id"]))
    )
    messages = _messages(rows.scalars().all())
    assistant = messages[-1]
    assert assistant.role == "assistant"
    assert assistant.metadata_json["surface"] == "cv_builder"
    # The session itself stayed a normal chat session (no context binding).
    sessions = (await client.get("/api/v1/chat/sessions", headers=auth_headers)).json()
    entry = next(s for s in sessions if s["id"] == session["id"])
    assert entry["context"] is None


async def test_question_intent_stays_normal_chat(client, db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    session = await _session(client, auth_headers)

    events = await _send(
        client,
        session["id"],
        auth_headers,
        "which jobs fit this cv?",
        attachments=[{"kind": "cv", "cv_id": str(cv.id)}],
    )
    names = [name for name, _ in events]
    assert "builder_state" not in names
    assert "delta" in names

    rows = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session["id"]))
    )
    assistant = _messages(rows.scalars().all())[-1]
    assert assistant.metadata_json.get("surface") != "cv_builder"
    assert assistant.metadata_json["referenced_cv_ids"] == [str(cv.id)]


async def test_earlier_reference_also_hands_off(client, db, auth_headers, builder_env):
    """Follow-up 'polish it' with the inherited reference hands off too."""
    user = await _auth_user(db)
    cv = await _cv(db, user)
    session = await _session(client, auth_headers)

    await _send(
        client,
        session["id"],
        auth_headers,
        "review this cv",
        attachments=[{"kind": "cv", "cv_id": str(cv.id)}],
    )
    events = await _send(
        client,
        session["id"],
        auth_headers,
        "good, now polish the wording",
    )
    assert "builder_state" in [name for name, _ in events]


async def test_build_intent_without_attachment_stays_chat(client, db, auth_headers):
    session = await _session(client, auth_headers)
    events = await _send(
        client,
        session["id"],
        auth_headers,
        "rewrite my cover letter approach",
    )
    assert "builder_state" not in [name for name, _ in events]


async def test_legacy_bound_session_still_routes(client, db, auth_headers, builder_env):
    """AD1 compat: existing cv_builder-bound sessions keep the copilot."""
    user = await _auth_user(db)
    cv = await _cv(db, user)
    session = (
        await client.post(
            "/api/v1/chat/sessions",
            json={
                "title": "legacy bound",
                "context": {"surface": "cv_builder", "cv_id": str(cv.id)},
            },
            headers=auth_headers,
        )
    ).json()

    events = await _send(client, session["id"], auth_headers, "rewrite the summary")
    assert "builder_state" in [name for name, _ in events]


async def test_sync_path_hands_off_too(client, db, auth_headers, builder_env):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    session = await _session(client, auth_headers)

    response = await client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        json={
            "content": "rewrite the summary",
            "attachments": [{"kind": "cv", "cv_id": str(cv.id)}],
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    rows = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session["id"]))
    )
    assistant = _messages(rows.scalars().all())[-1]
    assert assistant.metadata_json["surface"] == "cv_builder"


async def test_preview_intent_persists_and_emits(
    client, db, auth_headers, builder_env, monkeypatch
):
    """Plan 83C/D: a template-look turn renders previews, emits `preview`
    events + a trace card, and persists template_previews metadata."""
    from app.ai.gateway import register_mock_fixture
    from app.ai.agents.cv_builder_chat import _mock_builder_turn
    from app.models.enums import AITaskType
    from app.services.cv_template_service import CvTemplateService

    async def fake_first_page_png(self, template):
        return b"fake-png"

    monkeypatch.setattr(CvTemplateService, "first_page_png", fake_first_page_png)

    seen_prompts: list[str] = []

    def prompt_capture(schema, user_prompt):
        seen_prompts.append(user_prompt)
        return _mock_builder_turn(schema, user_prompt)

    register_mock_fixture(AITaskType.CV_BUILDER_CHAT, prompt_capture)
    try:
        user = await _auth_user(db)
        cv = await _cv(db, user)
        session = await _session(client, auth_headers)
        events = await _send(
            client,
            session["id"],
            auth_headers,
            "restyle the CV — switch to a more modern template",
            attachments=[{"kind": "cv", "cv_id": str(cv.id)}],
        )
    finally:
        register_mock_fixture(AITaskType.CV_BUILDER_CHAT, _mock_builder_turn)

    previews = [payload for name, payload in events if name == "preview"]
    assert len(previews) >= 1
    assert {"template_id", "title", "url"} <= set(previews[0])
    assert previews[0]["url"].endswith("/preview.png")

    cards = [
        payload
        for name, payload in events
        if name == "tool_call" and payload.get("name") == "template_previews"
    ]
    assert len(cards) == 1

    assert seen_prompts and "template_previews" in seen_prompts[0], (
        "the model prompt must map the attached images"
    )

    rows = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session["id"]))
    )
    assistant = _messages(rows.scalars().all())[-1]
    persisted = assistant.metadata_json["template_previews"]
    assert [e["template_id"] for e in persisted] == [e["template_id"] for e in previews]


async def test_no_preview_intent_skips_previews(
    client, db, auth_headers, builder_env, monkeypatch
):
    from app.services.cv_template_service import CvTemplateService

    calls = {"n": 0}

    async def fake_first_page_png(self, template):
        calls["n"] += 1
        return b"fake-png"

    monkeypatch.setattr(CvTemplateService, "first_page_png", fake_first_page_png)

    user = await _auth_user(db)
    cv = await _cv(db, user)
    session = await _session(client, auth_headers)
    events = await _send(
        client,
        session["id"],
        auth_headers,
        "please shorten the summary section",
        attachments=[{"kind": "cv", "cv_id": str(cv.id)}],
    )
    assert "builder_state" in names_of(events)
    assert [p for name, p in events if name == "preview"] == []
    assert calls["n"] == 0


def names_of(events):
    return [name for name, _ in events]
