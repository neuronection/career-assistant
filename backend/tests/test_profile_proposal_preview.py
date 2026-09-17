"""Plan 99.4: snapshots, the lazy preview endpoint, per-edit summary rows
and revert (inverse-apply, moved-target guard, terminal ``reverted``)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.models.experience_model import ExperienceItem, ExperienceSkill
from app.models.user_model import User
from app.services.experience_service import ExperienceService
from app.services.profile_proposal_service import (
    _REVERT_TOLERANCE,
    ProfileProposalService,
)


async def _auth_user(db) -> User:
    rows = await db.execute(
        select(User).where(User.email == settings.DEFAULT_USER_EMAIL)
    )
    return rows.scalars().one()


async def _second_user(client, db) -> User:
    email = f"pv-{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret1"},
    )
    rows = await db.execute(select(User).where(User.email == email))
    return rows.scalars().one()


async def _item(db, user, **overrides) -> ExperienceItem:
    payload = {
        "title": "Support Engineer",
        "kind": "job",
        "org_name": "Sample Logistics GmbH",
        "start": "2024-01-01",
        "end": "2024-12-31",
        "description": "Kept the warehouse systems online.",
        "skills": [{"skill_key": "python"}],
        "achievements": [{"text": "Owned monitoring", "metric": None}],
    }
    payload.update(overrides)
    return await ExperienceService(db).create_item(user.id, payload)


async def _append_proposal(
    db, user, item, text: str = "Optimized the nightly queries."
):
    created, dropped = await ProfileProposalService(db).create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "text_edits": [{"field": "description", "op": "append", "text": text}],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert dropped == []
    return created[0]


async def test_update_snapshots_draft_bullets_and_summary_rows(db, auth_headers):
    user = await _auth_user(db)
    item = await _item(db, user)
    proposal = await _append_proposal(db, user, item)

    payload = proposal.payload_json
    before = payload["base_snapshot"]
    after = payload["after_snapshot"]
    assert before["description"] == "Kept the warehouse systems online."
    assert before["title"] == "Support Engineer"
    assert after["description"] == (
        "Kept the warehouse systems online.\nOptimized the nightly queries."
    )
    assert [s["skill_key"] for s in before["skills"]] == ["python"]
    assert after["skills"] == before["skills"]

    rows = {r["field"]: r for r in proposal.diff_json}
    assert rows["edit"]["after"] == (
        "appends to description: 'Optimized the nightly queries.'"
    )
    assert "Kept the warehouse systems online." in rows["description"]["before"]
    assert "Kept the warehouse systems online." in rows["description"]["after"]

    preview = await ProfileProposalService(db).preview(user.id, proposal.id)
    assert preview["before"] == before
    assert preview["after"] == after
    assert preview["edits"]["text_edits"][0]["op"] == "append"


async def test_cross_user_preview_is_404_and_pre99_rows_404(db, client, auth_headers):
    user = await _auth_user(db)
    email = f"pv-{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecret1"}
    )
    other = (await db.execute(select(User).where(User.email == email))).scalars().one()
    from app.core.security import create_access_token

    other_headers = {
        "Authorization": f"Bearer {create_access_token(other.id, other.token_version)}"
    }

    item = await _item(db, user)
    proposal = await _append_proposal(db, user, item)
    foreign = await client.get(
        f"/api/v1/me/profile-proposals/{proposal.id}/preview", headers=other_headers
    )
    assert foreign.status_code == 404

    plain = await ProfileProposalService(db).create(
        user.id,
        kind="experience_item",
        action="update",
        payload={"hours_per_week": 12},
        entity_id=item.id,
    )
    plain.payload_json = {
        k: v
        for k, v in plain.payload_json.items()
        if k not in ("base_snapshot", "after_snapshot")
    }
    flag_modified(plain, "payload_json")
    await db.commit()
    response = await client.get(
        f"/api/v1/me/profile-proposals/{plain.id}/preview", headers=auth_headers
    )
    assert response.status_code == 404


async def test_anchored_replace_snapshot_and_preview(db, auth_headers):
    user = await _auth_user(db)
    item = await _item(db, user)
    created, dropped = await ProfileProposalService(db).create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "text_edits": [
                    {
                        "field": "description",
                        "op": "replace",
                        "find": "Kept the warehouse systems online.",
                        "text": "Ran the warehouse systems.",
                    }
                ],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert dropped == []
    payload = created[0].payload_json
    assert payload["after_snapshot"]["description"] == "Ran the warehouse systems."
    rows = {r["field"]: r for r in created[0].diff_json}
    assert rows["edit"]["after"].startswith("replaces 'Kept the warehouse")


async def test_snapshot_values_survive_2000_char_description(db, auth_headers):
    user = await _auth_user(db)
    long = "Kept things running. " * 12 + "End of original text."
    item = await _item(db, user, description=long)
    proposal = await _append_proposal(db, user, item, text="Dashboard rebuilt.")
    before = proposal.payload_json["base_snapshot"]
    assert before["description"] == long
    assert (
        proposal.payload_json["after_snapshot"]["description"]
        == long + "\nDashboard rebuilt."
    )


async def test_preview_404_for_non_snapshot_kinds(db, auth_headers):
    user = await _auth_user(db)
    service = ProfileProposalService(db)
    from app.services.skills_service import SkillService

    skill_row = await SkillService(db).upsert_user_skill(user.id, "python", 5)
    for kind, action, payload, entity_id in (
        ("user_skill", "update", {"level": 3}, skill_row.id),
        (
            "profile_section",
            "update",
            {"section": "academics", "value": {}},
            None,
        ),
        (
            "cv_synth",
            "create",
            {
                "refs": [{"source_key": "experience", "item_id": str(uuid.uuid4())}],
                "action": "summarize",
            },
            None,
        ),
    ):
        card = await service.create(
            user.id,
            kind=kind,
            action=action,
            payload=payload,
            entity_id=entity_id,
        )
        with pytest.raises(NotFoundError):
            await service.preview(user.id, card.id)


async def test_create_card_preview_after_only_and_revert(db, auth_headers):
    user = await _auth_user(db)
    service = ProfileProposalService(db)
    created, dropped = await service.create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "create",
                "payload": {
                    "title": "Sample rebuild project",
                    "kind": "project",
                    "open_ended": True,
                    "skills": [{"skill_key": "python"}],
                },
            }
        ],
        grounding=set(),
    )
    proposal = created[0]
    payload = proposal.payload_json
    assert payload["base_snapshot"] is None
    assert payload["after_snapshot"]["title"] == "Sample rebuild project"

    preview = await service.preview(user.id, proposal.id)
    assert preview["before"] is None
    assert preview["after"]["title"] == "Sample rebuild project"

    _, applied, _ = await service.approve(user.id, proposal.id)
    await db.refresh(proposal)
    assert proposal.entity_id == uuid.UUID(applied["id"])
    rows = await db.execute(
        select(ExperienceItem).where(ExperienceItem.id == proposal.entity_id)
    )
    assert rows.scalars().first() is not None

    reverted = await service.revert(user.id, proposal.id)
    await db.refresh(proposal)
    assert reverted.status == "reverted"
    rows = await db.execute(
        select(ExperienceItem).where(ExperienceItem.id == proposal.entity_id)
    )
    assert rows.scalars().first() is None

    again = await service.revert(user.id, proposal.id)
    assert again.status == "reverted"
    with pytest.raises(DomainError):
        await service.reject(user.id, proposal.id)


async def test_delete_preview_before_only_and_revert_recreates_children(
    db, auth_headers
):
    user = await _auth_user(db)
    item = await _item(db, user)
    service = ProfileProposalService(db)
    proposal = await service.create(
        user.id,
        kind="experience_item",
        action="delete",
        payload={},
        entity_id=item.id,
    )
    payload = proposal.payload_json
    assert payload["base_snapshot"] is None
    assert payload["after_snapshot"] is None

    preview = await service.preview(user.id, proposal.id)
    assert preview["after"] is None
    assert preview["before"]["description"] == "Kept the warehouse systems online."
    assert [s["skill_key"] for s in preview["before"]["skills"]] == ["python"]
    assert [a["text"] for a in preview["before"]["achievements"]] == [
        "Owned monitoring"
    ]

    await service.approve(user.id, proposal.id)
    rows = await db.execute(select(ExperienceItem).where(ExperienceItem.id == item.id))
    assert rows.scalars().first() is None

    await service.revert(user.id, proposal.id)
    await db.refresh(proposal)
    assert proposal.status == "reverted"
    rows = (
        (
            await db.execute(
                select(ExperienceItem)
                .options(
                    selectinload(ExperienceItem.skills).selectinload(
                        ExperienceSkill.skill
                    ),
                    selectinload(ExperienceItem.achievements),
                )
                .where(ExperienceItem.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    recreated = rows[0]
    assert recreated.title == "Support Engineer"
    assert recreated.description == "Kept the warehouse systems online."
    assert {link.skill.key for link in recreated.skills} == {"python"}
    assert [a.text for a in recreated.achievements] == ["Owned monitoring"]
    assert recreated.id != item.id


async def test_update_revert_restores_snapshot_and_children(db, auth_headers):
    user = await _auth_user(db)
    item = await _item(db, user)
    created, _ = await ProfileProposalService(db).create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "text_edits": [
                    {
                        "field": "description",
                        "op": "append",
                        "text": "Optimized the nightly queries.",
                    }
                ],
                "collection_edits": [
                    {
                        "collection": "skills",
                        "op": "add",
                        "value": {"skill_key": "typescript"},
                    }
                ],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    proposal = created[0]
    await ProfileProposalService(db).approve(user.id, proposal.id)

    rows = await _load(db, item.id)
    refreshed = rows[0]
    assert {link.skill.key for link in refreshed.skills} == {"python", "typescript"}

    reverted = await ProfileProposalService(db).revert(user.id, proposal.id)
    await db.refresh(proposal)
    assert reverted.status == "reverted"
    rows = await _load(db, item.id)
    restored = rows[0]
    assert restored.description == "Kept the warehouse systems online."
    assert {link.skill.key for link in restored.skills} == {"python"}
    assert restored.title == "Support Engineer"


async def _load(db, item_id):
    return (
        (
            await db.execute(
                select(ExperienceItem)
                .options(
                    selectinload(ExperienceItem.skills).selectinload(
                        ExperienceSkill.skill
                    ),
                    selectinload(ExperienceItem.achievements),
                )
                .where(ExperienceItem.id == item_id)
            )
        )
        .scalars()
        .all()
    )


async def test_revert_guard_blocks_later_edits(db, auth_headers):
    user = await _auth_user(db)
    item = await _item(db, user)
    proposal = await _append_proposal(db, user, item)
    await ProfileProposalService(db).approve(user.id, proposal.id)
    await db.refresh(proposal, ["resolve_error", "status"])

    rows = (
        (await db.execute(select(ExperienceItem).where(ExperienceItem.id == item.id)))
        .scalars()
        .one()
    )
    rows.updated_at = proposal.resolved_at + 2 * _REVERT_TOLERANCE
    db.add(rows)
    await db.commit()

    with pytest.raises(ConflictError):
        await ProfileProposalService(db).revert(user.id, proposal.id)
    await db.refresh(proposal)
    assert proposal.status == "approved"


async def test_revert_guard_tolerance_boundary(db, auth_headers):
    user = await _auth_user(db)
    item = await _item(db, user)
    proposal = await _append_proposal(db, user, item)
    await ProfileProposalService(db).approve(user.id, proposal.id)
    await db.refresh(proposal)

    rows = (
        (await db.execute(select(ExperienceItem).where(ExperienceItem.id == item.id)))
        .scalars()
        .one()
    )
    rows.updated_at = proposal.resolved_at + _REVERT_TOLERANCE
    db.add(rows)
    await db.commit()

    reverted = await ProfileProposalService(db).revert(user.id, proposal.id)
    assert reverted.status == "reverted"


async def test_revert_rejects_pending_and_non_entity_kinds(db, auth_headers):
    user = await _auth_user(db)
    service = ProfileProposalService(db)
    item = await _item(db, user)
    pending = await service.create(
        user.id,
        kind="experience_item",
        action="update",
        payload={"hours_per_week": 9},
        entity_id=item.id,
    )
    with pytest.raises(DomainError):
        await service.revert(user.id, pending.id)
    skill = await service.create(
        user.id,
        kind="user_skill",
        action="create",
        payload={"skill_key": "docker", "level": 4},
        entity_id=None,
    )
    await service.approve(user.id, skill.id)
    with pytest.raises(DomainError):
        await service.revert(user.id, skill.id)


async def test_sweep_leaves_reverted_rows(db, auth_headers):
    user = await _auth_user(db)
    service = ProfileProposalService(db)
    item = await _item(db, user)
    proposal = await _append_proposal(db, user, item)
    await service.approve(user.id, proposal.id)
    await service.revert(user.id, proposal.id)
    count = await service.sweep_expired()
    assert count == 0
    await db.refresh(proposal)
    assert proposal.status == "reverted"


async def test_api_preview_SHAPE_keyed_to_endpoint(client, db, auth_headers):
    user = await _auth_user(db)
    item = await _item(db, user)
    proposal = await _append_proposal(db, user, item)
    await ProfileProposalService(db).approve(user.id, proposal.id)
    response = await client.get(
        f"/api/v1/me/profile-proposals/{proposal.id}/preview", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["before"]["title"] == "Support Engineer"
    assert body["after"]["description"].endswith("Optimized the nightly queries.")
    assert body["edits"]["text_edits"][0]["field"] == "description"


async def test_api_revert_roundtrip(client, db, auth_headers):
    user = await _auth_user(db)
    item = await _item(db, user)
    proposal = await _append_proposal(db, user, item)
    await client.post(
        f"/api/v1/me/profile-proposals/{proposal.id}/approve", headers=auth_headers
    )
    reverted = await client.post(
        f"/api/v1/me/profile-proposals/{proposal.id}/revert", headers=auth_headers
    )
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["status"] == "reverted"
    rows = await _load(db, item.id)
    assert rows[0].description == "Kept the warehouse systems online."
