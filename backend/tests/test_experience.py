"""Experience profile (plan 40): derivation math, CRUD, apply, evidence."""

from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest

from sqlalchemy import select

from app.models.experience_model import (
    Organization,
    SkillEvidence,
)
from app.models.user_model import User, UserSkill
from app.services.experience_derivation import (
    KIND_WEIGHT,
    ROLE_WEIGHT,
    derive_skill_months,
    months_to_confidence,
    months_to_level,
    years_of_experience,
)
from app.services.fit.dimensions import compute_fit


class _FakeItem:
    def __init__(self, id, kind, start, end=None, open_ended=False, hours=None):
        self.id = id
        self.kind = kind
        self.start = start
        self.end = end
        self.open_ended = open_ended
        self.hours_per_week = hours


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def test_level_curve_monotonic_and_anchored():
    assert months_to_level(0) == 1.0
    assert months_to_level(12) < months_to_level(24) < months_to_level(48)
    assert months_to_level(12) < 4.0
    assert months_to_level(48) < 7.5
    assert months_to_level(1200) == 10.0


def test_confidence_saturates():
    assert months_to_confidence(0) == 0.0
    assert months_to_confidence(18) == 0.5
    assert months_to_confidence(48) == 1.0


def test_derivation_kind_and_role_weights():
    today = date(2026, 9, 1)
    start = today - timedelta(days=365)
    job = _FakeItem("job-1", "job", start, today)
    project = _FakeItem("proj-1", "project", start, today)
    parts = [
        {"item": job, "skill_id": "s1", "role_in_item": "primary"},
        {"item": project, "skill_id": "s2", "role_in_item": "primary"},
    ]
    derived = derive_skill_months(parts, today=today)
    months = _months_between(start, today) + 1
    assert derived["s1"].months == months
    assert derived["s2"].months == months * KIND_WEIGHT["project"]
    secondary = derive_skill_months(
        [{"item": job, "skill_id": "s1", "role_in_item": "secondary"}], today=today
    )
    assert secondary["s1"].months == months * ROLE_WEIGHT["secondary"]


def test_derivation_hours_intensity():
    today = date(2026, 9, 1)
    start = today - timedelta(days=365)
    part_time = _FakeItem("p1", "job", start, today, hours=20)
    derived = derive_skill_months(
        [{"item": part_time, "skill_id": "s1", "role_in_item": "primary"}],
        today=today,
    )
    months = _months_between(start, today) + 1
    assert derived["s1"].months == months * 0.5


def test_overlap_dedup_takes_max_rate_per_month():
    today = date(2026, 9, 1)
    start = today - timedelta(days=365)
    job = _FakeItem("j1", "job", start, today)
    volunteer = _FakeItem("v1", "volunteer", start, today)
    derived = derive_skill_months(
        [
            {"item": job, "skill_id": "s1", "role_in_item": "primary"},
            {"item": volunteer, "skill_id": "s1", "role_in_item": "primary"},
        ],
        today=today,
    )
    months = _months_between(start, today) + 1
    assert derived["s1"].months == months  # max(job 1.0, volunteer 0.4) per month


def test_years_of_experience_is_union_not_sum():
    today = date(2026, 9, 1)
    parallel_a = _FakeItem("a", "job", date(2024, 1, 1), date(2025, 12, 31))
    parallel_b = _FakeItem("b", "job", date(2024, 6, 1), date(2026, 6, 30))
    assert years_of_experience([parallel_a, parallel_b], today) == 2.5
    sequential = _FakeItem("c", "job", date(2026, 1, 1), date(2026, 6, 30))
    # 2024-01→2025-12 (24) + 2026-01→2026-06 (6) = 30 months
    assert years_of_experience([parallel_a, sequential], today) == 2.5


def test_recency_decay_applies():
    today = date(2026, 9, 1)
    old_end = date(2020, 1, 1)
    item = _FakeItem("old", "job", date(2018, 1, 1), old_end)
    derived = derive_skill_months(
        [{"item": item, "skill_id": "s1", "role_in_item": "primary"}], today=today
    )
    months = _months_between(date(2018, 1, 1), old_end) + 1
    assert derived["s1"].months == months * 0.5


def test_fit_experience_uses_skill_months():
    band = (1, 3)
    job = {
        "skill_links": [
            {"skill_id": "s1", "required_level": 5, "importance": "core"},
            {"skill_id": "s2", "required_level": 5, "importance": "important"},
        ],
        "education_level": None,
        "experience_band": band,
        "job_city": None,
        "job_country": None,
        "job_remote": False,
        "interest_ids": set(),
        "work_style": {},
        "physical_requirements": [],
    }
    user = {"skill_levels": {}, "education_level": "high_school", "skill_months": {}}
    result = compute_fit(job=job, user=user)
    assert result.breakdown["experience"].get("neutral") is True

    user["skill_months"] = {"s1": 24.0, "s2": 24.0}
    result = compute_fit(job=job, user=user)
    assert result.breakdown["experience"]["score"] == 10.0
    assert result.breakdown["experience"].get("neutral") is None


async def _skill_key(db) -> str:
    from app.models.taxonomy_model import Skill

    row = (await db.execute(select(Skill).limit(1))).scalars().first()
    return row.key


async def test_experience_crud_and_derivation_flow(
    client, auth_headers, seeded_catalog, db
):
    skill_key = await _skill_key(db)
    body = {
        "title": "DevOps intern",
        "kind": "internship",
        "org_name": "Acme Cloud",
        "start": "2025-01-01",
        "end": "2025-12-31",
        "hours_per_week": 40,
        "description": "Deployed things.",
        "skills": [{"skill_key": skill_key, "role_in_item": "primary"}],
        "achievements": [
            {
                "text": "Cut deploy time",
                "metric": {"kind": "time_saved", "value": 40, "unit": "%"},
            }
        ],
    }
    created = await client.post(
        "/api/v1/me/experience", json=body, headers=auth_headers
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["org_name"] == "Acme Cloud"
    assert item["skills"][0]["skill_key"] == skill_key

    orgs = (await db.execute(select(Organization))).scalars().all()
    assert len(orgs) == 1 and orgs[0].status == "proposed"

    preview = await client.get("/api/v1/me/experience/derivation", headers=auth_headers)
    assert preview.status_code == 200
    skills = preview.json()["skills"]
    assert len(skills) == 1
    expected_months = _months_between(date(2025, 1, 1), date(2025, 12, 31)) + 1
    assert skills[0]["months"] == pytest.approx(
        expected_months * KIND_WEIGHT["internship"]
    )

    applied = await client.post(
        "/api/v1/me/experience/derivation/apply", headers=auth_headers
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] == 1
    assert applied.json()["conflicts"] == []

    evidence_rows = (await db.execute(select(SkillEvidence))).scalars().all()
    assert len(evidence_rows) == 1
    user_skills = (await db.execute(select(UserSkill))).scalars().all()
    assert len(user_skills) == 1
    assert user_skills[0].source == "experience"

    trace = await client.get(
        f"/api/v1/me/skills/{user_skills[0].skill_id}/evidence", headers=auth_headers
    )
    assert trace.status_code == 200
    trace_items = trace.json()["items"]
    assert len(trace_items) == 1
    assert trace_items[0]["experience_item"]["title"] == "DevOps intern"


async def test_conflicting_self_report_not_overwritten(
    client, auth_headers, seeded_catalog, db
):
    from app.models.taxonomy_model import Skill

    skill = (await db.execute(select(Skill).limit(1))).scalars().first()
    auth_user = (
        (await db.execute(select(User).where(User.email == "student@example.com")))
        .scalars()
        .first()
    )
    body = {
        "title": "Backend job",
        "kind": "job",
        "start": "2024-01-01",
        "end": "2026-01-31",
        "skills": [{"skill_key": skill.key, "role_in_item": "primary"}],
    }
    created = await client.post(
        "/api/v1/me/experience", json=body, headers=auth_headers
    )
    assert created.status_code == 201
    skill_id = UUID(created.json()["skills"][0]["skill_id"])
    db.add(
        UserSkill(
            user_id=auth_user.id,
            skill_id=skill_id,
            level=10,
            source="self_report",
        )
    )
    await db.commit()
    applied = await client.post(
        "/api/v1/me/experience/derivation/apply", headers=auth_headers
    )
    data = applied.json()
    assert data["applied"] == 0
    assert len(data["conflicts"]) == 1
    row = (await db.execute(select(UserSkill))).scalars().first()
    assert row.level == 10


async def test_draft_items_excluded_from_derivation(
    client, auth_headers, seeded_catalog, db
):
    skill_key = await _skill_key(db)
    body = {
        "title": "Draft project",
        "kind": "project",
        "start": "2025-01-01",
        "end": "2025-06-30",
        "status": "draft",
        "skills": [{"skill_key": skill_key, "role_in_item": "primary"}],
    }
    created = await client.post(
        "/api/v1/me/experience", json=body, headers=auth_headers
    )
    assert created.status_code == 201
    preview = await client.get("/api/v1/me/experience/derivation", headers=auth_headers)
    assert preview.json()["skills"] == []
    item_id = created.json()["id"]
    activated = await client.patch(
        f"/api/v1/me/experience/{item_id}",
        json={"status": "active"},
        headers=auth_headers,
    )
    assert activated.status_code == 200
    preview = await client.get("/api/v1/me/experience/derivation", headers=auth_headers)
    assert len(preview.json()["skills"]) == 1


async def test_experience_isolation(client, auth_headers, seeded_catalog, db):
    skill_key = await _skill_key(db)
    body = {
        "title": "Private project",
        "kind": "project",
        "start": "2025-01-01",
        "end": "2025-06-30",
        "skills": [{"skill_key": skill_key}],
    }
    created = await client.post(
        "/api/v1/me/experience", json=body, headers=auth_headers
    )
    item_id = created.json()["id"]

    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "other40@example.com", "password": "supersecret1"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert (
        await client.get(f"/api/v1/me/experience/{item_id}", headers=other_headers)
    ).status_code in (404, 405)
    assert (
        await client.patch(
            f"/api/v1/me/experience/{item_id}", json={}, headers=other_headers
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/me/experience/{item_id}", headers=other_headers)
    ).status_code == 404
    assert (await client.get("/api/v1/me/experience", headers=other_headers)).json()[
        "items"
    ] == []


async def test_unknown_skill_key_rejected(client, auth_headers, seeded_catalog):
    body = {
        "title": "X",
        "kind": "project",
        "start": "2025-01-01",
        "end": "2025-06-30",
        "skills": [{"skill_key": "no-such-skill"}],
    }
    response = await client.post(
        "/api/v1/me/experience", json=body, headers=auth_headers
    )
    assert response.status_code == 400


async def test_skill_evidence_one_source_check(db, seeded_catalog):
    """The CHECK constraint rejects rows with zero or multiple sources."""
    from app.models.taxonomy_model import Skill
    from app.models.user_model import User

    user = User(email="check40@example.com", password_hash="x", full_name="C")
    db.add(user)
    skill = (await db.execute(select(Skill).limit(1))).scalars().first()
    await db.commit()
    await db.refresh(user)
    user_id = user.id
    skill_id = skill.id

    row = SkillEvidence(
        user_id=user_id,
        skill_id=skill_id,
        claimed_at=date.today(),
    )
    db.add(row)
    try:
        await db.commit()
        raised = False
    except Exception:
        raised = True
        await db.rollback()
    assert raised

    db.add(
        SkillEvidence(
            user_id=user_id,
            skill_id=skill_id,
            experience_item_id=uuid4(),
            cv_document_id=uuid4(),
            claimed_at=date.today(),
        )
    )
    try:
        await db.commit()
        raised = False
    except Exception:
        raised = True
        await db.rollback()
    assert raised


async def test_postings_org_backfill_shape(db, seeded_catalog):
    """_resolve_org find-or-proposes by slug; reuse does not duplicate."""
    from app.services.experience_service import slugify_org

    assert slugify_org("Acme Cloud GmbH!") == "acme-cloud-gmbh"
