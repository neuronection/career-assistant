"""Plan 212 S1.5 — reusable screening answers and the kit hand-off."""

import uuid

from tests.conftest import _make_posting, session_headers


async def test_saved_answer_crud_and_ownership(client, auth_headers, db, source):
    created = await client.post(
        "/api/v1/me/answers",
        json={
            "question_key": "availability",
            "question_text": "When can you start?",
            "answer_text": "Immediately.",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    answer = created.json()
    assert answer["answer_text"] == "Immediately."

    listing = await client.get("/api/v1/me/answers", headers=auth_headers)
    assert [row["question_key"] for row in listing.json()] == ["availability"]

    patched = await client.patch(
        f"/api/v1/me/answers/{answer['id']}",
        json={"answer_text": "From July."},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["answer_text"] == "From July."

    null_patch = await client.patch(
        f"/api/v1/me/answers/{answer['id']}",
        json={"answer_text": None},
        headers=auth_headers,
    )
    assert null_patch.status_code == 422

    deleted = await client.delete(f"/api/v1/me/answers/{answer['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/me/answers", headers=auth_headers)).json() == []


async def test_saved_answer_upsert_is_keyed_by_question(client, auth_headers):
    first = await client.post(
        "/api/v1/me/answers",
        json={"question_key": "availability", "answer_text": "Two weeks."},
        headers=auth_headers,
    )
    second = await client.post(
        "/api/v1/me/answers",
        json={"question_key": "availability", "answer_text": "One month."},
        headers=auth_headers,
    )
    assert first.status_code == 201 and second.status_code == 201
    listing = await client.get("/api/v1/me/answers", headers=auth_headers)
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["answer_text"] == "One month."


async def test_kit_returns_the_saved_answer(client, auth_headers, db, source, seeded_catalog):
    await client.post(
        "/api/v1/me/answers",
        json={
            "question_key": "availability",
            "answer_text": "Available immediately.",
        },
        headers=auth_headers,
    )
    posting = await _make_posting(db, source, external_id=f"answers-{uuid.uuid4().hex[:6]}")
    response = await client.get(f"/api/v1/postings/{posting.ref}/kit", headers=auth_headers)
    assert response.status_code == 200, response.text
    availability = next(row for row in response.json()["answers"] if row["key"] == "availability")
    assert availability["saved_answer"] == "Available immediately."


async def test_saved_answer_foreign_user_is_404(client, auth_headers):
    created = await client.post(
        "/api/v1/me/answers",
        json={"question_key": "availability", "answer_text": "Two weeks."},
        headers=auth_headers,
    )
    answer_id = created.json()["id"]
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "answers-other@example.com", "password": "supersecret1"},
    )
    other_headers = session_headers(other)
    patched = await client.patch(
        f"/api/v1/me/answers/{answer_id}",
        json={"answer_text": "Hijacked."},
        headers=other_headers,
    )
    assert patched.status_code == 404
    deleted = await client.delete(f"/api/v1/me/answers/{answer_id}", headers=other_headers)
    assert deleted.status_code == 404
