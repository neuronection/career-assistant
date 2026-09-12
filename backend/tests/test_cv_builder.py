"""— CV builder: context engine, preview, compile, versions."""

import uuid


async def _second_user(client) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{uuid.uuid4().hex[:10]}@example.com",
            "password": "Str0ngPass!23",
            "full_name": "Second User",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _experience(client, headers, **overrides) -> dict:
    body = {
        "title": "DevOps intern",
        "kind": "internship",
        "org_name": "Acme Cloud",
        "start": "2025-01-01",
        "end": "2025-12-31",
        "hours_per_week": 40,
        "description": "Deployed things.",
        "skills": [],
        "achievements": [{"text": "Cut deploy time 40%"}],
        **overrides,
    }
    created = await client.post("/api/v1/me/experience", json=body, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()


async def _education(client, headers, **overrides) -> dict:
    body = {
        "institution": "Sample University",
        "program": "BSc Computer Science",
        "level": "bachelor",
        "start": "2022-09-01",
        "in_progress": True,
        **overrides,
    }
    created = await client.post("/api/v1/me/education", json=body, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()


async def _make_cv(client, headers, **overrides) -> dict:
    payload = {"title": "Backend Intern CV", **overrides}
    response = await client.post("/api/v1/cv", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_education_department_flows_into_context_and_snapshot(
    client, db, auth_headers, seeded_catalog
):
    """: the education department (catalog link) shows in the
    context tree and renders in the snapshot org line."""
    from app.models.university_model import Department, University

    university = University(name="Sample University", country="NL")
    db.add(university)
    await db.flush()
    department = Department(university_id=university.id, name="School of Computing")
    db.add(department)
    await db.commit()

    created = await client.post(
        "/api/v1/me/education",
        json={
            "institution": "Sample University",
            "program": "MSc Computer Science",
            "level": "master",
            "start": "2025-09-01",
            "in_progress": True,
            "university_id": str(university.id),
            "department_id": str(department.id),
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    sources = await client.get("/api/v1/cv/context/sources", headers=auth_headers)
    tree = {s["key"]: s for s in sources.json()["sources"]}
    assert tree["education"]["items"][0]["detail"] == (
        "Sample University — School of Computing"
    )

    cv = await _make_cv(client, auth_headers)
    resolved = await client.get(f"/api/v1/cv/{cv['id']}/context", headers=auth_headers)
    assert resolved.status_code == 200, resolved.text
    entry = resolved.json()["snapshot"]["education"][0]
    assert entry["org"] == "Sample University — School of Computing"
    assert entry["department"] == "School of Computing"
    assert entry["level"] == "master"


async def test_context_sources_list_items(client, auth_headers, seeded_catalog):
    await _experience(client, auth_headers)
    await _education(client, auth_headers)
    response = await client.get("/api/v1/cv/context/sources", headers=auth_headers)
    assert response.status_code == 200, response.text
    sources = {source["key"]: source for source in response.json()["sources"]}
    assert set(sources) == {
        "basics",
        "summary",
        "experience",
        "projects",
        "volunteer",
        "education",
        "certifications",
        "achievements",
        "skills",
        "languages",
        "interests",
    }
    assert sources["experience"]["items"][0]["label"] == "DevOps intern"
    assert sources["education"]["items"][0]["detail"] == "Sample University"


async def test_resolution_modes_and_exclusion_primacy(
    client, auth_headers, profile_ready, seeded_catalog
):
    first = await _experience(client, auth_headers)
    second = await _experience(
        client,
        auth_headers,
        title="Campus app",
        kind="project",
        org_name="",
        start="2024-02-01",
        end="2024-06-30",
    )
    cv = await _make_cv(client, auth_headers)

    resolved = await client.get(f"/api/v1/cv/{cv['id']}/context", headers=auth_headers)
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["snapshot_index"]["experience"] == [first["id"]]
    assert body["snapshot_index"]["projects"] == [second["id"]]
    assert body["snapshot"]["basics"]["location"] == "Athens, Greece"

    minus_one = await client.put(
        f"/api/v1/cv/{cv['id']}/context",
        json={
            "mode": "all",
            "include": [],
            "exclude": [{"source_key": "projects", "item_id": second["id"]}],
        },
        headers=auth_headers,
    )
    assert minus_one.status_code == 200, minus_one.text
    resolved = (
        await client.get(f"/api/v1/cv/{cv['id']}/context", headers=auth_headers)
    ).json()
    assert resolved["snapshot_index"]["experience"] == [first["id"]]
    assert "projects" not in resolved["snapshot_index"]

    plus_only = await client.put(
        f"/api/v1/cv/{cv['id']}/context",
        json={
            "mode": "none",
            "include": [{"source_key": "projects", "item_id": second["id"]}],
            "exclude": [],
        },
        headers=auth_headers,
    )
    assert plus_only.status_code == 200
    resolved = (
        await client.get(f"/api/v1/cv/{cv['id']}/context", headers=auth_headers)
    ).json()
    assert resolved["snapshot_index"] == {"projects": [second["id"]]}
    assert "basics" not in resolved["snapshot"]

    excluded_but_included = await client.put(
        f"/api/v1/cv/{cv['id']}/context",
        json={
            "mode": "custom",
            "include": [
                {"source_key": "projects", "item_id": second["id"]},
            ],
            "exclude": [{"source_key": "projects", "item_id": second["id"]}],
        },
        headers=auth_headers,
    )
    assert excluded_but_included.status_code == 200
    resolved = (
        await client.get(f"/api/v1/cv/{cv['id']}/context", headers=auth_headers)
    ).json()
    assert resolved["snapshot"] == {}, "exclusions must win over includes"


async def test_experience_sources_split_by_kind(
    client, auth_headers, profile_ready, seeded_catalog
):
    """Plan 70: work/projects/volunteer resolve as three disjoint sources."""
    job = await _experience(client, auth_headers)
    project = await _experience(
        client,
        auth_headers,
        title="Campus app",
        kind="project",
        org_name="",
        start="2024-02-01",
        end="2024-06-30",
    )
    volunteer = await _experience(
        client,
        auth_headers,
        title="Food bank helper",
        kind="volunteer",
        org_name="Food Bank",
        start="2023-10-01",
        end="2024-01-31",
    )
    sources = {
        source["key"]: source
        for source in (
            await client.get("/api/v1/cv/context/sources", headers=auth_headers)
        ).json()["sources"]
    }
    assert [item["item_id"] for item in sources["experience"]["items"]] == [job["id"]]
    assert [item["item_id"] for item in sources["projects"]["items"]] == [project["id"]]
    assert [item["item_id"] for item in sources["volunteer"]["items"]] == [
        volunteer["id"]
    ]
    assert sources["experience"]["label"] == "Work Experience"


async def test_preview_renders_without_versioning(
    client, auth_headers, profile_ready, seeded_catalog
):
    await _experience(client, auth_headers)
    cv = await _make_cv(client, auth_headers)
    response = await client.post(f"/api/v1/cv/{cv['id']}/preview", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "DevOps intern" in body["html"]
    assert body["metrics"]["estimated_pages"] >= 1
    assert body["resolution"]["snapshot_index"]["experience"]
    versions = await client.get(f"/api/v1/cv/{cv['id']}/versions", headers=auth_headers)
    assert versions.json() == []


async def test_compile_versions_and_traceability(
    client, auth_headers, profile_ready, seeded_catalog
):
    await _experience(client, auth_headers)
    cv = await _make_cv(client, auth_headers)
    response = await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"]["version"] == 1
    assert "DevOps intern" in body["html"]
    content = body["version"]["content"]
    assert content["snapshot"]["experience"][0]["org"] == "Acme Cloud"
    refs = body["version"]["context_resolution"]["items"]
    assert {ref["source_key"] for ref in refs} >= {"experience", "basics", "summary"}
    assert all(ref["item_id"] for ref in refs)

    again = await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    assert again.json()["version"]["content_hash"] == body["version"]["content_hash"]


async def test_compile_empty_selection_rejected(client, auth_headers, seeded_catalog):
    cv = await _make_cv(
        client, auth_headers, context={"mode": "none", "include": [], "exclude": []}
    )
    response = await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    assert response.status_code == 400
    assert "Nothing to compile" in response.json()["detail"]


async def test_staleness_diffs_against_baseline(
    client, auth_headers, profile_ready, seeded_catalog
):
    item = await _experience(client, auth_headers)
    cv = await _make_cv(client, auth_headers)
    await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)

    status = await client.get(
        f"/api/v1/cv/{cv['id']}/context/status", headers=auth_headers
    )
    assert status.status_code == 200
    body = status.json()
    assert body["has_baseline"] and body["stale"] is False

    updated = await client.patch(
        f"/api/v1/me/experience/{item['id']}",
        json={"description": "Deployed many things."},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    body = (
        await client.get(f"/api/v1/cv/{cv['id']}/context/status", headers=auth_headers)
    ).json()
    assert body["stale"] is True
    assert (ref["item_id"] for ref in body["changed"])

    await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    body = (
        await client.get(f"/api/v1/cv/{cv['id']}/context/status", headers=auth_headers)
    ).json()
    assert body["stale"] is False

    deleted = await client.delete(
        f"/api/v1/me/experience/{item['id']}", headers=auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    body = (
        await client.get(f"/api/v1/cv/{cv['id']}/context/status", headers=auth_headers)
    ).json()
    assert body["stale"] is True
    assert body["removed"], "a deleted source item must show as removed"


async def test_overrides_patch_snapshot(
    client, auth_headers, profile_ready, seeded_catalog
):
    cv = await _make_cv(client, auth_headers)
    patched = await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "overrides": {"summary:summary": {"summary": "Custom objective"}}
            }
        },
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    preview = await client.post(f"/api/v1/cv/{cv['id']}/preview", headers=auth_headers)
    assert "Custom objective" in preview.json()["html"]


async def test_restore_copy_forward(
    client, auth_headers, profile_ready, seeded_catalog
):
    cv = await _make_cv(client, auth_headers)
    first = (
        await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    ).json()
    custom_blocks = [
        {"kind": "header"},
        {"kind": "custom_text", "props": {"title": "Note", "text": "Hello"}},
    ]
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={"working_content": {"blocks": custom_blocks, "overrides": {}}},
        headers=auth_headers,
    )
    await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    restored = await client.post(
        f"/api/v1/cv/{cv['id']}/versions/1/restore", headers=auth_headers
    )
    assert restored.status_code == 200, restored.text
    working = restored.json()["working_content"]
    assert working["blocks"] == first["version"]["content"]["blocks"]
    assert working["overrides"] == {}


async def test_duplicate_copies_state_not_versions(
    client, auth_headers, profile_ready, seeded_catalog
):
    cv = await _make_cv(client, auth_headers)
    await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    copy = await client.post(f"/api/v1/cv/{cv['id']}/duplicate", headers=auth_headers)
    assert copy.status_code == 201, copy.text
    body = copy.json()
    assert body["title"] == "Backend Intern CV (copy)"
    assert body["context"] == cv["context"]
    versions = await client.get(
        f"/api/v1/cv/{body['id']}/versions", headers=auth_headers
    )
    assert versions.json() == []


async def test_builder_isolated_per_user(
    client, auth_headers, profile_ready, seeded_catalog
):
    cv = await _make_cv(client, auth_headers)
    other = await _second_user(client)
    preview = await client.post(f"/api/v1/cv/{cv['id']}/preview", headers=other)
    assert preview.status_code == 404
    compile_attempt = await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=other)
    assert compile_attempt.status_code == 404


async def test_cv_can_use_a_specific_template(
    client, auth_headers, profile_ready, seeded_catalog
):
    created = await client.post(
        "/api/v1/cv/templates",
        json={
            "title": "My Serif",
            "content": {
                "blocks": [
                    {"kind": "header"},
                    {"kind": "summary"},
                    {
                        "kind": "items",
                        "props": {"title": "Experience", "source_key": "experience"},
                    },
                ]
            },
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    template = created.json()
    cv = await _make_cv(client, auth_headers, template_id=template["id"])
    assert cv["template_id"] == template["id"]
    preview = await client.post(f"/api/v1/cv/{cv['id']}/preview", headers=auth_headers)
    assert preview.status_code == 200, preview.text

    switched = await client.patch(
        f"/api/v1/cv/{cv['id']}", json={"template_id": None}, headers=auth_headers
    )
    assert switched.status_code == 200
    assert switched.json()["template_id"] is None

    foreign = await client.post(
        "/api/v1/cv",
        json={"title": "Bad", "template_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert foreign.status_code == 404


async def test_templates_actually_change_rendered_output(
    client, auth_headers, profile_ready, seeded_catalog
):
    async def _template(title: str, accent: str) -> dict:
        response = await client.post(
            "/api/v1/cv/templates",
            json={
                "title": title,
                "content": {
                    "blocks": [
                        {"kind": "header"},
                        {"kind": "summary"},
                        {
                            "kind": "items",
                            "props": {
                                "title": "Experience",
                                "source_key": "experience",
                            },
                        },
                    ],
                    "design": {"accent_color": accent},
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        return response.json()

    teal = await _template("Teal Layout", "#0f766e")
    red = await _template("Red Layout", "#b91c1c")
    cv = await _make_cv(client, auth_headers, template_id=teal["id"])

    teal_preview = await client.post(
        f"/api/v1/cv/{cv['id']}/preview", headers=auth_headers
    )
    assert "#0f766e" in teal_preview.json()["html"]

    switched = await client.patch(
        f"/api/v1/cv/{cv['id']}", json={"template_id": red["id"]}, headers=auth_headers
    )
    assert switched.status_code == 200
    red_preview = await client.post(
        f"/api/v1/cv/{cv['id']}/preview", headers=auth_headers
    )
    body = red_preview.json()
    assert "#b91c1c" in body["html"]
    assert "#0f766e" not in body["html"]

    compiled = await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    version = compiled.json()["version"]
    assert version["content"]["template_id"] == red["id"]


async def test_version_preview_renders_immutable_snapshot(
    client, auth_headers, profile_ready, seeded_catalog
):
    await _experience(client, auth_headers, title="Snapshot role")
    cv = await _make_cv(client, auth_headers)
    compiled = await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    assert compiled.status_code == 201

    preview = await client.get(
        f"/api/v1/cv/{cv['id']}/versions/1/preview", headers=auth_headers
    )
    assert preview.status_code == 200, preview.text
    assert "Snapshot role" in preview.text

    # mutate the profile; the old snapshot must render unchanged
    await _experience(client, auth_headers, title="Newer role")
    again = await client.get(
        f"/api/v1/cv/{cv['id']}/versions/1/preview", headers=auth_headers
    )
    assert "Snapshot role" in again.text
    assert "Newer role" not in again.text

    missing = await client.get(
        f"/api/v1/cv/{cv['id']}/versions/99/preview", headers=auth_headers
    )
    assert missing.status_code == 404
