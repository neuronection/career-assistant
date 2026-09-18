"""Chat CV attachments (plan 78.1): per-message references, prompt
blocks (latest version or no-write preview fallback), earlier-reference
inheritance, regenerate inheritance, validation."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.chat_model import ChatMessage
from app.models.user_model import User
from app.schemas.cv import CvDocumentCreate
from app.services.chat_attachments import resolve_attachments
from app.services.cv_service import CvService
from app.schemas.chat import ChatAttachmentIn

from tests.test_chat_streaming import _parse_sse


async def _auth_user(db) -> User:
    rows = await db.execute(
        select(User).where(User.email == settings.DEFAULT_USER_EMAIL)
    )
    return rows.scalars().one()


async def _cv(db, user, title="Backend CV") -> object:
    return await CvService(db).create(user.id, CvDocumentCreate(title=title))


async def _session(client, headers) -> dict:
    return (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "refs"}, headers=headers
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


async def test_attachment_validation(db, auth_headers, client):
    user = await _auth_user(db)
    cv = await _cv(db, user)

    resolved = await resolve_attachments(db, user.id, [ChatAttachmentIn(cv_id=cv.id)])
    assert resolved == [{"kind": "cv", "cv_id": str(cv.id), "title": "Backend CV"}]

    with pytest.raises(Exception):
        await resolve_attachments(db, user.id, [ChatAttachmentIn(cv_id=uuid.uuid4())])
    with pytest.raises(Exception):
        await resolve_attachments(
            db,
            user.id,
            [ChatAttachmentIn(cv_id=cv.id)] * 3,
        )


async def test_cross_user_attachment_422(client, db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    session = await _session(client, auth_headers)

    email = f"x-{uuid.uuid4().hex[:8]}@example.com"
    other = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret1"},
        )
    ).json()

    response = await client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        json={"content": "hi", "attachments": [{"kind": "cv", "cv_id": str(cv.id)}]},
        headers={"Authorization": f"Bearer {other['access_token']}"},
    )
    assert response.status_code == 422


async def test_reference_block_and_chips(client, db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user, title="My Career CV")
    session = await _session(client, auth_headers)

    events = await _send(
        client,
        session["id"],
        auth_headers,
        "Which jobs fit this CV?",
        attachments=[{"kind": "cv", "cv_id": str(cv.id)}],
    )
    meta = next(p for n, p in events if n == "meta")
    assert meta["message_id"]

    rows = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session["id"]))
    )
    messages = sorted(rows.scalars().all(), key=lambda m: m.created_at)
    user_message = next(m for m in messages if m.role == "user")
    assert user_message.metadata_json["attachments"][0]["cv_id"] == str(cv.id)
    assistant = next(m for m in messages if m.role == "assistant")
    assert assistant.metadata_json["referenced_cv_ids"] == [str(cv.id)]
    assert "My Career CV" in assistant.content


async def test_uncompiled_cv_falls_back_to_preview_and_writes_no_version(
    client, db, auth_headers
):
    from app.models.cv_model import CvVersion

    user = await _auth_user(db)
    cv = await _cv(db, user)
    session = await _session(client, auth_headers)

    events = await _send(
        client,
        session["id"],
        auth_headers,
        "what do you think of this cv",
        attachments=[{"kind": "cv", "cv_id": str(cv.id)}],
    )
    assert any(n == "flow_finished" for n, _ in events)
    versions = (
        (await db.execute(select(CvVersion).where(CvVersion.cv_document_id == cv.id)))
        .scalars()
        .all()
    )
    assert versions == [], "reference rendering must never compile"


async def test_followup_inherits_earlier_reference(client, db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user, title="Earlier CV")
    session = await _session(client, auth_headers)

    await _send(
        client,
        session["id"],
        auth_headers,
        "summarize this CV",
        attachments=[{"kind": "cv", "cv_id": str(cv.id)}],
    )
    events = await _send(
        client,
        session["id"],
        auth_headers,
        "and what about the skills section?",
    )
    assert any(n == "flow_finished" for n, _ in events)
    rows = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session["id"]))
    )
    # ORDER matters: without an explicit sort the DB's physical row order
    # decides which assistant message is "last" (bit us when page layout
    # shifted — the -1 row was the FIRST turn's reply).
    assistants = sorted(
        (m for m in rows.scalars().all() if m.role == "assistant"),
        key=lambda m: m.created_at,
    )
    assert len(assistants) == 2
    assert assistants[-1].metadata_json["referenced_cv_ids"] == [str(cv.id)]
    assert "attached earlier" in assistants[-1].content


async def test_regenerate_inherits_attachments(client, db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user, title="Regen CV")
    session = await _session(client, auth_headers)

    await _send(
        client,
        session["id"],
        auth_headers,
        "review this cv",
        attachments=[{"kind": "cv", "cv_id": str(cv.id)}],
    )
    rows = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session["id"]))
    )
    first_user = next(m for m in rows.scalars().all() if m.role == "user")

    response = await client.post(
        f"/api/v1/chat/messages/{first_user.id}/regenerate",
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert any(n == "flow_finished" for n, _ in events)

    rows = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session["id"]))
    )
    assistants = [m for m in rows.scalars().all() if m.role == "assistant"]
    assert len(assistants) == 2
    assert all(a.metadata_json["referenced_cv_ids"] == [str(cv.id)] for a in assistants)


async def test_edit_branch_keeps_attachments_without_body(client, db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user, title="Edit CV")
    session = await _session(client, auth_headers)

    await _send(
        client,
        session["id"],
        auth_headers,
        "review this cv please",
        attachments=[{"kind": "cv", "cv_id": str(cv.id)}],
    )
    rows = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session["id"]))
    )
    first_user = next(m for m in rows.scalars().all() if m.role == "user")

    response = await client.post(
        f"/api/v1/chat/messages/{first_user.id}/edit",
        json={"content": "review this cv thoroughly"},
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert any(n == "flow_finished" for n, _ in events)
    rows = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session["id"]))
    )
    edited = [
        m
        for m in rows.scalars().all()
        if m.role == "user" and m.content == "review this cv thoroughly"
    ]
    assert edited, "edited branch persisted"
    assert edited[0].metadata_json["attachments"][0]["cv_id"] == str(cv.id)
