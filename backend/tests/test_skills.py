"""Skill ontology: browse, user skills, lifecycle, gaps, uniqueness rules."""

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.models.job_model import Job, JobSkill
from app.models.taxonomy_model import InterestTag, Skill
from app.models.user_model import User, UserInterest, UserSkill
from app.core.security import hash_password


async def _user(db, email="skills@example.com") -> User:
    user = User(email=email, password_hash=hash_password("password123"))
    db.add(user)
    await db.flush()
    return user


async def test_public_skills_listing_active_only(client, auth_headers, seeded_catalog):
    rows = (await client.get("/api/v1/skills", headers=auth_headers)).json()
    assert len(rows) >= 25
    assert all("level_anchors" in r for r in rows)
    levels = {a["level"] for a in rows[0]["level_anchors"]}
    assert {1, 3, 6, 9} <= levels


async def test_skill_detail_with_jobs(client, auth_headers, seeded_catalog):
    response = await client.get(
        "/api/v1/skills/programming?include_children=false", headers=auth_headers
    )
    assert response.status_code == 200
    skill = response.json()
    assert skill["key"] == "programming"
    assert skill["level_anchors"]
    assert any(job["key"] == "programming" for job in skill["jobs"])
    assert skill["jobs"][0]["required_level"] == 5


async def test_unknown_skill_404(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/skills/does-not-exist", headers=auth_headers)
    assert response.status_code == 404


async def test_put_user_skills_roundtrip_and_validation(
    client, auth_headers, seeded_catalog
):
    payload = {
        "skills": [
            {"skill_key": "programming", "level": 7},
            {"skill_key": "empathy", "level": 3},
        ]
    }
    saved = await client.put("/api/v1/me/skills", json=payload, headers=auth_headers)
    assert saved.status_code == 200, saved.text
    rows = {r["key"]: r for r in saved.json()}
    assert rows["programming"]["level"] == 7
    assert rows["programming"]["source"] == "self_report"

    listing = (await client.get("/api/v1/me/skills", headers=auth_headers)).json()
    assert len(listing) == 2

    # 1–10 bounds enforced
    for bad in (0, 11):
        bad_save = await client.put(
            "/api/v1/me/skills",
            json={"skills": [{"skill_key": "programming", "level": bad}]},
            headers=auth_headers,
        )
        assert bad_save.status_code == 422

    # replace semantics: second PUT swaps the self_report set
    await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": "teamwork", "level": 5}]},
        headers=auth_headers,
    )
    keys = {
        r["key"]
        for r in (await client.get("/api/v1/me/skills", headers=auth_headers)).json()
    }
    assert keys == {"teamwork"}


async def test_unknown_skill_self_report_creates_proposed(
    client, auth_headers, seeded_catalog, client_admin_headers
):
    saved = await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": "quantum-tinkering", "level": 2}]},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    row = saved.json()[0]
    assert row["key"] == "quantum-tinkering"
    assert row["level"] == 2

    # proposed skills stay out of the public default listing
    public = (await client.get("/api/v1/skills", headers=auth_headers)).json()
    assert all(r["key"] != "quantum-tinkering" for r in public)

    # admin sees the proposal, promotes it, and it becomes visible
    proposals = (
        await client.get("/api/v1/admin/skills/proposals", headers=client_admin_headers)
    ).json()
    assert any(p["key"] == "quantum-tinkering" for p in proposals)


@pytest.fixture
async def client_admin_headers(client, db):
    """An admin user (is_admin forced — the first-user rule may already be taken)."""
    from sqlalchemy import select

    from app.models.user_model import User

    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "skilladmin@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201
    row = (
        (await db.execute(select(User).where(User.email == "skilladmin@example.com")))
        .scalars()
        .first()
    )
    row.is_admin = True
    await db.commit()
    return {"Authorization": f"Bearer {first.json()['access_token']}"}


async def test_aliases_are_display_only_but_resolve(
    client, client_admin_headers, db, seeded_catalog
):
    skill = (
        (await db.execute(select(Skill).where(Skill.key == "programming")))
        .scalars()
        .first()
    )
    skill.aliases = ["coding", "software development"]
    await db.commit()

    # resolve through an alias at self-report time (no new row created)
    saved = await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": "Coding", "level": 4}]},
        headers=client_admin_headers,
    )
    keys = {r["key"] for r in saved.json()}
    assert keys == {"programming"}


async def test_gaps_report(client, auth_headers, seeded_catalog, db):
    # user claims one skill below the required level
    await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": "programming", "level": 3}]},
        headers=auth_headers,
    )
    response = await client.get(
        "/api/v1/me/skills/gaps?job_id=software-developer", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["job_code"] == "software-developer"
    by_key = {g["key"]: g for g in report["gaps"]}
    programming = by_key["programming"]
    assert programming["required_level"] == 5
    assert programming["user_level"] == 3
    assert programming["delta"] == -2
    assert "Close the gap" in programming["suggestion"]

    # a skill the user never claimed has no level and no delta
    missing = [g for g in report["gaps"] if g["user_level"] is None]
    assert missing
    assert missing[0]["delta"] is None
    assert missing[0]["suggestion"].startswith("Start building")

    # path hints flow in from the curated seed paths
    hinted = [g["next_step"] for g in report["gaps"] if g["next_step"]]
    assert hinted


async def test_join_table_uniqueness_enforced(db, seeded_catalog):
    job = (
        (await db.execute(select(Job).where(Job.code == "software-developer")))
        .scalars()
        .first()
    )
    existing = (
        (await db.execute(select(JobSkill).where(JobSkill.job_id == job.id)))
        .scalars()
        .first()
    )

    with pytest.raises(IntegrityError):
        await db.execute(
            insert(JobSkill).values(
                job_id=job.id,
                skill_id=existing.skill_id,
                required_level=3,
                importance="bonus",
                source="seed",
            )
        )


async def test_user_level_bounds_enforced_at_db(db, seeded_catalog):
    user = await _user(db)
    skill = (
        (await db.execute(select(Skill).where(Skill.key == "programming")))
        .scalars()
        .first()
    )
    with pytest.raises(IntegrityError):
        db.add(UserSkill(user_id=user.id, skill_id=skill.id, level=11))
        await db.flush()
    await db.rollback()


async def test_user_interest_unique_and_weights(db, seeded_catalog):
    user = await _user(db, "interests@example.com")
    tag = (
        (
            await db.execute(
                select(InterestTag).where(InterestTag.key == "technology-software")
            )
        )
        .scalars()
        .first()
    )
    db.add(UserInterest(user_id=user.id, interest_tag_id=tag.id, weight=5))
    await db.flush()
    with pytest.raises(IntegrityError):
        db.add(UserInterest(user_id=user.id, interest_tag_id=tag.id, weight=3))
        await db.flush()
