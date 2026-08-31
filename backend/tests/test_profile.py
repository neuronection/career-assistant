async def test_profile_defaults_after_register(client, auth_headers):
    response = await client.get("/api/v1/profile", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["basics"]["education_level"] == "high_school"
    assert body["interests"] == []
    assert body["completeness"]["percent"] == 0


async def test_profile_section_update_and_completeness(
    client, auth_headers, profile_ready
):
    response = await client.get("/api/v1/profile", headers=auth_headers)
    body = response.json()
    assert len(body["interests"]) == 3
    assert body["basics"]["country"] == "Greece"
    assert body["completeness"]["percent"] == 100


async def test_profile_partial_update_keeps_other_sections(
    client, auth_headers, profile_ready
):
    response = await client.put(
        "/api/v1/profile",
        json={"hobbies": [{"key": "chess", "label": "Chess", "weight": 3}]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["hobbies"][0]["key"] == "chess"
    assert len(body["interests"]) == 3


async def test_profile_rejects_bad_weight(client, auth_headers):
    response = await client.put(
        "/api/v1/profile",
        json={"interests": [{"tag_key": "technology-software", "weight": 9}]},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_profile_rejects_bad_enum(client, auth_headers):
    response = await client.put(
        "/api/v1/profile",
        json={"basics": {"education_level": "not_a_level"}},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_profile_ai_analyze_mock(
    client, auth_headers, profile_ready, seeded_catalog
):
    response = await client.post("/api/v1/profile/ai-analyze", headers=auth_headers)
    assert response.status_code == 200, response.text
    summary = response.json()["ai_summary"]
    assert summary["summary"]
    existing = {"technology-software", "technology-ai", "technology-games"}
    for key in summary["suggested_interest_keys"]:
        assert key not in existing


async def test_isolated_profiles(client, auth_headers):
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    await client.put(
        "/api/v1/profile",
        json={"hobbies": [{"label": "run", "weight": 5}]},
        headers=auth_headers,
    )
    mine = await client.get("/api/v1/profile", headers=auth_headers)
    theirs = await client.get("/api/v1/profile", headers=other_headers)
    assert len(mine.json()["hobbies"]) == 1
    assert theirs.json()["hobbies"] == []
