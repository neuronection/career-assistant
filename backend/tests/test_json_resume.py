"""Plan 212 S2.4 — JSON Resume export/import with a review report."""


async def _seed(client, auth_headers, db):
    experience = await client.post(
        "/api/v1/me/experience",
        json={
            "title": "Data intern",
            "kind": "internship",
            "org_name": "Acme",
            "start": "2025-01-01",
            "end": "2025-06-30",
            "description": "Built reports.",
            "achievements": [{"text": "Cut reporting time by 40%"}],
            "skills": [],
        },
        headers=auth_headers,
    )
    assert experience.status_code == 201, experience.text
    education = await client.post(
        "/api/v1/me/education",
        json={
            "institution": "Sample University",
            "program": "BSc Computer Science",
            "level": "bachelor",
            "start": "2022-09-01",
            "in_progress": True,
        },
        headers=auth_headers,
    )
    assert education.status_code == 201, education.text


async def test_export_roundtrips_known_fields(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    await _seed(client, auth_headers, db)
    response = await client.get("/api/v1/profile/export/jsonresume", headers=auth_headers)
    assert response.status_code == 200, response.text
    resume = response.json()
    assert resume["$schema"].endswith("schema.json")
    assert resume["basics"]["name"] != ""
    assert resume["work"][0]["name"] == "Acme"
    assert resume["work"][0]["position"] == "Data intern"
    assert resume["work"][0]["highlights"] == ["Cut reporting time by 40%"]
    assert resume["education"][0]["institution"] == "Sample University"
    assert resume["education"][0]["area"] == "BSc Computer Science"

    preview = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": resume},
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    report = preview.json()
    assert report["applied"] is False
    assert report["mapped"]["work"][0]["title"] == "Data intern"
    assert report["mapped"]["education"][0]["institution"] == "Sample University"
    assert report["dropped"] == []


async def test_import_reports_unknowns_and_writes_only_on_apply(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    payload = {
        "$schema": "https://example/schema.json",
        "basics": {"name": "Ada Example", "label": "Engineer", "summary": "Hello"},
        "work": [
            {
                "name": "Globex",
                "position": "Platform Engineer",
                "startDate": "2020-02",
                "endDate": "2021-03",
                "highlights": ["Shipped a thing"],
                "type": "full-time",
            },
            {
                "name": "Initech",
                "position": "Analyst",
                "startDate": "2019-01",
                "highlights": "not-a-list",
            },
        ],
        "education": [
            {
                "institution": "Other University",
                "area": "MSc Computing",
                "studyType": "Master",
                "endDate": "2022",
                "score": "3.9",
            }
        ],
        "skills": [{"name": "Python"}],
        "unknownField": {"x": 1},
    }
    preview = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": payload},
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    report = preview.json()
    assert "unknownField" in report["dropped"]
    assert "work[0].type" in report["dropped"]
    assert report["applied"] is False
    assert "skills are reported only" in " ".join(report["warnings"])
    assert report["mapped"]["education"][0]["level"] == "master"
    assert report["mapped"]["work"][1]["achievements"] == []
    assert any(item["text"] == "not-a-list" for item in []) is False
    assert any("score kept out" in warning for warning in report["warnings"])
    assert any("highlights was not a list" in warning for warning in report["warnings"])
    assert isinstance(report["basics_conflicts"], list)

    work_before = (await client.get("/api/v1/me/experience", headers=auth_headers)).json()["items"]
    assert work_before == []

    applied = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": payload, "apply": True},
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["applied"] is True
    assert result["created"]["work"] == 2
    assert result["created"]["education"] == 1

    work_after = (await client.get("/api/v1/me/experience", headers=auth_headers)).json()["items"]
    assert {item["title"] for item in work_after} == {"Platform Engineer", "Analyst"}
    basics = (await client.get("/api/v1/profile", headers=auth_headers)).json()["basics"]
    assert basics["full_name"] == "Ada Example"
    assert basics["headline"] == "Engineer"

    again = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": payload, "apply": True},
        headers=auth_headers,
    )
    assert again.status_code == 200
    assert again.json()["created"]["work"] == 0, "repeat apply skips existing rows"
    assert again.json()["created"]["education"] == 0


async def test_import_rejects_non_objects(client, auth_headers):
    response = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": ["nope"]},
        headers=auth_headers,
    )
    assert response.status_code == 422
    bad = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": {"work": "not-a-list"}, "apply": True},
        headers=auth_headers,
    )
    assert bad.status_code == 200
    assert "work" not in bad.json()["mapped"] or bad.json()["mapped"]["work"] == []


async def test_import_reports_unmapped_study_type_and_nested_keys(
    client, auth_headers, profile_ready, seeded_catalog
):
    payload = {
        "basics": {
            "name": "Ada",
            "url": "https://ada.example",
            "location": {"city": "Athens", "address": "Somewhere 1"},
            "profiles": [{"network": "GitHub", "username": "ada", "url": "https://github.com/ada"}],
        },
        "education": [
            {
                "institution": "Diploma School",
                "studyType": "Higher National Diploma",
                "endDate": "2020",
            }
        ],
    }
    preview = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": payload},
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    report = preview.json()
    assert "basics.url" in report["dropped"]
    assert "basics.location.address" in report["dropped"]
    assert "basics.profiles[0].username" in report["dropped"]
    assert any("studyType not mapped" in warning for warning in report["warnings"])
    assert report["mapped"]["education"][0]["level"] == "high_school"


async def test_export_after_apply_includes_imported_rows(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    payload = {
        "basics": {"name": "Grace Hopper", "label": "Engineer"},
        "work": [
            {
                "name": "Navy",
                "position": "Programmer",
                "startDate": "1943-01",
                "endDate": "1946-01",
                "highlights": ["Built a compiler"],
            }
        ],
        "education": [
            {
                "institution": "Yale",
                "area": "Mathematics",
                "studyType": "PhD",
                "endDate": "1934",
            }
        ],
    }
    applied = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": payload, "apply": True},
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    exported = (await client.get("/api/v1/profile/export/jsonresume", headers=auth_headers)).json()
    assert exported["basics"]["name"] == "Grace Hopper"
    assert exported["work"][0]["position"] == "Programmer"
    assert exported["work"][0]["highlights"] == ["Built a compiler"]
    assert exported["education"][0]["institution"] == "Yale"
    assert exported["education"][0]["area"].startswith("Mathematics")

    again = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": exported, "apply": True},
        headers=auth_headers,
    )
    assert again.status_code == 200
    assert again.json()["created"]["work"] == 0
    assert again.json()["created"]["education"] == 0


async def test_import_reports_basics_and_links_conflicts(
    client, auth_headers, profile_ready, seeded_catalog
):
    existing = await client.put(
        "/api/v1/profile",
        json={
            "basics": {
                "full_name": "Old Name",
                "headline": "Old headline",
                "email": "old@example.com",
                "city": "Athens",
                "country": "GR",
                "links": [{"kind": "linkedin", "url": "https://linkedin.com/in/old", "label": ""}],
            }
        },
        headers=auth_headers,
    )
    assert existing.status_code == 200, existing.text
    incoming = {
        "basics": {
            "name": "New Name",
            "label": "New headline",
            "email": "new@example.com",
            "location": {"city": "Berlin", "countryCode": "DE"},
            "profiles": [{"network": "GitHub", "url": "https://github.com/new", "username": "new"}],
        }
    }
    preview = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": incoming},
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    conflicts = {row["field"] for row in preview.json()["basics_conflicts"]}
    assert {"full_name", "headline", "email", "city", "country", "links"} <= conflicts
    assert "basics.profiles[0].username" in preview.json()["dropped"]

    applied = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": incoming, "apply": True},
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    basics = (await client.get("/api/v1/profile", headers=auth_headers)).json()["basics"]
    assert basics["full_name"] == "New Name"
    assert basics["links"][0]["url"] == "https://github.com/new"


async def test_import_caps_collections(client, auth_headers):
    payload = {
        "work": [
            {"name": f"Org {index}", "position": "Intern", "startDate": "2024-01"}
            for index in range(120)
        ],
        "skills": [{"name": f"Skill {index}"} for index in range(250)],
    }
    response = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": payload},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert len(report["mapped"]["work"]) == 100
    assert len(report["mapped"]["skills"]) == 200
    assert any("work capped at 100" in warning for warning in report["warnings"])
    assert any("skills capped at 200" in warning for warning in report["warnings"])


async def test_import_rejects_an_oversized_resume(client, auth_headers):
    payload = {"basics": {"summary": "x" * 1_100_000}}
    response = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": payload},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_import_dedupes_within_one_payload(client, auth_headers):
    payload = {
        "work": [
            {"name": "Acme", "position": "Intern", "startDate": "2024-01"},
            {"name": "Acme", "position": "Intern", "startDate": "2024-01"},
        ]
    }
    response = await client.post(
        "/api/v1/profile/import/jsonresume",
        json={"resume": payload, "apply": True},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["created"]["work"] == 1
    assert any("already exists" in warning for warning in report["warnings"])
