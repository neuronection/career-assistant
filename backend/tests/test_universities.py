async def test_university_crud_and_departments(client, auth_headers):
    created = await client.post(
        "/api/v1/universities",
        json={
            "name": "National Test University",
            "country": "Greece",
            "city": "Athens",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    uni = created.json()

    dept = await client.post(
        f"/api/v1/universities/{uni['id']}/departments",
        json={
            "name": "School of Engineering",
            "field_key": "engineering",
            "duration_years": 5,
        },
        headers=auth_headers,
    )
    assert dept.status_code == 201
    dept_id = dept.json()["id"]

    admission = await client.post(
        f"/api/v1/universities/departments/{dept_id}/admissions",
        json={"year": 2025, "baseline_score": 82.5, "top_score": 97.0, "quota": 150},
        headers=auth_headers,
    )
    assert admission.status_code == 201
    assert float(admission.json()["baseline_score"]) == 82.5

    detail = await client.get(f"/api/v1/universities/{uni['id']}", headers=auth_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["departments"]) == 1
    assert body["departments"][0]["admissions"][0]["year"] == 2025


async def test_admission_upsert_same_year(client, auth_headers):
    uni = (
        await client.post(
            "/api/v1/universities",
            json={"name": "Upsert Uni", "country": "Greece"},
            headers=auth_headers,
        )
    ).json()
    dept = (
        await client.post(
            f"/api/v1/universities/{uni['id']}/departments",
            json={"name": "Dept A"},
            headers=auth_headers,
        )
    ).json()
    first = await client.post(
        f"/api/v1/universities/departments/{dept['id']}/admissions",
        json={"year": 2024, "baseline_score": 70},
        headers=auth_headers,
    )
    second = await client.post(
        f"/api/v1/universities/departments/{dept['id']}/admissions",
        json={"year": 2024, "baseline_score": 75},
        headers=auth_headers,
    )
    assert first.json()["id"] == second.json()["id"]
    assert float(second.json()["baseline_score"]) == 75


async def test_job_department_link(client, auth_headers, seeded_catalog):
    uni = (
        await client.post(
            "/api/v1/universities",
            json={"name": "Link Uni", "country": "Greece"},
            headers=auth_headers,
        )
    ).json()
    dept = (
        await client.post(
            f"/api/v1/universities/{uni['id']}/departments",
            json={"name": "School of Computing", "field_key": "computer-science"},
            headers=auth_headers,
        )
    ).json()
    job = (
        await client.get("/api/v1/jobs/software-developer", headers=auth_headers)
    ).json()
    link = await client.post(
        "/api/v1/universities/job-links",
        json={
            "job_id": job["id"],
            "department_id": dept["id"],
            "relevance": 9.5,
            "rationale": "Direct software pathway",
            "required_subjects": ["mathematics", "physics"],
            "typical_position": "Software Engineer",
            "employment_rate_pct": 92.0,
        },
        headers=auth_headers,
    )
    assert link.status_code == 201, link.text
    assert link.json()["relevance"] == 9.5

    detail = await client.get(
        "/api/v1/jobs/software-developer/match", headers=auth_headers
    )
    assert detail.status_code == 200
    pathways = detail.json()["university_pathways"]
    assert len(pathways) == 1
    assert pathways[0]["department"]["university"]["name"] == "Link Uni"
    assert pathways[0]["admissions"] == []


async def test_university_search(client, auth_headers):
    await client.post(
        "/api/v1/universities",
        json={"name": "Athens Tech", "country": "Greece"},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/universities",
        json={"name": "Berlin Uni", "country": "Germany"},
        headers=auth_headers,
    )
    found = await client.get("/api/v1/universities?q=athens", headers=auth_headers)
    assert len(found.json()) == 1
    by_country = await client.get(
        "/api/v1/universities?country=Germany", headers=auth_headers
    )
    assert len(by_country.json()) == 1
    assert by_country.json()[0]["name"] == "Berlin Uni"
