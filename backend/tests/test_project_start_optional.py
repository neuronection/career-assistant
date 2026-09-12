"""Projects are open-ended by nature: their start date is optional."""


async def test_project_can_be_created_without_a_start(client, db, auth_headers):
    response = await client.post(
        "/api/v1/me/experience",
        json={
            "kind": "project",
            "title": "Campus events app",
            "description": "Weekend project",
            "open_ended": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["start"] in (None, "")


async def test_other_kinds_still_require_a_start(client, db, auth_headers):
    response = await client.post(
        "/api/v1/me/experience",
        json={
            "kind": "internship",
            "title": "Backend Intern",
            "open_ended": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "start" in response.text


async def test_project_without_start_is_omitted_from_ordered_context(
    client, db, auth_headers, profile_ready
):
    created = await client.post(
        "/api/v1/me/experience",
        json={
            "kind": "project",
            "title": "Undated project",
            "open_ended": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    sources = (
        await client.get("/api/v1/cv/context/sources", headers=auth_headers)
    ).json()
    projects = next(
        source for source in sources["sources"] if source["key"] == "projects"
    )
    assert projects["items"], "an undated project still resolves as a source item"
