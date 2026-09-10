async def test_family_tree(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/jobs/tree", headers=auth_headers)
    assert response.status_code == 200
    tree = response.json()
    keys = {n["key"] for n in tree}
    assert "technology" in keys and "healthcare" in keys
    tech = next(n for n in tree if n["key"] == "technology")
    child_keys = {c["key"] for c in tech["children"]}
    assert "technology-software" in child_keys
    assert tech["level"] == 0
    assert tech["children"][0]["level"] == 1
    total_count = tech["job_count"] + sum(c["job_count"] for c in tech["children"])
    assert total_count >= 5


async def test_list_jobs_seeded(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/jobs?page_size=100", headers=auth_headers)
    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) >= 40
    codes = {j["code"] for j in jobs}
    assert "software-developer" in codes and "nurse" in codes


async def test_job_attributes_are_structured(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/jobs/software-developer", headers=auth_headers)
    job = response.json()
    attrs = job["attributes"]
    assert attrs["education"]["level"] == "bachelor"
    assert any(
        s["key"] == "programming" and s["required_level"] == 5 for s in job["skills"]
    )
    assert any(i["key"] == "technology-software" for i in job["interests"])
    assert attrs["demand"]["outlook"] == "hot"
    assert attrs["salary"]["median"] == [60000, 95000]
    assert attrs["typical_positives"][0]["title"]
    assert "office" in attrs["environments"]


async def test_job_search_by_q(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/jobs?q=nurse", headers=auth_headers)
    jobs = response.json()
    assert jobs
    assert all(
        "nurse" in j["title"].lower() or "nurse" in j["short_description"].lower()
        for j in jobs
    )


async def test_job_filter_by_family(client, auth_headers, seeded_catalog):
    response = await client.get(
        "/api/v1/jobs?family_key=healthcare", headers=auth_headers
    )
    jobs = response.json()
    assert jobs
    assert all(j["family_key"].startswith("healthcare") for j in jobs)


async def test_job_filter_by_demand(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/jobs?demand=hot", headers=auth_headers)
    jobs = response.json()
    assert jobs
    assert all(j["attributes"]["demand"]["outlook"] == "hot" for j in jobs)


async def test_job_filter_by_environment(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/jobs?environment=lab", headers=auth_headers)
    jobs = response.json()
    assert jobs
    assert all("lab" in j["attributes"]["environments"] for j in jobs)


async def test_job_filter_by_min_salary(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/jobs?min_salary=90000", headers=auth_headers)
    jobs = response.json()
    assert jobs
    assert all(j["attributes"]["salary"]["median"][1] >= 90000 for j in jobs)


async def test_job_relations_endpoint(client, auth_headers, seeded_catalog):
    response = await client.get(
        "/api/v1/jobs/relations/software-developer", headers=auth_headers
    )
    relations = response.json()
    assert len(relations) >= 3
    assert all(
        r["from_code"] == "software-developer" or r["to_code"] == "software-developer"
        for r in relations
    )
    types = {r["relation_type"] for r in relations}
    assert "specialises_into" in types


async def test_graph_from_root(client, auth_headers, seeded_catalog):
    response = await client.get(
        "/api/v1/jobs/graph?root=software-developer&depth=1", headers=auth_headers
    )
    assert response.status_code == 200
    graph = response.json()
    codes = {n["code"] for n in graph["nodes"]}
    assert "software-developer" in codes
    assert "ml-engineer" in codes
    assert graph["edges"]


async def test_graph_by_family(client, auth_headers, seeded_catalog):
    response = await client.get(
        "/api/v1/jobs/graph?family=technology", headers=auth_headers
    )
    graph = response.json()
    family_nodes = {n["code"] for n in graph["nodes"]}
    assert "software-developer" in family_nodes
    assert "nurse" not in family_nodes


async def test_create_and_update_manual_job(client, auth_headers, seeded_catalog):
    payload = {
        "code": "test-job-role",
        "title": "Test Job Role",
        "family_key": "technology",
        "short_description": "A role created by a test.",
        "attributes": {
            "subjects": ["mathematics"],
            "demand": {"outlook": "growing", "note": "", "sources": {}},
        },
        "interest_keys": ["technology-software"],
        "skills": [
            {"skill_key": "programming", "required_level": 6, "importance": "core"}
        ],
    }
    created = await client.post("/api/v1/jobs", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "user"
    assert [s["key"] for s in body["skills"]] == ["programming"]
    assert [i["key"] for i in body["interests"]] == ["technology-software"]

    updated = await client.put(
        "/api/v1/jobs/test-job-role",
        json={
            "title": "Renamed Role",
            "skills": [
                {
                    "skill_key": "problem-solving",
                    "required_level": 4,
                    "importance": "important",
                }
            ],
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Renamed Role"
    assert [s["key"] for s in updated.json()["skills"]] == ["problem-solving"]

    bad_skill = await client.put(
        "/api/v1/jobs/test-job-role",
        json={"skills": [{"skill_key": "no-such-skill", "required_level": 3}]},
        headers=auth_headers,
    )
    assert bad_skill.status_code == 400

    deleted = await client.delete("/api/v1/jobs/test-job-role", headers=auth_headers)
    assert deleted.status_code == 200
    gone = await client.get("/api/v1/jobs/test-job-role", headers=auth_headers)
    assert gone.status_code == 404


async def test_cannot_delete_seed_job(client, auth_headers, seeded_catalog):
    response = await client.delete("/api/v1/jobs/nurse", headers=auth_headers)
    assert response.status_code == 400


async def test_unknown_family_rejected(client, auth_headers, seeded_catalog):
    payload = {
        "code": "bad-family-job",
        "title": "Bad Family Job",
        "family_key": "does-not-exist",
    }
    response = await client.post("/api/v1/jobs", json=payload, headers=auth_headers)
    assert response.status_code == 400
