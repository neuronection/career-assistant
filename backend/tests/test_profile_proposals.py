"""HITL profile proposals (plan 77): diff correctness, idempotent resolve,
conflict/expiry lifecycle, one-apply-path parity, tenant isolation."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.models.experience_model import ExperienceItem
from app.models.profile_proposal_model import ProfileProposal
from app.models.user_model import User, UserSkill
from app.services.experience_service import ExperienceService
from app.services.profile_proposal_service import ProfileProposalService
from app.services.skills_service import SkillService


async def _auth_user(db) -> User:
    rows = await db.execute(
        select(User).where(User.email == settings.DEFAULT_USER_EMAIL)
    )
    return rows.scalars().one()


async def _second_user(client, db) -> User:
    email = f"pp-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret1"},
    )
    assert response.status_code == 201, response.text
    rows = await db.execute(select(User).where(User.email == email))
    return rows.scalars().one()


async def _experience(db, user, **overrides) -> ExperienceItem:
    payload = {
        "title": "Siemens internship",
        "kind": "internship",
        "org_name": "Siemens",
        "start": "2025-09-01",
        "open_ended": True,
    }
    payload.update(overrides)
    return await ExperienceService(db).create_item(user.id, payload)


async def _propose(
    db, user, *, kind="experience_item", action="update", payload=None, entity_id=None
) -> ProfileProposal:
    return await ProfileProposalService(db).create(
        user.id,
        kind=kind,
        action=action,
        payload=payload or {},
        entity_id=entity_id,
    )


async def test_update_proposal_diff_and_idempotent_approve(db, auth_headers):
    user = await _auth_user(db)
    item = await _experience(db, user)
    proposal = await _propose(
        db,
        user,
        action="update",
        payload={"end": "2026-06-30", "open_ended": False, "status": "draft"},
        entity_id=item.id,
    )

    assert proposal.status == "pending"
    assert proposal.base_updated_at is not None
    by_field = {row["field"]: row for row in proposal.diff_json}
    assert by_field["end"]["before"] is None
    assert by_field["end"]["after"] == "2026-06-30"
    assert by_field["open_ended"]["before"] is True
    assert by_field["status"]["after"] == "draft"

    resolved, applied, already = await ProfileProposalService(db).approve(
        user.id, proposal.id
    )
    assert already is False
    assert resolved.status == "approved"
    assert resolved.resolved_at is not None
    assert applied["id"] == str(item.id)
    assert applied["kind"] == "experience_item"

    await db.refresh(item)
    assert item.end == date(2026, 6, 30)
    assert item.open_ended is False
    assert item.status == "draft"

    again, applied2, already2 = await ProfileProposalService(db).approve(
        user.id, proposal.id
    )
    assert already2 is True
    assert applied2 is None
    assert again.status == "approved"
    await db.refresh(item)
    assert item.end == date(2026, 6, 30)


async def test_approve_conflict_when_entity_changed(db, auth_headers):
    user = await _auth_user(db)
    item = await _experience(db, user)
    proposal = await _propose(
        db, user, payload={"hours_per_week": 20}, entity_id=item.id
    )

    item.hours_per_week = 35
    db.add(item)
    await db.commit()

    with pytest.raises(ConflictError):
        await ProfileProposalService(db).approve(user.id, proposal.id)
    await db.refresh(proposal)
    assert proposal.status == "conflict"
    refreshed = {row["field"]: row for row in proposal.diff_json}
    assert refreshed["hours_per_week"]["before"] == 35
    with pytest.raises(DomainError):
        await ProfileProposalService(db).approve(user.id, proposal.id)


async def test_target_deleted_marks_expired(db, auth_headers):
    user = await _auth_user(db)
    item = await _experience(db, user)
    proposal = await _propose(
        db, user, payload={"description": "late update"}, entity_id=item.id
    )
    await ExperienceService(db).delete_item(user.id, item.id)

    with pytest.raises(NotFoundError):
        await ProfileProposalService(db).approve(user.id, proposal.id)
    await db.refresh(proposal)
    assert proposal.status == "expired"


async def test_delete_proposal_stores_snapshot(db, auth_headers):
    user = await _auth_user(db)
    item = await _experience(db, user, description="Built dashboards")
    proposal = await _propose(db, user, action="delete", entity_id=item.id)
    snapshot = proposal.payload_json["snapshot"]
    assert snapshot["title"] == "Siemens internship"
    assert snapshot["kind"] == "internship"
    assert snapshot["description"] == "Built dashboards"
    assert all(row["after"] is None for row in proposal.diff_json)

    resolved, applied, _ = await ProfileProposalService(db).approve(
        user.id, proposal.id
    )
    assert resolved.status == "approved"
    assert applied is None
    rows = await db.execute(select(ExperienceItem).where(ExperienceItem.id == item.id))
    assert rows.scalars().first() is None


async def test_user_skill_add_upserts_without_wipe(db, auth_headers):
    user = await _auth_user(db)
    await SkillService(db).put_user_skills(
        user.id, [{"skill_key": "python", "level": 5}]
    )
    proposal = await _propose(
        db,
        user,
        kind="user_skill",
        action="create",
        payload={"skill_key": "docker", "level": 4},
    )
    assert proposal.entity_label == "docker"
    diff = {row["field"]: row for row in proposal.diff_json}
    assert diff["level"]["after"] == 4

    _, applied, _ = await ProfileProposalService(db).approve(user.id, proposal.id)
    rows = await db.execute(
        select(UserSkill)
        .options(selectinload(UserSkill.skill))
        .where(UserSkill.user_id == user.id)
    )
    skills = rows.scalars().all()
    assert {s.skill.key for s in skills} == {"python", "docker"}
    docker = next(s for s in skills if s.skill.key == "docker")
    assert applied["id"] == str(docker.id)


async def test_user_skill_update_and_reject_idempotent(db, auth_headers):
    user = await _auth_user(db)
    row = await SkillService(db).upsert_user_skill(user.id, "python", 5)
    proposal = await _propose(
        db,
        user,
        kind="user_skill",
        action="update",
        payload={"level": 7},
        entity_id=row.id,
    )
    await ProfileProposalService(db).reject(user.id, proposal.id)
    await db.refresh(proposal)
    assert proposal.status == "rejected"
    await ProfileProposalService(db).reject(user.id, proposal.id)
    await db.refresh(row)
    assert row.level == 5
    with pytest.raises(DomainError):
        await ProfileProposalService(db).approve(user.id, proposal.id)


async def test_section_patch_updates_profile_with_conflict(db, auth_headers):
    user = await _auth_user(db)
    service = ProfileProposalService(db)
    proposal = await _propose(
        db,
        user,
        kind="profile_section",
        action="update",
        payload={
            "section": "academics",
            "value": {"languages": [{"code": "de", "level": "native"}]},
        },
    )
    assert proposal.entity_label == "academics"

    resolved, _, _ = await service.approve(user.id, proposal.id)
    assert resolved.status == "approved"
    from app.services.profile_service import ProfileService

    profile = await ProfileService(db).get(user.id)
    assert profile.academics["languages"] == [{"code": "de", "level": "native"}]

    conflicting = await _propose(
        db,
        user,
        kind="profile_section",
        action="update",
        payload={"section": "academics", "value": {}},
    )
    profile.academics = {"languages": [{"code": "en", "level": "native"}]}
    db.add(profile)
    await db.commit()
    with pytest.raises(ConflictError):
        await service.approve(user.id, conflicting.id)


async def test_certification_and_education_kinds_apply(db, auth_headers):
    user = await _auth_user(db)
    service = ProfileProposalService(db)
    cert = await _propose(
        db,
        user,
        kind="certification",
        action="create",
        payload={
            "name": "AWS Cloud Practitioner",
            "issuer": "Amazon",
            "issued": "2026-01-15",
        },
    )
    _, applied, _ = await service.approve(user.id, cert.id)
    assert applied["kind"] == "certification"
    assert applied["label"] == "AWS Cloud Practitioner"

    from app.schemas.profile_entities import EducationItemIn
    from app.services.profile_entities_service import ProfileEntitiesService

    education = await ProfileEntitiesService(db).create_education(
        user.id,
        EducationItemIn(
            institution="TU Munich",
            program="BSc Informatics",
            level="bachelor",
            in_progress=True,
        ),
    )
    edu_proposal = await _propose(
        db,
        user,
        kind="education_item",
        action="update",
        payload={"program": "BSc Computer Science"},
        entity_id=education.id,
    )
    await service.approve(user.id, edu_proposal.id)
    await db.refresh(education)
    assert education.program == "BSc Computer Science"


async def test_cross_user_isolation(client, db, auth_headers):
    user = await _auth_user(db)
    other = await _second_user(client, db)
    item = await _experience(db, user)
    proposal = await _propose(
        db, user, payload={"hours_per_week": 10}, entity_id=item.id
    )
    with pytest.raises(NotFoundError):
        await ProfileProposalService(db).approve(other.id, proposal.id)
    with pytest.raises(NotFoundError):
        await ProfileProposalService(db).get(other.id, proposal.id)
    assert await ProfileProposalService(db).list_(other.id) == []


async def test_create_from_ops_drops_invalid(db, auth_headers):
    user = await _auth_user(db)
    item = await _experience(db, user)
    created, dropped = await ProfileProposalService(db).create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "payload": {"hours_per_week": 12},
                "entity_id": str(item.id),
            },
            {
                "kind": "experience_item",
                "action": "update",
                "payload": {"hours_per_week": 999},
                "entity_id": str(item.id),
            },
            {
                "kind": "experience_item",
                "action": "delete",
                "payload": {},
            },
        ],
    )
    assert len(created) == 1
    assert len(dropped) == 2
    assert all("reason" in entry for entry in dropped)


async def test_sweep_expired_flips_stale_pending(db, auth_headers):
    user = await _auth_user(db)
    item = await _experience(db, user)
    proposal = await _propose(
        db, user, payload={"hours_per_week": 8}, entity_id=item.id
    )
    proposal.created_at = datetime.now(timezone.utc) - timedelta(days=20)
    db.add(proposal)
    await db.commit()

    count = await ProfileProposalService(db).sweep_expired()
    assert count >= 1
    await db.refresh(proposal)
    assert proposal.status == "expired"
    assert await ProfileProposalService(db).sweep_expired() == 0


async def test_api_list_approve_reject_dismiss(client, db, auth_headers):
    user = await _auth_user(db)
    item = await _experience(db, user)
    proposal = await _propose(
        db, user, payload={"hours_per_week": 15}, entity_id=item.id
    )

    listing = await client.get("/api/v1/me/profile-proposals", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["pending_count"] >= 1
    entry = next(p for p in body["proposals"] if p["id"] == str(proposal.id))
    assert entry["title"].startswith("Update experience · Siemens")
    assert entry["destructive"] is False
    assert entry["status"] == "pending"

    approved = await client.post(
        f"/api/v1/me/profile-proposals/{proposal.id}/approve", headers=auth_headers
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["proposal"]["status"] == "approved"
    assert approved.json()["applied"]["kind"] == "experience_item"
    await db.refresh(item)
    assert item.hours_per_week == 15

    again = await client.post(
        f"/api/v1/me/profile-proposals/{proposal.id}/approve", headers=auth_headers
    )
    assert again.status_code == 200
    assert again.json()["already"] is True

    rejectable = await _propose(
        db, user, payload={"hours_per_week": 25}, entity_id=item.id
    )
    rejected = await client.post(
        f"/api/v1/me/profile-proposals/{rejectable.id}/reject", headers=auth_headers
    )
    assert rejected.status_code == 200
    assert rejected.json()["proposal"]["status"] == "rejected"

    dismissible = await _propose(
        db, user, payload={"hours_per_week": 30}, entity_id=item.id
    )
    dismissed = await client.delete(
        f"/api/v1/me/profile-proposals/{dismissible.id}", headers=auth_headers
    )
    assert dismissed.status_code == 204
    await db.refresh(dismissible)
    assert dismissible.status == "rejected"


async def test_api_hides_cross_user(client, db, auth_headers):
    user = await _auth_user(db)
    other = await _second_user(client, db)
    item = await _experience(db, user)
    proposal = await _propose(
        db, user, payload={"hours_per_week": 5}, entity_id=item.id
    )
    rows = await db.execute(select(User).where(User.id == other.id))
    other = rows.scalars().one()
    from app.core.security import create_access_token

    other_headers = {
        "Authorization": f"Bearer {create_access_token(other.id, other.token_version)}"
    }
    foreign = await client.post(
        f"/api/v1/me/profile-proposals/{proposal.id}/approve",
        headers=other_headers,
    )
    assert foreign.status_code == 404


async def test_ops_caps_and_unknown_kind_rejected(db, auth_headers):
    user = await _auth_user(db)
    with pytest.raises(DomainError):
        await _propose(db, user, kind="inventory_item", action="create", payload={})
    with pytest.raises(DomainError):
        await _propose(
            db,
            user,
            action="update",
            payload={"hours_per_week": 5},
        )
