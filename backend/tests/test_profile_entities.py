"""— CV data entities (education, certifications, achievements)
plus the deterministic cv-readiness report. adds the universities
catalog linkage and the derived education level."""

import uuid

from sqlalchemy import select

from app.models.profile_entities_model import (
    Certification,
    EducationItem,
    ProfileAchievement,
)
from app.models.university_model import Department, University
from app.models.user_model import Profile, User
from app.services.fit.service import FitService
from app.services.profile_entities_service import effective_education_level


async def _register_second(client) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "other48@example.com", "password": "supersecret1"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_education_crud_and_ownership(client, db, auth_headers):
    created = await client.post(
        "/api/v1/me/education",
        json={
            "institution": "University of Sample",
            "program": "BSc Computer Science",
            "level": "bachelor",
            "start": "2022-09-01",
            "in_progress": True,
            "focus_subjects": ["algorithms"],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["source"] == "self_report"
    assert item["status"] == "active"

    patched = await client.patch(
        f"/api/v1/me/education/{item['id']}",
        json={"grade_band": "good", "in_progress": False, "end": "2026-06-30"},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["grade_band"] == "good"
    assert patched.json()["in_progress"] is False

    listing = await client.get("/api/v1/me/education", headers=auth_headers)
    assert [i["id"] for i in listing.json()] == [item["id"]]

    other = await _register_second(client)
    foreign = await client.patch(
        f"/api/v1/me/education/{item['id']}",
        json={"program": "stolen"},
        headers=other,
    )
    assert foreign.status_code == 404

    deleted = await client.delete(
        f"/api/v1/me/education/{item['id']}", headers=auth_headers
    )
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/me/education", headers=auth_headers)).json() == []


async def test_certifications_crud(client, db, auth_headers):
    created = await client.post(
        "/api/v1/me/certifications",
        json={
            "name": "Cambridge B2 First",
            "issuer": "Cambridge Assessment",
            "issued": "2024-03-15",
            "credential_id": "B2-123",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    item = created.json()

    patched = await client.patch(
        f"/api/v1/me/certifications/{item['id']}",
        json={"expires": "2029-03-15"},
        headers=auth_headers,
    )
    assert patched.json()["expires"] == "2029-03-15"

    listing = await client.get("/api/v1/me/certifications", headers=auth_headers)
    assert len(listing.json()) == 1
    rows = await db.execute(select(Certification))
    assert rows.scalars().first() is not None


async def test_achievements_crud_and_kind_validation(client, db, auth_headers):
    created = await client.post(
        "/api/v1/me/achievements",
        json={"kind": "award", "title": "Hackathon 1st place", "issuer": "SampleCon"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    bad = await client.post(
        "/api/v1/me/achievements",
        json={"kind": "lottery_win", "title": "X"},
        headers=auth_headers,
    )
    assert bad.status_code == 422, "kinds are a closed vocabulary"

    listing = await client.get("/api/v1/me/achievements", headers=auth_headers)
    assert listing.json()[0]["kind"] == "award"
    rows = await db.execute(select(ProfileAchievement))
    assert rows.scalars().first() is not None


async def test_cv_readiness_empty_profile(client, db, auth_headers):
    response = await client.get("/api/v1/me/cv-readiness", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == 0
    assert {s["key"] for s in body["sections"]} == {
        "contact",
        "education",
        "experience",
        "skills",
        "languages",
        "interests",
        "certifications",
        "achievements",
        "objective",
    }
    for section in body["sections"]:
        assert section["missing"], "empty profile must explain what's missing"


async def test_cv_readiness_progresses_with_data(client, db, auth_headers):
    await client.put(
        "/api/v1/profile",
        json={
            "basics": {
                "education_level": "high_school",
                "email": "jane@example.com",
                "phone": "+30 555",
                "city": "Athens",
                "headline": "Aspiring engineer",
                "links": [
                    {"kind": "github", "url": "https://github.com/jane", "label": "gh"}
                ],
            },
            "academics": {"languages": [{"code": "en", "level": "advanced"}]},
            "aspirations": [{"label": "Build an app", "tag_keys": []}],
        },
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/me/education",
        json={"institution": "Sample High", "level": "high_school"},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/me/achievements",
        json={"kind": "honor", "title": "Math olympiad"},
        headers=auth_headers,
    )

    body = (await client.get("/api/v1/me/cv-readiness", headers=auth_headers)).json()
    by_key = {s["key"]: s for s in body["sections"]}
    assert by_key["contact"]["complete"] is True
    assert by_key["education"]["complete"] is True
    assert by_key["achievements"]["complete"] is True
    assert by_key["languages"]["complete"] is True
    assert by_key["objective"]["complete"] is True
    assert body["overall"] >= 45, "contact+education+achievements+languages+objective"
    assert body["overall"] < 100, "still missing experience/skills/certs/interests"


async def test_readiness_is_deterministic(client, db, auth_headers):
    first = (await client.get("/api/v1/me/cv-readiness", headers=auth_headers)).json()
    second = (await client.get("/api/v1/me/cv-readiness", headers=auth_headers)).json()
    assert first == second, "no AI, no randomness — pure coverage math"


# ------------------------------------------------------: education


async def _student_id(db) -> uuid.UUID:
    return (
        (await db.execute(select(User).where(User.email == "student@example.com")))
        .scalars()
        .first()
    ).id


async def _seed_university(db) -> tuple[University, Department, University]:
    university = University(name="TU Sample", country="NL", city="Utrecht")
    db.add(university)
    await db.flush()
    department = Department(
        university_id=university.id, name="Computer Science", degree="master"
    )
    db.add(department)
    other = University(name="Other University", country="NL", city="Leiden")
    db.add(other)
    await db.flush()
    return university, department, other


async def test_education_level_vocabulary_enforced(client, db, auth_headers):
    created = await client.post(
        "/api/v1/me/education",
        json={"institution": "Sample U", "level": "quantum_alchemy"},
        headers=auth_headers,
    )
    assert created.status_code == 422, created.text
    ok = await client.post(
        "/api/v1/me/education",
        json={"institution": "Sample U", "level": "doctorate"},
        headers=auth_headers,
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["level"] == "doctorate"


async def test_education_catalog_linkage(client, db, auth_headers):
    university, department, other = await _seed_university(db)

    created = await client.post(
        "/api/v1/me/education",
        json={
            "institution": "TU Sample",
            "program": "MSc Computer Science",
            "level": "master",
            "in_progress": True,
            "university_id": str(university.id),
            "department_id": str(department.id),
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["university_id"] == str(university.id)
    assert item["department_id"] == str(department.id)

    # department-only create resolves the university automatically
    dept_only = await client.post(
        "/api/v1/me/education",
        json={
            "institution": "TU Sample",
            "level": "bachelor",
            "department_id": str(department.id),
        },
        headers=auth_headers,
    )
    assert dept_only.status_code == 201, dept_only.text
    assert dept_only.json()["university_id"] == str(university.id)

    # department of another university is rejected
    mismatch = await client.post(
        "/api/v1/me/education",
        json={
            "institution": "Other University",
            "level": "bachelor",
            "university_id": str(other.id),
            "department_id": str(department.id),
        },
        headers=auth_headers,
    )
    assert mismatch.status_code == 400, mismatch.text

    unknown = await client.post(
        "/api/v1/me/education",
        json={
            "institution": "Ghost U",
            "level": "bachelor",
            "university_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert unknown.status_code == 404, unknown.text

    # swapping the department onto another university on update is rejected
    swapped = await client.patch(
        f"/api/v1/me/education/{item['id']}",
        json={"university_id": str(other.id)},
        headers=auth_headers,
    )
    assert swapped.status_code == 400, swapped.text

    # explicit null clears the department but keeps the university
    cleared = await client.patch(
        f"/api/v1/me/education/{item['id']}",
        json={"department_id": None},
        headers=auth_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["department_id"] is None
    assert cleared.json()["university_id"] == str(university.id)


async def test_education_catalog_fk_set_null(client, db, auth_headers):
    university, department, _other = await _seed_university(db)
    created = await client.post(
        "/api/v1/me/education",
        json={
            "institution": "TU Sample",
            "level": "master",
            "university_id": str(university.id),
            "department_id": str(department.id),
        },
        headers=auth_headers,
    )
    item_id = created.json()["id"]

    uni_row = await db.get(University, university.id)
    await db.delete(uni_row)
    await db.commit()

    listing = (await client.get("/api/v1/me/education", headers=auth_headers)).json()
    item = next(i for i in listing if i["id"] == item_id)
    assert item["university_id"] is None
    assert item["department_id"] is None
    assert item["institution"] == "TU Sample", "free text survives"


async def test_effective_education_level_derivation(client, db, auth_headers):
    user_id = await _student_id(db)
    assert await effective_education_level(db, user_id, None) == "high_school"

    # basics-only fallback semantics are preserved
    assert await effective_education_level(db, user_id, "vocational") == "vocational"

    await client.post(
        "/api/v1/me/education",
        json={"institution": "Sample U", "level": "bachelor"},
        headers=auth_headers,
    )
    # items beat a lower basics select
    assert await effective_education_level(db, user_id, "high_school") == "bachelor"

    master = await client.post(
        "/api/v1/me/education",
        json={
            "institution": "Sample U",
            "level": "master",
            "in_progress": True,
        },
        headers=auth_headers,
    )
    # in-progress counts — order-based, not completion-based
    assert await effective_education_level(db, user_id, "high_school") == "master"

    # draft items don't count
    await client.patch(
        f"/api/v1/me/education/{master.json()['id']}",
        json={"status": "draft"},
        headers=auth_headers,
    )
    assert await effective_education_level(db, user_id, "high_school") == "bachelor"

    # legacy/unknown item levels (e.g. old intake rows) are ignored
    db.add(
        EducationItem(
            user_id=user_id,
            institution="Legacy Academy",
            level="quantum_alchemy",
            status="active",
        )
    )
    await db.commit()
    assert await effective_education_level(db, user_id, None) == "bachelor"


async def test_fit_uses_derived_education_level(client, db, auth_headers):
    user_id = await _student_id(db)
    await client.put(
        "/api/v1/profile",
        json={"basics": {"education_level": "high_school"}},
        headers=auth_headers,
    )
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id)))
        .scalars()
        .first()
    )
    context = await FitService(db).user_context(profile)
    assert context["education_level"] == "high_school"

    await client.post(
        "/api/v1/me/education",
        json={"institution": "Sample U", "level": "master", "in_progress": True},
        headers=auth_headers,
    )
    context = await FitService(db).user_context(profile)
    assert context["education_level"] == "master"


async def test_certification_language_link_validation(client, db, auth_headers):
    response = await client.post(
        "/api/v1/me/certifications",
        json={"name": "Quest 3 Certificate", "issuer": "Anywhere"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    cert = response.json()

    good = await client.patch(
        f"/api/v1/me/certifications/{cert['id']}",
        json={"language_code": "EN"},
        headers=auth_headers,
    )
    assert good.status_code == 200, good.text
    assert good.json()["language_code"] == "en", "codes normalize to lowercase"

    bad = await client.patch(
        f"/api/v1/me/certifications/{cert['id']}",
        json={"language_code": "klingon"},
        headers=auth_headers,
    )
    assert bad.status_code == 422

    clear = await client.patch(
        f"/api/v1/me/certifications/{cert['id']}",
        json={"language_code": None},
        headers=auth_headers,
    )
    assert clear.status_code == 200 and clear.json()["language_code"] is None
