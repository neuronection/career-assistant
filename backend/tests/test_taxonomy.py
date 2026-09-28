async def test_interest_taxonomy_seeded(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/taxonomy/interests", headers=auth_headers)
    assert response.status_code == 200
    tags = response.json()
    assert len(tags) >= 40
    keys = {t["key"] for t in tags}
    assert "technology-software" in keys
    assert "people-health" in keys


async def test_interest_taxonomy_category_filter(client, auth_headers, seeded_catalog):
    response = await client.get(
        "/api/v1/taxonomy/interests?category=science", headers=auth_headers
    )
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
