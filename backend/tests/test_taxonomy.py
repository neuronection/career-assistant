async def test_interest_taxonomy_seeded(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/taxonomy/interests", headers=auth_headers)
    assert response.status_code == 200
    tags = response.json()
    assert len(tags) >= 40
    keys = {t["key"] for t in tags}
    assert "technology-software" in keys
    assert "people-health" in keys


async def test_interest_taxonomy_category_filter(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/taxonomy/interests?category=science", headers=auth_headers)
    tags = response.json()
    assert tags
    assert all(t["category"] == "science" for t in tags)


async def test_skill_taxonomy_seeded(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/taxonomy/skills", headers=auth_headers)
    skills = response.json()
    assert len(skills) >= 25
    keys = {s["key"] for s in skills}
    assert "programming" in keys
    assert "empathy" in keys


async def test_taxonomy_requires_auth(client):
    assert (await client.get("/api/v1/taxonomy/interests")).status_code == 401


async def _bulk_skill_id(db, key: str) -> str:
    from sqlalchemy import select

    from app.models.taxonomy_model import Skill

    skill = (await db.execute(select(Skill).where(Skill.key == key))).scalars().first()
    assert skill is not None, f"seed skill {key} missing"
    return str(skill.id)


async def _statuses(client, headers, *keys: str) -> dict[str, str]:
    rows = (
        await client.get("/api/v1/taxonomy/skills?include_proposed=true", headers=headers)
    ).json()
    return {row["key"]: row["status"] for row in rows if row["key"] in keys}


async def test_bulk_skill_lifecycle_actions(client, db, client_admin_headers, seeded_catalog):
    """promote/deprecate/restore act per id; inapplicable ids are failures."""
    for key in ("bulk-one", "bulk-two"):
        await client.put(
            "/api/v1/me/skills",
            json={"skills": [{"skill_key": key, "level": 3}]},
            headers=client_admin_headers,
        )
    one = await _bulk_skill_id(db, "bulk-one")
    two = await _bulk_skill_id(db, "bulk-two")
    active = await _bulk_skill_id(db, "programming")

    promoted = await client.post(
        "/api/v1/admin/skills/bulk",
        json={"ids": [one, two, active], "action": "promote"},
        headers=client_admin_headers,
    )
    assert promoted.status_code == 200, promoted.text
    body = promoted.json()
    assert sorted(body["affected"]) == sorted([one, two])
    assert [row["key"] for row in body["failed"]] == ["programming"]
    assert "Only proposed" in body["failed"][0]["reason"]

    assert await _statuses(client, client_admin_headers, "bulk-one", "bulk-two") == {
        "bulk-one": "active",
        "bulk-two": "active",
    }

    deprecated = await client.post(
        "/api/v1/admin/skills/bulk",
        json={"ids": [one, two], "action": "deprecate"},
        headers=client_admin_headers,
    )
    assert deprecated.json()["affected"] == [one, two]
    restored = await client.post(
        "/api/v1/admin/skills/bulk",
        json={"ids": [one], "action": "restore"},
        headers=client_admin_headers,
    )
    assert restored.json()["affected"] == [one]
    assert await _statuses(client, client_admin_headers, "bulk-one", "bulk-two") == {
        "bulk-one": "active",
        "bulk-two": "deprecated",
    }


async def test_bulk_merge_many_into_one(client, db, client_admin_headers, seeded_catalog):
    for key in ("bulk-merge-one", "bulk-merge-two"):
        await client.put(
            "/api/v1/me/skills",
            json={"skills": [{"skill_key": key, "level": 3}]},
            headers=client_admin_headers,
        )
    first = await _bulk_skill_id(db, "bulk-merge-one")
    second = await _bulk_skill_id(db, "bulk-merge-two")
    target = await _bulk_skill_id(db, "programming")

    merged = await client.post(
        "/api/v1/admin/skills/bulk",
        json={"ids": [first, second, target], "action": "merge", "target_id": target},
        headers=client_admin_headers,
    )
    assert merged.status_code == 200, merged.text
    body = merged.json()
    assert sorted(body["affected"]) == sorted([first, second])
    assert [row["key"] for row in body["failed"]] == ["programming"]
    assert "into itself" in body["failed"][0]["reason"]

    statuses = await _statuses(
        client, client_admin_headers, "bulk-merge-one", "bulk-merge-two", "programming"
    )
    assert statuses["bulk-merge-one"] == "deprecated"
    assert statuses["bulk-merge-two"] == "deprecated"
    target_row = next(
        row
        for row in (
            await client.get(
                "/api/v1/taxonomy/skills?include_proposed=true", headers=client_admin_headers
            )
        ).json()
        if row["key"] == "programming"
    )
    assert "bulk-merge-one" in target_row["aliases"]


async def test_bulk_delete_reports_references(client, db, client_admin_headers, seeded_catalog):
    created = await client.post(
        "/api/v1/taxonomy/skills",
        json={"key": "bulk-deletable", "label": "Bulk Deletable", "category": "test"},
        headers=client_admin_headers,
    )
    assert created.status_code == 201, created.text
    deletable = created.json()["id"]
    referenced = await _bulk_skill_id(db, "programming")

    deleted = await client.post(
        "/api/v1/admin/skills/bulk",
        json={"ids": [deletable, referenced], "action": "delete"},
        headers=client_admin_headers,
    )
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["affected"] == [deletable]
    assert [row["key"] for row in body["failed"]] == ["programming"]
    assert (body["failed"][0]["job_refs"] or 0) >= 1, "the reference counts ride the failure"
    assert "referenced" in body["failed"][0]["reason"]

    keys = await _statuses(client, client_admin_headers, "bulk-deletable")
    assert keys == {}, "the unreferenced skill is gone"


async def test_bulk_skill_action_guards(client, client_admin_headers):
    from tests.conftest import session_headers

    empty = await client.post(
        "/api/v1/admin/skills/bulk",
        json={"ids": [], "action": "promote"},
        headers=client_admin_headers,
    )
    assert empty.status_code == 422

    merge_without_target = await client.post(
        "/api/v1/admin/skills/bulk",
        json={"ids": ["00000000-0000-0000-0000-000000000001"], "action": "merge"},
        headers=client_admin_headers,
    )
    assert merge_without_target.status_code == 422

    target_without_merge = await client.post(
        "/api/v1/admin/skills/bulk",
        json={
            "ids": ["00000000-0000-0000-0000-000000000001"],
            "action": "promote",
            "target_id": "00000000-0000-0000-0000-000000000002",
        },
        headers=client_admin_headers,
    )
    assert target_without_merge.status_code == 422

    stranger = await client.post(
        "/api/v1/auth/register",
        json={"email": "bulk-stranger@example.com", "password": "supersecret1"},
    )
    forbidden = await client.post(
        "/api/v1/admin/skills/bulk",
        json={"ids": ["00000000-0000-0000-0000-000000000001"], "action": "promote"},
        headers=session_headers(stranger),
    )
    assert forbidden.status_code == 403
