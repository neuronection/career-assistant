"""Admin surface: taxonomy CRUD, moderation queue, user management, audit."""

import pytest
from sqlalchemy import select

from app.models.taxonomy_model import Skill
from app.models.user_model import User
from app.services.job_worker import JobWorker


@pytest.fixture
async def _admin_and_user(client, db):
    """First user = admin, second = regular. Returns (admin_headers, user_headers)."""
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201
    admin = {"Authorization": f"Bearer {first.json()['access_token']}"}
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "supersecret1"},
    )
    assert second.status_code == 201
    user = {"Authorization": f"Bearer {second.json()['access_token']}"}
    return admin, user


async def test_taxonomy_create_requires_admin(client, _admin_and_user):
    admin, user = _admin_and_user
    denied = await client.post(
        "/api/v1/taxonomy/interests",
        json={"key": "new-tag", "label": "New", "category": "general"},
        headers=user,
    )
    assert denied.status_code == 403

    ok = await client.post(
        "/api/v1/taxonomy/interests",
        json={
            "key": "new-tag",
            "label": "New Tag",
            "category": "general",
            "description": "d",
        },
        headers=admin,
    )
    assert ok.status_code == 201
    assert ok.json()["key"] == "new-tag"
    assert ok.json()["deprecated"] is False


async def test_taxonomy_create_validates_slug(client, _admin_and_user):
    admin, _ = _admin_and_user
    bad = await client.post(
        "/api/v1/taxonomy/interests",
        json={"key": "Bad Key!", "label": "X", "category": "general"},
        headers=admin,
    )
    assert bad.status_code == 400

    first = await client.post(
        "/api/v1/taxonomy/interests",
        json={"key": "dup-tag", "label": "X", "category": "general"},
        headers=admin,
    )
    assert first.status_code == 201
    duplicate = await client.post(
        "/api/v1/taxonomy/interests",
        json={"key": "dup-tag", "label": "X", "category": "general"},
        headers=admin,
    )
    assert duplicate.status_code == 400


async def test_taxonomy_key_is_immutable_but_editable(client, _admin_and_user, db):
    admin, _ = _admin_and_user
    created = (
        await client.post(
            "/api/v1/taxonomy/skills",
            json={"key": "temp-skill", "label": "Temp", "category": "tech"},
            headers=admin,
        )
    ).json()

    key_change = await client.put(
        f"/api/v1/taxonomy/skills/{created['id']}",
        json={"key": "renamed"},
        headers=admin,
    )
    assert key_change.status_code == 422

    relabel = await client.put(
        f"/api/v1/taxonomy/skills/{created['id']}",
        json={"label": "Renamed"},
        headers=admin,
    )
    assert relabel.status_code == 200
    assert relabel.json()["label"] == "Renamed"

    deprecate = await client.put(
        f"/api/v1/taxonomy/skills/{created['id']}",
        json={"status": "deprecated"},
        headers=admin,
    )
    assert deprecate.status_code == 200
    assert deprecate.json()["status"] == "deprecated"

    tag = (
        (await db.execute(select(Skill).where(Skill.key == "temp-skill")))
        .scalars()
        .first()
    )
    assert tag.status == "deprecated"

    bad_status = await client.put(
        f"/api/v1/taxonomy/skills/{created['id']}",
        json={"status": "zombie"},
        headers=admin,
    )
    assert bad_status.status_code == 400


async def test_taxonomy_delete_guard_and_success(
    client, db, _admin_and_user, seeded_catalog
):
    admin, _ = _admin_and_user
    tags = (await client.get("/api/v1/taxonomy/interests", headers=admin)).json()
    tag = next(t for t in tags if t["key"] == "technology-software")

    referenced = await client.delete(
        f"/api/v1/taxonomy/interests/{tag['id']}", headers=admin
    )
    assert referenced.status_code == 409
    body = referenced.json()["detail"]
    assert body["job_refs"] >= 1

    free = (
        await client.post(
            "/api/v1/taxonomy/skills",
            json={"key": "free-tag", "label": "Free", "category": "general"},
            headers=admin,
        )
    ).json()
    deleted = await client.delete(
        f"/api/v1/taxonomy/skills/{free['id']}", headers=admin
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == "free-tag"


async def test_deprecated_tags_hidden_on_request(client, _admin_and_user):
    admin, _ = _admin_and_user
    tag = (
        await client.post(
            "/api/v1/taxonomy/interests",
            json={"key": "old-tag", "label": "Old", "category": "general"},
            headers=admin,
        )
    ).json()
    await client.put(
        f"/api/v1/taxonomy/interests/{tag['id']}",
        json={"deprecated": True},
        headers=admin,
    )

    all_rows = (await client.get("/api/v1/taxonomy/interests", headers=admin)).json()
    assert any(r["key"] == "old-tag" for r in all_rows)
    filtered = (
        await client.get(
            "/api/v1/taxonomy/interests?include_deprecated=false", headers=admin
        )
    ).json()
    assert all(r["key"] != "old-tag" for r in filtered)


async def test_moderation_queue_and_bulk_actions(
    client, db, _admin_and_user, seeded_catalog
):
    admin, user = _admin_and_user
    mine = (
        await client.post(
            "/api/v1/jobs",
            json={
                "code": "draft-role",
                "title": "Draft Role",
                "family_key": "technology-software",
                "short_description": "d",
                "attributes": {},
                "interest_keys": ["technology-software"],
            },
            headers=user,
        )
    ).json()
    assert mine["status"] == "draft"

    queue = (await client.get("/api/v1/admin/jobs?status=draft", headers=admin)).json()
    assert "draft-role" in [j["code"] for j in queue]

    third = await client.post(
        "/api/v1/auth/register",
        json={"email": "third@example.com", "password": "supersecret1"},
    )
    other_headers = {"Authorization": f"Bearer {third.json()['access_token']}"}
    forbidden = await client.get("/api/v1/admin/jobs", headers=other_headers)
    assert forbidden.status_code == 403

    published = await client.post(
        "/api/v1/admin/jobs/bulk",
        json={"ids": [mine["id"]], "action": "publish"},
        headers=admin,
    )
    assert published.json() == {"published": 1, "rejected": 0}
    detail = await client.get("/api/v1/jobs/draft-role", headers=admin)
    assert detail.json()["status"] == "published"

    rejected = await client.post(
        "/api/v1/admin/jobs/bulk",
        json={"ids": [mine["id"]], "action": "reject"},
        headers=admin,
    )
    assert rejected.json()["rejected"] == 1
    gone = await client.get("/api/v1/jobs/draft-role", headers=admin)
    assert gone.status_code == 404


async def test_user_management_guards(client, _admin_and_user, db):
    admin, user = _admin_and_user
    listing = (await client.get("/api/v1/admin/users", headers=admin)).json()
    emails = {u["email"] for u in listing}
    assert {"admin@example.com", "user@example.com"} <= emails

    user_row = (
        (await db.execute(select(User).where(User.email == "user@example.com")))
        .scalars()
        .first()
    )
    admin_row = (
        (await db.execute(select(User).where(User.email == "admin@example.com")))
        .scalars()
        .first()
    )

    self_demote = await client.patch(
        f"/api/v1/admin/users/{admin_row.id}", json={"is_admin": False}, headers=admin
    )
    assert self_demote.status_code == 400

    self_deactivate = await client.patch(
        f"/api/v1/admin/users/{admin_row.id}", json={"is_active": False}, headers=admin
    )
    assert self_deactivate.status_code == 400

    deactivated = await client.patch(
        f"/api/v1/admin/users/{user_row.id}", json={"is_active": False}, headers=admin
    )
    assert deactivated.json()["is_active"] is False

    stale = await client.get("/api/v1/auth/me", headers=user)
    assert stale.status_code == 401


async def test_reset_password_and_force_logout(client, _admin_and_user, db):
    admin, user = _admin_and_user
    user_row = (
        (await db.execute(select(User).where(User.email == "user@example.com")))
        .scalars()
        .first()
    )

    reset = await client.post(
        f"/api/v1/admin/users/{user_row.id}/reset-password",
        json={"new_password": "brandnewpw1"},
        headers=admin,
    )
    assert reset.status_code == 200

    stale = await client.get("/api/v1/auth/me", headers=user)
    assert stale.status_code == 401

    relogin = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "brandnewpw1"},
    )
    assert relogin.status_code == 200
    new_headers = {"Authorization": f"Bearer {relogin.json()['access_token']}"}

    force = await client.post(
        f"/api/v1/admin/users/{user_row.id}/force-logout", headers=admin
    )
    assert force.status_code == 200
    killed = await client.get("/api/v1/auth/me", headers=new_headers)
    assert killed.status_code == 401


async def test_audit_viewer_filters(client, db, _admin_and_user, seeded_catalog):
    admin, user = _admin_and_user
    await client.post("/api/v1/jobs/generate", json={"count": 1}, headers=user)
    worker = JobWorker(db)
    while await worker.run_once():
        pass

    listing = (await client.get("/api/v1/admin/ai/generations", headers=admin)).json()
    assert listing["total"] >= 1
    assert any(g["task_type"] == "job_generate" for g in listing["items"])

    by_task = (
        await client.get(
            "/api/v1/admin/ai/generations?task=job_generate", headers=admin
        )
    ).json()
    assert all(g["task_type"] == "job_generate" for g in by_task["items"])

    by_status = (
        await client.get("/api/v1/admin/ai/generations?status=ok", headers=admin)
    ).json()
    assert by_status["total"] >= 1

    forbidden = await client.get("/api/v1/admin/ai/generations", headers=user)
    assert forbidden.status_code == 403
