"""The /paths explorer: visibility, detail with marks + gaps, and the
user_path_flags marks (preferences that never touch scoring)."""

from sqlalchemy import select

from app.models.career_path_model import CareerPath, CareerPathStep, UserPathFlag
from app.models.enums import PathSource, PathStatus
from app.models.job_model import Job, JobFamily
from app.models.taxonomy_model import Skill
from tests.conftest import register_user, user_id_from_headers


async def _make_user_path(db, owner_headers: dict, *, status: str = PathStatus.ACTIVE.value):
    """A source='user' path with skill steps + the owner's path flag."""
    job = (await db.execute(select(Job))).scalars().first()
    python = (await db.execute(select(Skill))).scalars().first()
    assert job is not None and python is not None
    path = CareerPath(
        job_id=job.id,
        title="My own route",
        description="desc",
        source=PathSource.USER.value,
        status=status,
    )
    db.add(path)
    await db.flush()
    db.add(
        CareerPathStep(
            path_id=path.id,
            position=0,
            kind="skill",
            skill_id=python.id,
            label="Learn Python",
        )
    )
    await db.flush()
    db.add(
        UserPathFlag(
            user_id=user_id_from_headers(owner_headers),
            path_id=path.id,
            step_id=None,
            flag="pinned",
        )
    )
    await db.commit()
    return path, python


async def test_index_lists_published_paths(client, auth_headers, seeded_catalog):
    response = await client.get("/api/v1/paths", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert rows
    assert all(row["status"] == "published" for row in rows)
    assert all(row["job_code"] for row in rows)
    assert all(row["my_flag"] is None for row in rows)
    step = rows[0]["steps"][0]
    assert {"id", "position", "kind", "label", "parent_step_id", "edge_label"} <= set(step)


async def test_index_filters_by_job_and_family(client, db, auth_headers, seeded_catalog):
    job = (await db.execute(select(Job).where(Job.code == "software-developer"))).scalars().first()
    assert job is not None
    by_job = await client.get(f"/api/v1/paths?job={job.code}", headers=auth_headers)
    assert by_job.status_code == 200
    assert by_job.json()
    assert all(row["job_code"] == job.code for row in by_job.json())

    family = (
        (await db.execute(select(JobFamily).where(JobFamily.id == job.family_id))).scalars().first()
    )
    by_family = await client.get(f"/api/v1/paths?family={family.key}", headers=auth_headers)
    assert by_family.status_code == 200
    assert all(row["job_code"] for row in by_family.json())


async def test_user_copies_are_visible_only_to_their_owner(
    client, db, auth_headers, seeded_catalog
):
    path, _skill = await _make_user_path(db, auth_headers)
    owner = await client.get("/api/v1/paths", headers=auth_headers)
    assert [row["id"] for row in owner.json() if row["id"] == str(path.id)]
    assert owner.json()[0]["my_flag"] == "pinned"

    other = await register_user(client, "other-path@example.com")
    stranger = await client.get("/api/v1/paths", headers=other)
    assert all(row["id"] != str(path.id) for row in stranger.json())
    detail = await client.get(f"/api/v1/paths/{path.id}", headers=other)
    assert detail.status_code == 404


async def test_path_detail_reports_skill_gap_and_completeness(
    client, db, auth_headers, seeded_catalog
):
    path, python = await _make_user_path(db, auth_headers)
    await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": python.key, "level": 2}]},
        headers=auth_headers,
    )
    detail = (await client.get(f"/api/v1/paths/{path.id}", headers=auth_headers)).json()
    assert detail["title"] == "My own route"
    assert len(detail["steps"]) == 1
    step = detail["steps"][0]
    assert step["skill"]["key"] == python.key
    assert step["skill"]["user_level"] == 2
    assert detail["skills_total"] >= 1
    job_skill_level = step["skill"]["required_level"]
    threshold = job_skill_level if job_skill_level is not None else 1
    expected_met = 1 if threshold <= 2 else 0
    assert detail["skills_met"] == expected_met


async def test_flags_upsert_and_clear(client, db, auth_headers, seeded_catalog):
    path, _skill = await _make_user_path(db, auth_headers)
    detail = (await client.get(f"/api/v1/paths/{path.id}", headers=auth_headers)).json()
    step_id = detail["steps"][0]["id"]

    marked = await client.put(
        f"/api/v1/paths/{path.id}/flags",
        json={"step_id": step_id, "flag": "interested", "note": "soon"},
        headers=auth_headers,
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["steps"][0]["my_flag"] == "interested"
    assert marked.json()["steps"][0]["my_note"] == "soon"

    moved = await client.put(
        f"/api/v1/paths/{path.id}/flags",
        json={"step_id": step_id, "flag": "dismissed"},
        headers=auth_headers,
    )
    assert moved.json()["steps"][0]["my_flag"] == "dismissed"

    cleared = await client.put(
        f"/api/v1/paths/{path.id}/flags",
        json={"step_id": step_id, "flag": None},
        headers=auth_headers,
    )
    assert cleared.json()["steps"][0]["my_flag"] is None


async def test_path_level_flag_is_unique_per_user(client, db, auth_headers, seeded_catalog):
    path, _skill = await _make_user_path(db, auth_headers)
    first = await client.put(
        f"/api/v1/paths/{path.id}/flags",
        json={"flag": "interested"},
        headers=auth_headers,
    )
    assert first.status_code == 200
    second = await client.put(
        f"/api/v1/paths/{path.id}/flags",
        json={"flag": "pinned", "note": "goal"},
        headers=auth_headers,
    )
    assert second.status_code == 200
    assert second.json()["my_flag"] == "pinned"
    assert second.json()["my_note"] == "goal"


async def test_flags_on_foreign_user_path_are_rejected(client, db, auth_headers, seeded_catalog):
    path, _skill = await _make_user_path(db, auth_headers)
    other = await register_user(client, "flagger@example.com")
    denied = await client.put(
        f"/api/v1/paths/{path.id}/flags",
        json={"flag": "interested"},
        headers=other,
    )
    assert denied.status_code == 404


async def test_unknown_step_rejects_flags(client, db, auth_headers, seeded_catalog):
    path, _skill = await _make_user_path(db, auth_headers)
    from uuid import uuid4

    missing = await client.put(
        f"/api/v1/paths/{path.id}/flags",
        json={"step_id": str(uuid4()), "flag": "interested"},
        headers=auth_headers,
    )
    assert missing.status_code == 404


async def test_marks_never_change_scores(client, db, auth_headers, profile_ready, seeded_catalog):
    """Career-stages law: wall-test that path marks leave fit untouched."""
    job = (await client.get("/api/v1/jobs/software-developer", headers=auth_headers)).json()
    before = (
        await client.post("/api/v1/match/score", json={"job_id": job["id"]}, headers=auth_headers)
    ).json()[0]
    path, _skill = await _make_user_path(db, auth_headers)
    await client.put(
        f"/api/v1/paths/{path.id}/flags",
        json={"flag": "dismissed"},
        headers=auth_headers,
    )
    detail = (await client.get(f"/api/v1/paths/{path.id}", headers=auth_headers)).json()
    for step in detail["steps"]:
        await client.put(
            f"/api/v1/paths/{path.id}/flags",
            json={"step_id": step["id"], "flag": "dismissed"},
            headers=auth_headers,
        )
    after = (
        await client.post("/api/v1/match/score", json={"job_id": job["id"]}, headers=auth_headers)
    ).json()[0]
    assert after["fit_score"] == before["fit_score"]
    assert after["ai_score"] == before["ai_score"]
    assert after["prerequisites"] == before["prerequisites"]


async def test_job_paths_include_own_user_copies(client, db, auth_headers, seeded_catalog):
    path, _skill = await _make_user_path(db, auth_headers)
    job_code = (await client.get("/api/v1/paths", headers=auth_headers)).json()
    target = next(row for row in job_code if row["id"] == str(path.id))
    rows = (
        await client.get(f"/api/v1/jobs/{target['job_code']}/paths", headers=auth_headers)
    ).json()
    assert any(row["id"] == str(path.id) for row in rows)


async def test_dismissed_steps_leave_the_completeness_denominator(
    client, db, auth_headers, seeded_catalog
):
    path, _python = await _make_user_path(db, auth_headers)
    detail = (await client.get(f"/api/v1/paths/{path.id}", headers=auth_headers)).json()
    step_id = detail["steps"][0]["id"]
    before = detail["skills_total"]
    assert before >= 1
    await client.put(
        f"/api/v1/paths/{path.id}/flags",
        json={"step_id": step_id, "flag": "dismissed"},
        headers=auth_headers,
    )
    after = (await client.get(f"/api/v1/paths/{path.id}", headers=auth_headers)).json()
    assert after["skills_total"] == before - 1


async def test_family_filter_scopes_the_index(client, db, auth_headers, seeded_catalog):
    job = (await db.execute(select(Job))).scalars().first()
    family = (
        (await db.execute(select(JobFamily).where(JobFamily.id == job.family_id))).scalars().first()
    )
    rows = (await client.get(f"/api/v1/paths?family={family.key}", headers=auth_headers)).json()
    assert all(row["job_code"] for row in rows)
