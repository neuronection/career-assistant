"""Plan 212 S1.7 — STAR story library, suggestions and practice hand-off."""

import uuid

from tests.conftest import _make_posting, session_headers


async def test_story_crud_and_ownership(client, auth_headers):
    created = await client.post(
        "/api/v1/me/interview/stories",
        json={
            "title": "Cut deploy time",
            "competency_keys": ["teamwork"],
            "situation": "Deploys were slow.",
            "task": "Cut the pipeline.",
            "action": "Parallelized the steps.",
            "result": "40% faster.",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    story = created.json()
    assert story["title"] == "Cut deploy time"

    listing = await client.get("/api/v1/me/interview/stories", headers=auth_headers)
    assert [row["id"] for row in listing.json()] == [story["id"]]

    patched = await client.patch(
        f"/api/v1/me/interview/stories/{story['id']}",
        json={"result": "55% faster."},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["result"] == "55% faster."

    other = await client.post(
        "/api/v1/auth/register",
        json={"email": f"stories-{uuid.uuid4().hex[:6]}@example.com", "password": "supersecret1"},
    )
    other_headers = session_headers(other)
    foreign = await client.patch(
        f"/api/v1/me/interview/stories/{story['id']}",
        json={"result": "Hijacked."},
        headers=other_headers,
    )
    assert foreign.status_code == 404

    deleted = await client.delete(
        f"/api/v1/me/interview/stories/{story['id']}", headers=auth_headers
    )
    assert deleted.status_code == 204


async def test_story_suggestions_exclude_linked_experience(client, auth_headers):
    experience = await client.post(
        "/api/v1/me/experience",
        json={
            "title": "DevOps intern",
            "kind": "internship",
            "org_name": "Acme",
            "start": "2025-01-01",
            "end": "2025-12-31",
            "description": "Cut deploy time by 40%.",
            "achievements": [],
            "skills": [],
        },
        headers=auth_headers,
    )
    assert experience.status_code == 201, experience.text
    item = experience.json()

    suggestions = await client.get("/api/v1/me/interview/stories/suggestions", headers=auth_headers)
    assert suggestions.status_code == 200, suggestions.text
    assert str(item["id"]) in {row["experience_item_id"] for row in suggestions.json()}

    created = await client.post(
        "/api/v1/me/interview/stories",
        json={"title": "DevOps story", "experience_item_id": item["id"]},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    after = await client.get("/api/v1/me/interview/stories/suggestions", headers=auth_headers)
    assert str(item["id"]) not in {row["experience_item_id"] for row in after.json()}


async def test_practice_prepends_a_story_question(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    story = await client.post(
        "/api/v1/me/interview/stories",
        json={
            "title": "Cut deploy time",
            "situation": "Slow deploys.",
            "task": "Speed them up.",
            "action": "Parallelized the pipeline.",
            "result": "40% faster.",
        },
        headers=auth_headers,
    )
    posting = await _make_posting(db, source, external_id=f"story-{uuid.uuid4().hex[:6]}")
    session = await client.post(
        "/api/v1/interview/sessions",
        json={"posting_ref": posting.ref, "kind": "behavioral", "story_ids": [story.json()["id"]]},
        headers=auth_headers,
    )
    assert session.status_code == 201, session.text
    plan = session.json()["plan"]
    assert plan[0]["id"].startswith("story-")
    assert plan[0]["question"] == "Walk me through this story: Cut deploy time."
    assert "40% faster" in plan[0]["focus"]


async def test_story_patch_rejects_null_text(client, auth_headers):
    created = await client.post(
        "/api/v1/me/interview/stories",
        json={"title": "A story"},
        headers=auth_headers,
    )
    story_id = created.json()["id"]
    for field in ("title", "situation", "result"):
        response = await client.patch(
            f"/api/v1/me/interview/stories/{story_id}",
            json={field: None},
            headers=auth_headers,
        )
        assert response.status_code == 422, (field, response.text)


async def test_interview_create_rejects_duplicate_story_ids(client, auth_headers):
    response = await client.post(
        "/api/v1/interview/sessions",
        json={
            "job_code": "backend-engineer",
            "story_ids": ["00000000-0000-0000-0000-000000000001"] * 2,
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_suggestion_uses_the_first_achievement(client, auth_headers):
    experience = await client.post(
        "/api/v1/me/experience",
        json={
            "title": "Data intern",
            "kind": "internship",
            "org_name": "Acme",
            "start": "2025-01-01",
            "end": "2025-12-31",
            "description": "",
            "achievements": [{"text": "Cut reporting time by 40%"}],
            "skills": [],
        },
        headers=auth_headers,
    )
    item_id = experience.json()["id"]
    suggestions = await client.get("/api/v1/me/interview/stories/suggestions", headers=auth_headers)
    row = next(row for row in suggestions.json() if row["experience_item_id"] == item_id)
    assert row["hint"] == "Cut reporting time by 40%"
