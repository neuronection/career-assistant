"""Path editing: review-first creation, fork-on-edit, branch steps,
reorder — user paths are mutable by their owner only."""

from sqlalchemy import select

from app.models.career_path_model import CareerPath, CareerPathStep
from app.models.enums import PathSource, PathStatus
from app.models.job_model import Job, JobFamily
from app.models.taxonomy_model import Skill
from tests.conftest import register_user


async def _create(client, headers, *, steps=None, title="My fork route"):
    payload = {
        "job_ref": "software-developer",
        "title": title,
        "description": "created by the test",
        "steps": steps
        or [
            {"kind": "education", "label": "School", "education_level": "high_school"},
            {"kind": "skill", "label": "Practice"},
            {
                "kind": "experience",
                "label": "Research semester",
                "parent": 1,
                "edge_label": "or: research",
            },
            {"kind": "job", "label": "Junior role"},
        ],
    }
    response = await client.post("/api/v1/paths", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_is_review_first_draft(client, db, auth_headers, seeded_catalog):
    detail = await _create(client, auth_headers)
    assert detail["source"] == "user"
    assert detail["status"] == "draft"
    assert detail["my_flag"] == "pinned"
    steps = detail["steps"]
    assert len(steps) == 4
    branch = steps[2]
    assert branch["parent_step_id"] == steps[1]["id"]
    assert branch["edge_label"] == "or: research"
    assert steps[3]["parent_step_id"] is None


async def test_activate_moves_draft_to_active(client, db, auth_headers, seeded_catalog):
    detail = await _create(client, auth_headers)
    assert detail["status"] == "draft"
    activated = await client.post(f"/api/v1/paths/{detail['id']}/activate", headers=auth_headers)
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    again = await client.post(f"/api/v1/paths/{detail['id']}/activate", headers=auth_headers)
    assert again.status_code == 409


async def test_curated_paths_are_not_mutable(client, db, auth_headers, seeded_catalog):
    rows = (
        (await db.execute(select(CareerPath).where(CareerPath.source == PathSource.SEED.value)))
        .scalars()
        .all()
    )
    assert rows, "seeded catalog should carry curated paths"
    curated = rows[0]
    first_step = (
        (
            await db.execute(
                select(CareerPathStep)
                .where(CareerPathStep.path_id == curated.id)
                .order_by(CareerPathStep.position)
            )
        )
        .scalars()
        .first()
    )
    patched = await client.patch(
        f"/api/v1/paths/{curated.id}", json={"title": "hijacked"}, headers=auth_headers
    )
    assert patched.status_code == 404
    deleted = await client.delete(f"/api/v1/paths/{curated.id}", headers=auth_headers)
    assert deleted.status_code == 404
    added = await client.post(
        f"/api/v1/paths/{curated.id}/steps",
        params={"parent_step_id": str(first_step.id)},
        json={"kind": "skill", "label": "Injected"},
        headers=auth_headers,
    )
    assert added.status_code == 404


async def test_foreign_user_path_is_not_editable(client, db, auth_headers, seeded_catalog):
    detail = await _create(client, auth_headers)
    other = await register_user(client, "other-editor@example.com")
    patched = await client.patch(
        f"/api/v1/paths/{detail['id']}", json={"title": "stolen"}, headers=other
    )
    assert patched.status_code == 404
    activated = await client.post(f"/api/v1/paths/{detail['id']}/activate", headers=other)
    assert activated.status_code == 404
    deleted = await client.delete(f"/api/v1/paths/{detail['id']}", headers=other)
    assert deleted.status_code == 404


async def test_fork_copies_branches_and_keeps_curated_intact(
    client, db, auth_headers, seeded_catalog
):
    rows = (
        (await db.execute(select(CareerPath).where(CareerPath.source == PathSource.SEED.value)))
        .scalars()
        .all()
    )
    curated = rows[0]
    before_steps = [
        (s.id, s.position, s.label)
        for s in (
            await db.execute(
                select(CareerPathStep)
                .where(CareerPathStep.path_id == curated.id)
                .order_by(CareerPathStep.position)
            )
        )
        .scalars()
        .all()
    ]
    forked = await client.post(f"/api/v1/paths/{curated.id}/fork", headers=auth_headers)
    assert forked.status_code == 201, forked.text
    copy = forked.json()
    assert copy["source"] == "user"
    assert copy["status"] == "active"
    assert copy["my_flag"] == "pinned"
    assert copy["id"] != str(curated.id)
    assert [step["label"] for step in copy["steps"]] == [label for _id, _pos, label in before_steps]

    after_steps = [
        (s.id, s.position, s.label)
        for s in (
            await db.execute(
                select(CareerPathStep)
                .where(CareerPathStep.path_id == curated.id)
                .order_by(CareerPathStep.position)
            )
        )
        .scalars()
        .all()
    ]
    assert after_steps == before_steps
    source_row = (
        (await db.execute(select(CareerPath).where(CareerPath.id == curated.id))).scalars().one()
    )
    assert source_row.source == PathSource.SEED.value

    reforked = await client.post(f"/api/v1/paths/{curated.id}/fork", headers=auth_headers)
    assert reforked.status_code == 201
    assert reforked.json()["id"] != copy["id"]


async def test_forked_copy_can_be_edited_by_its_owner(client, db, auth_headers, seeded_catalog):
    rows = (
        (await db.execute(select(CareerPath).where(CareerPath.source == PathSource.SEED.value)))
        .scalars()
        .all()
    )
    forked = (await client.post(f"/api/v1/paths/{rows[0].id}/fork", headers=auth_headers)).json()
    assert forked["steps"]
    renamed = await client.patch(
        f"/api/v1/paths/{forked['id']}",
        json={"title": "My edited route", "description": "mine now"},
        headers=auth_headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "My edited route"
    original = (
        (await db.execute(select(CareerPath).where(CareerPath.id == rows[0].id))).scalars().first()
    )
    assert original.title != "My edited route"


async def test_add_branch_step_with_edge_label(client, db, auth_headers, seeded_catalog):
    detail = await _create(client, auth_headers)
    chain = [step for step in detail["steps"] if step["parent_step_id"] is None]
    target = chain[1]
    added = await client.post(
        f"/api/v1/paths/{detail['id']}/steps",
        params={"parent_step_id": target["id"]},
        json={
            "kind": "certification",
            "label": "Certificate track",
            "edge_label": "or: cert route",
            "optional": True,
        },
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text
    steps = added.json()["steps"]
    branch = next(step for step in steps if step["label"] == "Certificate track")
    assert branch["parent_step_id"] == target["id"]
    assert branch["edge_label"] == "or: cert route"
    assert branch["optional"] is True


async def test_add_chain_step_appends(client, db, auth_headers, seeded_catalog):
    detail = await _create(client, auth_headers)
    added = await client.post(
        f"/api/v1/paths/{detail['id']}/steps",
        json={"kind": "milestone", "label": "Reach mid-level"},
        headers=auth_headers,
    )
    assert added.status_code == 201
    steps = added.json()["steps"]
    assert steps[-1]["label"] == "Reach mid-level"
    assert steps[-1]["parent_step_id"] is None


async def test_update_step_optional_and_label(client, db, auth_headers, seeded_catalog):
    detail = await _create(client, auth_headers)
    step_id = detail["steps"][0]["id"]
    updated = await client.patch(
        f"/api/v1/paths/{detail['id']}/steps/{step_id}",
        json={"optional": True, "label": "School (or equivalent)"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    step = updated.json()["steps"][0]
    assert step["optional"] is True
    assert step["label"] == "School (or equivalent)"


async def test_delete_step_cascades_branch_children(client, db, auth_headers, seeded_catalog):
    detail = await _create(client, auth_headers)
    parent = detail["steps"][1]["id"]
    deleted = await client.delete(
        f"/api/v1/paths/{detail['id']}/steps/{parent}", headers=auth_headers
    )
    assert deleted.status_code == 200
    labels = [step["label"] for step in deleted.json()["steps"]]
    assert "Practice" not in labels
    assert "Research semester" not in labels
    assert "Junior role" in labels


async def test_reorder_main_chain(client, db, auth_headers, seeded_catalog):
    detail = await _create(client, auth_headers)
    chain = [step for step in detail["steps"] if step["parent_step_id"] is None]
    assert len(chain) == 3
    reordered = [chain[2], chain[0], chain[1]]
    response = await client.post(
        f"/api/v1/paths/{detail['id']}/steps/reorder",
        json={"parent_step_id": None, "ordered": [step["id"] for step in reordered]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    labels = [step["label"] for step in response.json()["steps"]]
    assert labels == ["Junior role", "School", "Research semester", "Practice"]


async def test_reorder_rejects_partial_sets(client, db, auth_headers, seeded_catalog):
    detail = await _create(client, auth_headers)
    response = await client.post(
        f"/api/v1/paths/{detail['id']}/steps/reorder",
        json={"parent_step_id": None, "ordered": [detail["steps"][0]["id"]]},
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_unknown_skill_reference_is_rejected(client, db, auth_headers, seeded_catalog):
    response = await client.post(
        "/api/v1/paths",
        json={
            "job_ref": "software-developer",
            "title": "Bad skill",
            "steps": [{"kind": "skill", "label": "X", "skill_key": "not-a-skill"}],
        },
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_create_resolves_skill_and_family_keys(client, db, auth_headers, seeded_catalog):
    skill = (await db.execute(select(Skill))).scalars().first()
    family_key = (
        await db.execute(
            select(JobFamily.key)
            .join(Job, Job.family_id == JobFamily.id)
            .where(Job.code == "software-developer")
        )
    ).scalar_one()
    detail = await _create(
        client,
        auth_headers,
        steps=[
            {
                "kind": "skill",
                "label": "Level up",
                "skill_key": skill.key,
                "family_key": family_key,
            }
        ],
        title="Keyed route",
    )
    step = detail["steps"][0]
    assert step["skill_key"] == skill.key
    assert step["family_key"] == family_key
    index = await client.get("/api/v1/paths", headers=auth_headers)
    row = next(entry for entry in index.json() if entry["id"] == detail["id"])
    assert row["status"] == PathStatus.DRAFT.value
    assert row["source"] == PathSource.USER.value
