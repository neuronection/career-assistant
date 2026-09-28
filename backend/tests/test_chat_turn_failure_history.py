"""Uniform chat error display: failed-turn markers are display-only."""

import uuid

from tests.conftest import user_id_from_headers


async def test_failed_turn_markers_stay_out_of_model_history(
    db, client, auth_headers, profile_ready
):
    from app.models.chat_model import ChatMessage
    from app.services.chat_service import ChatService

    session = await client.post(
        "/api/v1/chat/sessions", json={"title": "History"}, headers=auth_headers
    )
    assert session.status_code == 201
    session_id = uuid.UUID(session.json()["id"])
    user_id = uuid.UUID(user_id_from_headers(auth_headers))

    first = ChatMessage(session_id=session_id, role="user", content="hello")
    db.add(first)
    await db.flush()
    marker = ChatMessage(
        session_id=session_id,
        role="assistant",
        content="",
        metadata_json={"turn_failed": {"code": "ai_error", "detail": "boom"}},
        parent_id=first.id,
    )
    db.add(marker)
    await db.flush()
    second = ChatMessage(
        session_id=session_id, role="user", content="try again", parent_id=marker.id
    )
    db.add(second)
    await db.commit()

    service = ChatService(db)
    _session, history, _message_id = await service.begin_message(
        user_id, session_id, "next question"
    )
    contents = [entry["content"] for entry in history]
    assert "" not in contents, "failed-turn marker leaked into model history"
    assert [entry["role"] for entry in history] == ["user", "user"]
