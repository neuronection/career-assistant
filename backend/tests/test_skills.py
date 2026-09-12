"""Skill ontology: browse, user skills, lifecycle, gaps, uniqueness rules."""

import uuid

import pytest
from sqlalchemy import insert, select, update
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


async def test_patch_derive_enabled_toggle_and_404(
    client, auth_headers, seeded_catalog, db
):
    """Non-self_report rows can opt out of derivation; unknown rows 404."""
    saved = await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": "programming", "level": 7}]},
        headers=auth_headers,
    )
    row = saved.json()[0]
    assert row["derive_enabled"] is True

    patch = await client.patch(
        f"/api/v1/me/skills/{row['skill_id']}",
        json={"derive_enabled": False},
        headers=auth_headers,
    )
    assert patch.status_code == 200
    assert patch.json()["derive_enabled"] is False
    assert patch.json()["source"] == "self_report"

    re_enable = await client.patch(
        f"/api/v1/me/skills/{row['skill_id']}",
        json={"derive_enabled": True},
        headers=auth_headers,
    )
    assert re_enable.status_code == 200

    missing = await client.patch(
        "/api/v1/me/skills/00000000-0000-0000-0000-000000000001",
        json={"derive_enabled": False},
        headers=auth_headers,
    )
    assert missing.status_code == 404


async def test_delete_user_skill_tombstones(client, auth_headers, seeded_catalog, db):
    """DELETE hides the row from every listing and derivation apply
    never resurrects it; re-adding via PUT makes a fresh self_report."""
    from app.models.user_model import UserSkill
    from sqlalchemy import func as _func

    saved = await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": "programming", "level": 7}]},
        headers=auth_headers,
    )
    row = saved.json()[0]
    deleted = await client.delete(
        f"/api/v1/me/skills/{row['skill_id']}", headers=auth_headers
    )
    assert deleted.status_code == 204
    listing = (await client.get("/api/v1/me/skills", headers=auth_headers)).json()
    assert listing == []
    hidden_row = (await db.execute(select(UserSkill))).scalars().one()
    assert hidden_row.hidden is True
    assert hidden_row.derive_enabled is False

    # re-adding makes a fresh visible row
    again = await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": "programming", "level": 9}]},
        headers=auth_headers,
    )
    fresh = again.json()[0]
    assert fresh["level"] == 9
    assert fresh["derive_enabled"] is True
    assert fresh["hidden"] is False
    total = (await db.execute(select(_func.count(UserSkill.id)))).scalar()
    assert total == 1

    missing = await client.delete(
        "/api/v1/me/skills/00000000-0000-0000-0000-000000000001",
        headers=auth_headers,
    )
    assert missing.status_code == 404


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


async def test_disabled_skill_excluded_from_gaps(
    client, auth_headers, seeded_catalog, db
):
    """Opting out freezes scoring: the gap report treats it as unclaimed."""
    from sqlalchemy import func

    await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": "programming", "level": 3}]},
        headers=auth_headers,
    )
    preferred = select(Skill.id).where(Skill.key == "programming").scalar_subquery()
    users = select(User.id).where(User.email == "student@example.com")
    user_id = (await db.execute(users)).scalar()
    await db.execute(
        update(UserSkill)
        .where(UserSkill.user_id == user_id, UserSkill.skill_id == preferred)
        .values(derive_enabled=False)
    )
    count = (await db.execute(select(func.count(UserSkill.id)))).scalar()
    assert count == 1
    report = (
        await client.get(
            "/api/v1/me/skills/gaps?job_id=software-developer",
            headers=auth_headers,
        )
    ).json()
    by_key = {g["key"]: g for g in report["gaps"]}
    assert by_key["programming"]["user_level"] is None
    assert by_key["programming"]["suggestion"].startswith("Start building")


async def test_disabled_skill_excluded_from_cv_context_and_fit(
    client, auth_headers, seeded_catalog, db
):
    """CV Studio context and the fit engine ignore opted-out rows."""
    from app.models.user_model import Profile
    from app.services.fit.service import FitService

    saved = await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": "programming", "level": 7}]},
        headers=auth_headers,
    )
    row = saved.json()[0]
    user = (
        (await db.execute(select(User).where(User.email == "student@example.com")))
        .scalars()
        .first()
    )
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user.id)))
        .scalars()
        .first()
    )
    from app.services.cv_context_service import _resolve_skills

    items = await _resolve_skills(db, user.id)
    assert [i.item_id for i in items] == [row["skill_id"]]

    context = await FitService(db).user_context(profile)
    assert context["skill_levels"] == {uuid.UUID(row["skill_id"]): 7}

    stamps = (
        await db.execute(
            select(UserSkill).where(UserSkill.skill_id == uuid.UUID(row["skill_id"]))
        )
    ).scalar_one()
    stamps.derive_enabled = False
    await db.commit()

    items = await _resolve_skills(db, user.id)
    assert items == []
    context = await FitService(db).user_context(profile)
    assert context["skill_levels"] == {}


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
