"""Career paths: curated seeds, drafts moderation, BFS graph, AI suggester."""

import pytest
from sqlalchemy import select

from app.models.career_path_model import CareerPath
from app.models.enums import RelationType
from app.models.job_model import Job, JobRelation
from app.services.job_worker import JobWorker


@pytest.fixture
async def admin_headers(client, db):
    """An admin user (is_admin forced — the first-user rule may already be taken)."""
    from sqlalchemy import select

    from app.models.user_model import User

    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "pathadmin@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201
    row = (
        (await db.execute(select(User).where(User.email == "pathadmin@example.com")))
        .scalars()
        .first()
    )
    row.is_admin = True
    await db.commit()
    return {"Authorization": f"Bearer {first.json()['access_token']}"}


@pytest.fixture
async def non_admin_headers(client, db):
    """A guaranteed non-admin user (the first registered user is admin)."""
    from sqlalchemy import select

    from app.models.user_model import User

    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "pathuser@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201
    row = (
        (await db.execute(select(User).where(User.email == "pathuser@example.com")))
        .scalars()
        .first()
    )
    row.is_admin = False
    await db.commit()
    return {"Authorization": f"Bearer {first.json()['access_token']}"}


async def test_curated_seed_paths_published(client, auth_headers, seeded_catalog):
    response = await client.get(
        "/api/v1/jobs/software-developer/paths", headers=auth_headers
    )
    assert response.status_code == 200
    paths = response.json()
    assert len(paths) >= 2
    titles = {p["title"] for p in paths}
    assert "The classic study route" in titles
    classic = next(p for p in paths if p["title"] == "The classic study route")
    kinds = [s["kind"] for s in classic["steps"]]
    assert kinds[0] == "education" and "job" in kinds
    skill_step = next(
        s for s in classic["steps"] if s.get("skill_key") == "programming"
    )
    assert skill_step["skill_label"] == "Programming"


async def test_draft_paths_hidden_from_public(
    client, non_admin_headers, admin_headers, seeded_catalog, db
):
    job = (
        (await db.execute(select(Job).where(Job.code == "data-scientist")))
        .scalars()
        .first()
    )
    db.add(CareerPath(job_id=job.id, title="Secret draft", source="ai", status="draft"))
    await db.commit()

    public = (
        await client.get("/api/v1/jobs/data-scientist/paths", headers=non_admin_headers)
    ).json()
    assert all(p["status"] == "published" for p in public)

    admin_view = (
        await client.get(
            "/api/v1/jobs/data-scientist/paths?include_drafts=true",
            headers=admin_headers,
        )
    ).json()
    assert any(p["title"] == "Secret draft" for p in admin_view)

    forbidden = await client.get(
        "/api/v1/jobs/data-scientist/paths?include_drafts=true",
        headers=non_admin_headers,
    )
    assert forbidden.status_code == 403


async def test_paths_graph_bfs_over_incoming_edges(
    client, auth_headers, seeded_catalog
):
    """nurse --leads_to--> physician, paramedic --leads_to--> nurse."""
    response = await client.get(
        "/api/v1/jobs/physician/paths/graph", headers=auth_headers
    )
    assert response.status_code == 200
    graph = response.json()
    assert graph["root"] == "physician"
    nodes = {n["code"]: n for n in graph["nodes"]}
    assert nodes["physician"]["depth"] == 0
    assert nodes["nurse"]["depth"] == 1
    assert nodes["paramedic"]["depth"] == 2
    edge = next(
        e
        for e in graph["edges"]
        if e["from_code"] == "nurse" and e["to_code"] == "physician"
    )
    assert edge["relation_type"] == "leads_to"


async def test_paths_graph_cycle_safe(client, auth_headers, seeded_catalog, db):
    """A leads_to cycle must terminate, not loop forever."""
    jobs = {
        code: jid for code, jid in (await db.execute(select(Job.code, Job.id))).all()
    }
    for src, dst in (
        ("software-developer", "data-scientist"),
        ("data-scientist", "ml-engineer"),
        ("ml-engineer", "software-developer"),
    ):
        db.add(
            JobRelation(
                from_job_id=jobs[src],
                to_job_id=jobs[dst],
                relation_type=RelationType.LEADS_TO.value,
                weight=0.5,
                source="seed",
            )
        )
    await db.commit()

    response = await client.get(
        "/api/v1/jobs/software-developer/paths/graph?depth=4", headers=auth_headers
    )
    assert response.status_code == 200
    graph = response.json()
    codes = [n["code"] for n in graph["nodes"]]
    assert len(codes) == len(set(codes))
    assert {"software-developer", "data-scientist", "ml-engineer"} <= set(codes)


async def test_ai_path_suggester_flow(
    client, non_admin_headers, admin_headers, seeded_catalog, db
):
    """Enqueue path_suggest → drafts land → admin publishes → visible."""
    enqueue = await client.post(
        "/api/v1/jobs/logistics-coordinator/paths/suggest", headers=admin_headers
    )
    assert enqueue.status_code == 202, enqueue.text
    worker = JobWorker(db)
    while await worker.run_once():
        pass

    drafts = (
        await client.get(
            "/api/v1/jobs/logistics-coordinator/paths?include_drafts=true",
            headers=admin_headers,
        )
    ).json()
    assert len(drafts) >= 1
    draft = drafts[0]
    assert draft["source"] == "ai" and draft["status"] == "draft"
    assert draft["steps"]
    for step in draft["steps"]:
        assert step["kind"] in ("education", "job", "experience", "certification")

    # non-admin cannot trigger suggestions
    forbidden = await client.post(
        "/api/v1/jobs/logistics-coordinator/paths/suggest",
        headers=non_admin_headers,
    )
    assert forbidden.status_code == 403

    # admin moderation: publish, then it is publicly visible
    published = await client.post(
        f"/api/v1/admin/paths/{draft['id']}/publish", headers=admin_headers
    )
    assert published.status_code == 200
    public = (
        await client.get(
            "/api/v1/jobs/logistics-coordinator/paths", headers=non_admin_headers
        )
    ).json()
    assert any(p["id"] == draft["id"] for p in public)

    # rejection withdraws published paths to draft instead of hard delete
    rejected = await client.post(
        f"/api/v1/admin/paths/{draft['id']}/reject", headers=admin_headers
    )
    assert rejected.status_code == 200
    after = (
        await client.get(
            "/api/v1/jobs/logistics-coordinator/paths", headers=non_admin_headers
        )
    ).json()
    assert all(p["id"] != draft["id"] for p in after)


async def test_skill_merge_rewrites_references(
    client, admin_headers, seeded_catalog, db
):
    """Merging redirects join rows + aliases; source row deprecates."""
    from app.models.taxonomy_model import Skill as SkillModel
    from app.models.user_model import UserSkill, User
    from app.models.job_model import JobSkill

    duplicate = SkillModel(
        key="software-dev-dup",
        label="Programming",
        category="technical",
        status="active",
        origin="bank",
    )
    db.add(duplicate)
    await db.flush()
    survivor = (
        (await db.execute(select(SkillModel).where(SkillModel.key == "programming")))
        .scalars()
        .first()
    )
    job = (
        (await db.execute(select(Job).where(Job.code == "software-developer")))
        .scalars()
        .first()
    )
    # give the duplicate its own link on the same job (conflict case)
    dup_link = JobSkill(
        job_id=job.id,
        skill_id=duplicate.id,
        required_level=4,
        importance="bonus",
        source="seed",
    )
    db.add(dup_link)
    user = User(email="merge@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    db.add(UserSkill(user_id=user.id, skill_id=duplicate.id, level=5))
    await db.commit()

    response = await client.post(
        f"/api/v1/admin/skills/{duplicate.id}/merge",
        json={"target_id": str(survivor.id)},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text

    refreshed = (
        (
            await db.execute(
                select(SkillModel)
                .where(SkillModel.key == "software-dev-dup")
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .first()
    )
    assert refreshed.status == "deprecated"
    survivor_after = (
        (
            await db.execute(
                select(SkillModel)
                .where(SkillModel.key == "programming")
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .first()
    )
    assert "software-dev-dup" in survivor_after.aliases

    links = (
        (await db.execute(select(JobSkill).where(JobSkill.job_id == job.id)))
        .scalars()
        .all()
    )
    assert all(row.skill_id != duplicate.id for row in links)
    assert any(row.skill_id == survivor.id for row in links)
