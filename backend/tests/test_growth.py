"""Phase 28 growth toolkit: roadmaps, radar, resources, snapshot, quiet
hours, check-ins."""

import uuid as uuid_mod
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.connectors.base import (
    ConnectorCapabilities,
    ConnectorResult,
    PostingConnector,
    RawPosting,
)
from app.connectors.registry import register_connector, reset_registry
from app.core.security import decode_access_token
from app.models.job_model import Job
from app.models.posting_model import JobPosting
from app.models.taxonomy_model import Skill
from app.services.growth_service import (
    near_miss_radar,
)


@pytest.fixture
async def kinds(db):
    from app.seeds.run import seed_notification_kinds

    return await seed_notification_kinds(db)


def _user_id(auth_headers) -> uuid_mod.UUID:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    return decode_access_token(token)[0]


class SyntheticConnector(PostingConnector):
    key = "synthetic"
    title = "Synthetic"
    capabilities = ConnectorCapabilities(supports_incremental=True)

    def config_model(self):
        from app.connectors.base import EmptyConfig

        return EmptyConfig

    async def fetch(self, config, state, *, transport=None, **_kw):
        if state and state.get("etag"):
            return ConnectorResult(next_state=state)
        return ConnectorResult(
            postings=[
                RawPosting(
                    external_id="syn-1",
                    title="QA Automation Engineer",
                    org="SynthCo",
                    url="https://syn.example/1",
                    posted_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
                    salary_min=45000.0,
                    salary_max=65000.0,
                    salary_currency="USD",
                    skills_raw=["programming", "problem-solving"],
                    raw={"description": "programming and problem-solving"},
                )
            ],
            next_state={"etag": '"syn-etag"'},
        )


@pytest.fixture
def synthetic():
    register_connector(SyntheticConnector())
    yield
    reset_registry()


@pytest.fixture
async def source(db, synthetic):
    from app.models.posting_model import JobSource

    source = JobSource(key="synth", connector_key="synthetic", config={}, enabled=True)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def _job_by_code(db, code: str) -> Job:
    return (await db.execute(select(Job).where(Job.code == code))).scalars().first()


# --------------------------------------------------------------- roadmap


async def test_roadmap_generation_from_gaps(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    job = await _job_by_code(db, "software-developer")
    created = await client.post(
        "/api/v1/growth/plans",
        json={"target_job_id": str(job.id)},
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    plan = created.json()
    assert plan["target_job"]["code"] == "software-developer"
    assert plan["steps"], "gaps must generate steps"
    assert all(step["kind"] == "skill" for step in plan["steps"])
    assert [s["position"] for s in plan["steps"]] == list(range(len(plan["steps"])))

    duplicate = await client.post(
        "/api/v1/growth/plans",
        json={"target_job_id": str(job.id)},
        headers=auth_headers,
    )
    assert duplicate.status_code == 400


async def test_step_completion_upserts_skill_and_refits(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.models.user_model import UserSkill

    job = await _job_by_code(db, "software-developer")
    plan = (
        await client.post(
            "/api/v1/growth/plans",
            json={"target_job_id": str(job.id)},
            headers=auth_headers,
        )
    ).json()
    step = plan["steps"][0]
    assert step["skill_id"]

    done = await client.patch(
        f"/api/v1/growth/steps/{step['id']}",
        json={"status": "done", "completed_level": 6},
        headers=auth_headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["refitted"] > 0

    rows = (
        (
            await db.execute(
                select(UserSkill).where(
                    UserSkill.user_id == _user_id(auth_headers),
                    UserSkill.skill_id == uuid_mod.UUID(step["skill_id"]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].level == 6

    conflict = await client.patch(
        f"/api/v1/growth/steps/{step['id']}",
        json={"status": "done", "completed_level": 1},
        headers=auth_headers,
    )
    # Re-completing with a wild level flags a conflict, not a silent overwrite.
    refreshed = (
        (
            await db.execute(
                select(UserSkill).where(
                    UserSkill.user_id == _user_id(auth_headers),
                    UserSkill.skill_id == uuid_mod.UUID(step["skill_id"]),
                )
            )
        )
        .scalars()
        .first()
    )
    assert refreshed.level == 6 or conflict.json()["conflicts"]


async def test_plan_completes_when_steps_exhausted(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    job = await _job_by_code(db, "software-developer")
    plan = (
        await client.post(
            "/api/v1/growth/plans",
            json={"target_job_id": str(job.id)},
            headers=auth_headers,
        )
    ).json()
    for step in plan["steps"]:
        await client.patch(
            f"/api/v1/growth/steps/{step['id']}",
            json={"status": "skipped"},
            headers=auth_headers,
        )
    plans = (await client.get("/api/v1/growth/plans", headers=auth_headers)).json()
    mine = next(p for p in plans if p["id"] == plan["id"])
    assert mine["status"] == "completed"


# ----------------------------------------------------------------- radar


async def test_radar_band_and_deficit_math(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """Direct service-level check: craft an insight in the 5.5–7.5 band
    with ≤3 core deficits and confirm the radar entry math."""
    from app.models.matching_model import MatchInsight
    from app.services.fit.service import FitService

    # Get within 3 levels of the required skills (all required: 5) so
    # real small deficits exist — the radar targets the "almost there" band.
    saved = await client.put(
        "/api/v1/me/skills",
        json={
            "skills": [
                {"skill_key": "programming", "level": 3},
                {"skill_key": "problem-solving", "level": 5},
                {"skill_key": "critical-thinking", "level": 5},
            ]
        },
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text

    job = await _job_by_code(db, "software-developer")
    fit = FitService(db)
    # One mid fit write puts the job inside the band.
    from app.services.fit.dimensions import FitResult

    await fit.upsert_fit(
        _user_id(auth_headers), job, FitResult(score=6.5, breakdown={}, gates=[])
    )
    radar = await near_miss_radar(db, _user_id(auth_headers))
    entry = next((r for r in radar if r["code"] == "software-developer"), None)
    assert entry is not None
    assert 5.5 <= entry["fit_score"] <= 7.5
    assert entry["deficits"]
    assert len([d for d in entry["deficits"] if d["importance"] == "core"]) <= 3
    assert all(d["delta"] <= 3 for d in entry["deficits"])
    assert "away" in entry["headline"]

    # A gated job never appears on the radar.
    insight = (
        (
            await db.execute(
                select(MatchInsight).where(
                    MatchInsight.user_id == _user_id(auth_headers),
                    MatchInsight.job_id == job.id,
                )
            )
        )
        .scalars()
        .first()
    )
    insight.fit_breakdown = {
        "dimensions": {},
        "gates": ["physical"],
        "specialist_dimension": None,
    }
    await db.commit()
    radar_after = await near_miss_radar(db, _user_id(auth_headers))
    assert all(r["code"] != "software-developer" for r in radar_after)


# ------------------------------------------------------------- resources


async def test_resource_validation_and_moderation_flow(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().first()
    user.is_admin = True
    await db.commit()

    skill = (
        (await db.execute(select(Skill).where(Skill.key == "programming")))
        .scalars()
        .first()
    )

    insecure = await client.post(
        f"/api/v1/skills/{skill.id}/resources",
        json={"title": "X", "url": "http://insecure.example", "kind": "course"},
        headers=auth_headers,
    )
    assert insecure.status_code == 400

    created = await client.post(
        f"/api/v1/skills/{skill.id}/resources",
        json={
            "title": "Python for everyone",
            "url": "https://courses.example/py",
            "kind": "course",
            "cost": "free",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    ai_draft = await client.post(
        f"/api/v1/skills/{skill.id}/resources",
        json={
            "title": "AI-suggested book",
            "url": "https://books.example/x",
            "kind": "book",
            "source": "ai",
        },
        headers=auth_headers,
    )
    assert ai_draft.status_code == 201
    assert ai_draft.json()["status"] == "draft"

    listing = (
        await client.get(f"/api/v1/skills/{skill.id}/resources", headers=auth_headers)
    ).json()
    assert [r["title"] for r in listing] == ["Python for everyone"]


# --------------------------------------------------------------- snapshot


async def test_snapshot_thin_sample_suppression(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    from app.services.postings_service import sync_source

    await sync_source(db, source)
    snapshot = (
        await client.get(
            "/api/v1/market/snapshot?family_key=technology", headers=auth_headers
        )
    ).json()
    assert snapshot["sample_size"] == 1
    assert snapshot["thin_sample"] is True
    assert snapshot["salary_band"] is None
    assert snapshot["top_employers"][0]["org"] == "SynthCo"
    assert {"key": "programming", "count": 1} in snapshot["top_skills"]


async def test_snapshot_sufficient_sample_shows_band(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    from app.services.postings_service import sync_source

    await sync_source(db, source)
    # Inflate the sample to the threshold with direct inserts.
    base = (await db.execute(select(JobPosting))).scalars().first()
    for i in range(5):
        posting = JobPosting(
            source_id=base.source_id,
            external_id=f"bulk-{i}",
            title=f"Role {i}",
            org=f"Org{i}" if i > 0 else "SynthCo",
            location={},
            content_hash=f"hash-{i}",
            catalog_job_id=base.catalog_job_id,
            status="mapped",
            posted_at=datetime(2026, 8, 1 + i, tzinfo=timezone.utc),
            salary_min=40000 + i * 1000,
            salary_max=60000 + i * 1000,
            salary_currency="USD",
            salary_period="year",
        )
        db.add(posting)
    await db.commit()

    snapshot = (
        await client.get(
            f"/api/v1/market/snapshot?job_id={base.catalog_job_id}",
            headers=auth_headers,
        )
    ).json()
    assert snapshot["sample_size"] >= 5
    assert snapshot["thin_sample"] is False
    assert snapshot["salary_band"] is not None
    assert snapshot["salary_band"]["p25"] is not None


# ------------------------------------------------------------ quiet hours


async def test_quiet_hours_suppress_pings(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds
):
    from app.services.notification_service import NotificationService
    from app.services.fit.service import FitService
    from app.services.fit.dimensions import FitResult
    from app.services.job_service import JobService

    await client.put(
        "/api/v1/notifications/rules",
        json={
            "kind": "fit_threshold",
            "params": {"min_fit": 5, "quiet_hours": {"start": "00:00", "end": "23:59"}},
        },
        headers=auth_headers,
    )
    user_id = _user_id(auth_headers)
    job = await JobService(db).get_by_code_or_id("software-developer")
    fit = FitService(db)
    await fit.upsert_fit(user_id, job, FitResult(score=8.0, breakdown={}, gates=[]))
    assert await NotificationService(db).unread_count(user_id) == 0

    bad_window = await client.put(
        "/api/v1/notifications/rules",
        json={
            "kind": "fit_threshold",
            "params": {"min_fit": 5, "quiet_hours": {"start": "25:00", "end": "09:00"}},
        },
        headers=auth_headers,
    )
    assert bad_window.status_code == 422


# -------------------------------------------------------------- check-ins


async def test_checkin_cadence_skip_and_skill_conflicts(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    status = (await client.get("/api/v1/me/checkin", headers=auth_headers)).json()
    assert status["due"] is False
    assert status["next_at"]

    done = await client.post(
        "/api/v1/me/checkin",
        json={"stage": "experienced", "skills": {"programming": 5}},
        headers=auth_headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["applied_skills"] == 1
    assert done.json()["stage"] == "experienced"

    next_status = (await client.get("/api/v1/me/checkin", headers=auth_headers)).json()
    assert next_status["last_at"] is not None
    assert not next_status["due"]

    # Wild divergence flags a conflict instead of overwriting.
    conflict = await client.post(
        "/api/v1/me/checkin", json={"skills": {"programming": 1}}, headers=auth_headers
    )
    assert conflict.json()["conflicts"]
    assert conflict.json()["applied_skills"] == 0

    skip = await client.post(
        "/api/v1/me/checkin", json={"skipped": True}, headers=auth_headers
    )
    assert skip.status_code == 200
    after_skip = (await client.get("/api/v1/me/checkin", headers=auth_headers)).json()
    assert datetime.fromisoformat(after_skip["next_at"]) > datetime.now(timezone.utc)
