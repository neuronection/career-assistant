"""Chat session admin: rename + delete.

Both verbs are tenant-scoped through `_owned_session` (the established
career convention: foreign sessions yield 403, missing ones 404).
"""

from app.models.chat_model import ChatMessage, ChatSession
from sqlalchemy import select


async def _create_session(client, headers, title="session admin"):
    response = await client.post(
        "/api/v1/chat/sessions", json={"title": title}, headers=headers
    )
    assert response.status_code == 201
    return response.json()


async def _register(client, email: str) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "supersecret1",
            "full_name": "Other Student",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_rename_session_updates_title(client, db, auth_headers):
    session = await _create_session(client, auth_headers)
    response = await client.patch(
        f"/api/v1/chat/sessions/{session['id']}",
        json={"title": "Nursing in the NHS"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Nursing in the NHS"

    rows = (
        (await db.execute(select(ChatSession).where(ChatSession.id == session["id"])))
        .scalars()
        .all()
    )
    assert rows[0].title == "Nursing in the NHS"


async def test_rename_rejects_empty_and_overlong_titles(client, auth_headers):
    session = await _create_session(client, auth_headers)
    for title in ("", "x" * 201):
        response = await client.patch(
            f"/api/v1/chat/sessions/{session['id']}",
            json={"title": title},
            headers=auth_headers,
        )
        assert response.status_code == 422


async def test_delete_session_cascades_messages(client, db, auth_headers):
    session = await _create_session(client, auth_headers)
    db.add(ChatMessage(session_id=session["id"], role="user", content="hello there"))
    await db.commit()

    response = await client.delete(
        f"/api/v1/chat/sessions/{session['id']}", headers=auth_headers
    )
    assert response.status_code == 204

    sessions = (await db.execute(select(ChatSession))).scalars().all()
    messages = (await db.execute(select(ChatMessage))).scalars().all()
    assert sessions == []
    assert messages == []


async def test_delete_missing_session_returns_404(client, auth_headers):
    response = await client.delete(
        "/api/v1/chat/sessions/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_foreign_sessions_rejected_for_both_verbs(client, db, auth_headers):
    other = await _register(client, "other-student@example.com")
    session = await _create_session(client, other)
    for method in ("patch", "delete"):
        kwargs = {"json": {"title": "stolen"}} if method == "patch" else {}
        response = await getattr(client, method)(
            f"/api/v1/chat/sessions/{session['id']}",
            headers=auth_headers,
            **kwargs,
        )
        assert response.status_code == 403


async def test_list_reports_last_activity_and_orders_by_it(client, db, auth_headers):
    """The list carries computed last activity (newest message wins over
    the session's own update) and orders most-recently-active first."""
    older = await _create_session(client, auth_headers, title="older thread")
    newer = await _create_session(client, auth_headers, title="newer thread")
    assert older["created_at"] <= newer["created_at"]

    db.add(
        ChatMessage(
            session_id=older["id"], role="user", content="keep this thread alive"
        )
    )
    await db.commit()

    response = await client.get("/api/v1/chat/sessions", headers=auth_headers)
    assert response.status_code == 200
    rows = response.json()
    by_id = {row["id"]: row for row in rows}
    assert (
        by_id[older["id"]]["last_activity_at"] >= by_id[newer["id"]]["last_activity_at"]
    )
    assert rows[0]["id"] == older["id"]


async def test_create_and_rename_responses_carry_last_activity(
    client, db, auth_headers
):
    created = await _create_session(client, auth_headers)
    assert created["last_activity_at"] >= created["created_at"]

    db.add(ChatMessage(session_id=created["id"], role="user", content="a message"))
    await db.commit()

    response = await client.patch(
        f"/api/v1/chat/sessions/{created['id']}",
        json={"title": "renamed thread"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["last_activity_at"] >= created["created_at"]
