"""Taxonomy work-queue stats — one aggregation behind the stats bar (plan 161)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.career_path_model import CareerPath
from app.models.enums.taxonomy import SkillRelationType, SkillStatus
from app.models.job_model import Job
from app.models.localization_model import LabelOverride
from app.models.taxonomy_model import Skill, SkillChange, SkillRelation
from tests.conftest import session_headers


@pytest.fixture
async def _admin_and_user(client):
    """First user = admin, second = regular. Returns (admin_headers, user_headers)."""
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "stats-admin@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201
    admin = session_headers(first)
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "stats-user@example.com", "password": "supersecret1"},
    )
    assert second.status_code == 201
    return admin, session_headers(second)


async def _stats(client, headers) -> dict:
    response = await client.get("/api/v1/admin/taxonomy/stats", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_taxonomy_stats_requires_auth(client):
    assert (await client.get("/api/v1/admin/taxonomy/stats")).status_code == 401


@pytest.mark.contract  # §18.7 — non-admin on an admin surface ⇒ 403
async def test_taxonomy_stats_requires_admin(client, _admin_and_user):
    _, user = _admin_and_user
    denied = await client.get("/api/v1/admin/taxonomy/stats", headers=user)
    assert denied.status_code == 403


async def test_taxonomy_stats_shape_and_queue_math(client, _admin_and_user, db, seeded_catalog):
    admin, _ = _admin_and_user
    stats = await _stats(client, admin)

    assert set(stats) == {"skills", "queue"}
    assert set(stats["skills"]) == {
        "total",
        "active",
        "proposed",
        "deprecated",
        "auto_promoted",
        "promoted_7d",
    }
    assert set(stats["queue"]) == {
        "relations",
        "enrichment",
        "job_proposals",
        "paths",
        "translations",
        "total",
    }
    assert all(isinstance(value, int) and value >= 0 for value in stats["skills"].values())
    assert all(isinstance(value, int) and value >= 0 for value in stats["queue"].values())

    skill_total = sum(stats["skills"][key] for key in ("active", "proposed", "deprecated"))
    if skill_total == stats["skills"]["total"]:  # the vocabulary is the whole table
        assert skill_total == stats["skills"]["total"]
    queue_parts = sum(
        stats["queue"][key]
        for key in ("relations", "enrichment", "job_proposals", "paths", "translations")
    )
    assert queue_parts == stats["queue"]["total"]


async def test_taxonomy_stats_counts_skills_by_status(client, _admin_and_user, db, seeded_catalog):
    admin, _ = _admin_and_user
    before = await _stats(client, admin)
    baseline = before["skills"]

    db.add_all(
        [
            Skill(key="stats-proposed", label="Stats proposed", category="test"),
            Skill(
                key="stats-deprecated",
                label="Stats deprecated",
                category="test",
                status=SkillStatus.DEPRECATED.value,
            ),
        ]
    )
    await db.flush()
    proposed = (
        (await db.execute(select(Skill).where(Skill.key == "stats-proposed"))).scalars().one()
    )
    proposed.status = SkillStatus.PROPOSED.value
    await db.flush()

    after = await _stats(client, admin)
    skills = after["skills"]
    assert skills["total"] == baseline["total"] + 2
    assert skills["proposed"] == baseline["proposed"] + 1
    assert skills["deprecated"] == baseline["deprecated"] + 1
    assert skills["active"] == baseline["active"]


async def test_taxonomy_stats_journals_promotions(client, _admin_and_user, db, seeded_catalog):
    admin, _ = _admin_and_user
    skill = Skill(key="stats-promote", label="Stats promote", category="test")
    db.add(skill)
    await db.flush()
    skill.status = SkillStatus.PROPOSED.value
    await db.flush()
    skill_id = skill.id

    before = await _stats(client, admin)

    promoted = await client.post(f"/api/v1/admin/skills/{skill_id}/promote", headers=admin)
    assert promoted.status_code == 200, promoted.text

    after = await _stats(client, admin)
    assert after["skills"]["proposed"] == before["skills"]["proposed"] - 1
    assert after["skills"]["active"] == before["skills"]["active"] + 1
    assert after["skills"]["promoted_7d"] == before["skills"]["promoted_7d"] + 1

    db.add(
        SkillChange(
            skill_key="stats-old",
            skill_label="Stats old",
            event="promoted",
            actor_kind="admin",
            occurred_at=datetime.now(UTC) - timedelta(days=30),
        )
    )
    await db.flush()

    stale = await _stats(client, admin)
    assert stale["skills"]["promoted_7d"] == after["skills"]["promoted_7d"]


async def test_taxonomy_stats_ignores_rejected_enrichment(
    client, _admin_and_user, db, seeded_catalog
):
    """A discarded proposal stores JSON null under the same key — presence
    is not aliveness (the PostgreSQL/SQLite divergence trap)."""
    admin, _ = _admin_and_user
    job = (await db.execute(select(Job).where(Job.status == "published"))).scalars().first()
    before = await _stats(client, admin)

    job.ai_metadata = {
        "enrichment_proposal": None,
        "enrichment_rejected_at": "2026-10-30T00:00:00Z",
    }
    await db.flush()

    after = await _stats(client, admin)
    assert after["queue"]["enrichment"] == before["queue"]["enrichment"]


async def test_taxonomy_stats_counts_the_review_queues(client, _admin_and_user, db, seeded_catalog):
    admin, _ = _admin_and_user
    job = (await db.execute(select(Job).where(Job.status == "published"))).scalars().first()
    assert job is not None
    skills = (await db.execute(select(Skill).order_by(Skill.key).limit(2))).scalars().all()
    assert len(skills) == 2
    low, high = sorted((skills[0].id, skills[1].id), key=str)

    job.ai_metadata = {"enrichment_proposal": {"contract_type": "full_time"}}
    db.add_all(
        [
            CareerPath(job_id=job.id, title="Stats draft path"),
            SkillRelation(
                from_skill_id=low,
                to_skill_id=high,
                relation=SkillRelationType.SYNONYM.value,
                source="llm",
            ),
            LabelOverride(
                entity_kind="skill",
                entity_id=skills[0].id,
                locale="de",
                field="label",
                value="Statistik",
                source="human",
            ),
        ]
    )
    await db.flush()

    stats = await _stats(client, admin)
    assert stats["queue"]["enrichment"] >= 1
    assert stats["queue"]["paths"] >= 1
    assert stats["queue"]["relations"] >= 1
    assert stats["queue"]["translations"] >= 1
    assert stats["queue"]["total"] == sum(
        stats["queue"][key] for key in ("relations", "enrichment", "paths", "translations")
    )
