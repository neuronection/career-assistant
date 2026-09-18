"""HITL profile proposals (plan 77): diff correctness, idempotent resolve,
conflict/expiry lifecycle, one-apply-path parity, tenant isolation."""

import json
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


async def test_experience_update_diff_serializes_orm_rows(db, auth_headers):
    """The card diff must not render `<module.Object at 0x…>`: the
    before-side of relationship fields reads as payload-shaped dicts.
    Plan 99.2: the skills change rides collection_edits — full-replace
    update semantics are retired."""
    user = await _auth_user(db)
    item = await ExperienceService(db).create_item(
        user.id,
        {
            "title": "Neuronection",
            "kind": "project",
            "open_ended": True,
            "skills": [{"skill_key": "electron"}],
        },
    )

    added, dropped = await ProfileProposalService(db).create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
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
    assert dropped == []
    rows = {r["field"]: r for r in added[0].diff_json}
    assert [e["skill_key"] for e in rows["skills"]["before"]] == ["electron"]
    assert [e["skill_key"] for e in rows["skills"]["after"]] == [
        "electron",
        "typescript",
    ]
    assert "ExperienceSkill object" not in json.dumps(added[0].diff_json, default=str)

    # Full-replacement of a collection inside an update payload is
    # retired — it was the overwrite trap (plan 99.2).
    rejected, drop_reason = await ProfileProposalService(db).create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "payload": {"skills": ["electron", "typescript"]},
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert rejected == []
    assert drop_reason[0]["reason"].startswith("conflicting_edit")


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
        grounding={f"read:experience_item:{item.id}"},
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


async def test_experience_create_with_skill_links_applies(db, auth_headers):
    """Plan 82B: a create op can carry the linking collections the REST
    schema accepts — label-string skills normalize and apply as rows."""
    from app.models.experience_model import ExperienceSkill

    user = await _auth_user(db)
    created, dropped = await ProfileProposalService(db).create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "create",
                "payload": {
                    "title": "Neuronection platform",
                    "kind": "project",
                    "open_ended": True,
                    "skills": ["python", {"skill_key": "fastapi"}],
                    "links": ["https://github.com/example/platform"],
                },
            }
        ],
        grounding=set(),
    )
    assert dropped == []
    proposal = created[0]
    by_field = {row["field"]: row for row in proposal.diff_json}
    assert [e["skill_key"] for e in by_field["skills"]["after"]] == [
        "python",
        "fastapi",
    ]
    assert [
        (row["url"], row["kind"], row["label"]) for row in by_field["links"]["after"]
    ] == [("https://github.com/example/platform", "web", "")]

    _, applied, _ = await ProfileProposalService(db).approve(user.id, proposal.id)
    refreshed = await db.execute(
        select(ExperienceItem)
        .options(
            selectinload(ExperienceItem.skills).selectinload(ExperienceSkill.skill)
        )
        .where(ExperienceItem.id == uuid.UUID(applied["id"]))
    )
    item = refreshed.scalars().one()
    assert {link.skill.key for link in item.skills} == {"python", "fastapi"}
    assert [link["url"] for link in item.links] == [
        "https://github.com/example/platform"
    ]


async def test_experience_update_replaces_skill_list(db, auth_headers):
    """Plan 82B: update ops REPLACE the skill list in full (REST patch
    semantics) — the prompt documents this and apply honors it."""
    from app.models.experience_model import ExperienceSkill

    user = await _auth_user(db)
    item = await _experience(db, user, skills=[{"skill_key": "python"}])
    proposal = await _propose(
        db,
        user,
        action="update",
        payload={"skills": [{"skill_key": "fastapi"}]},
        entity_id=item.id,
    )
    by_field = {row["field"]: row for row in proposal.diff_json}
    assert [e["skill_key"] for e in by_field["skills"]["before"]] == ["python"]
    assert [e["skill_key"] for e in by_field["skills"]["after"]] == ["fastapi"]

    await ProfileProposalService(db).approve(user.id, proposal.id)
    refreshed = await db.execute(
        select(ExperienceItem)
        .options(
            selectinload(ExperienceItem.skills).selectinload(ExperienceSkill.skill)
        )
        .where(ExperienceItem.id == item.id)
    )
    replaced = refreshed.scalars().one()
    assert {link.skill.key for link in replaced.skills} == {"fastapi"}


async def test_mock_fixture_emits_skill_link_op(db, auth_headers):
    """Plan 82B: the mock chat fixture proposes a skill-linked create when
    the message names skills (offline tests/E2E parity for the prompt)."""
    from app.ai.mock_chat import mock_chat_reply as _mock_chat_reply

    user_prompt = "CONTEXT_JSON: " + json.dumps(
        {
            "message": "add a project with my skills",
            "tool_results": {
                "my_experience": {"items": []},
                "my_skills": {
                    "skills": [
                        {"row_id": "r1", "skill_key": "python"},
                        {"row_id": "r2", "skill_key": "docker"},
                    ]
                },
            },
        }
    )
    reply = _mock_chat_reply(object, user_prompt)
    ops = reply["profile_ops"]
    assert ops[0]["kind"] == "experience_item"
    assert [s["skill_key"] for s in ops[0]["payload"]["skills"]] == ["python", "docker"]


async def test_cv_synth_card_inline_drafts(db, auth_headers):
    """Plan 82A: an approved cv_synth card drafts library rows inline
    (≤5 refs) through the same service the Synth Library uses."""
    from app.models.cv_synth_model import CvSynthItem

    user = await _auth_user(db)
    item = await _experience(db, user)
    proposal = await _propose(
        db,
        user,
        kind="cv_synth",
        action="create",
        payload={
            "refs": [{"source_key": "experience", "item_id": str(item.id)}],
            "action": "summarize",
        },
    )
    assert proposal.status == "pending"
    assert proposal.entity_label == "Siemens internship · summarize"
    by_field = {row["field"]: row for row in proposal.diff_json}
    assert by_field["refs"]["after"] == [
        {
            "label": "Siemens internship",
            "source_key": "experience",
            "item_id": str(item.id),
        }
    ]
    assert proposal.payload_json["resolved_refs"] == by_field["refs"]["after"]

    resolved, applied, _ = await ProfileProposalService(db).approve(
        user.id, proposal.id
    )
    assert resolved.status == "approved"
    assert applied["queued"] is False
    assert len(applied["items"]) >= 1

    rows = (
        (await db.execute(select(CvSynthItem).where(CvSynthItem.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) >= 1
    assert all(row.status == "active" for row in rows)

    second = await _propose(
        db,
        user,
        kind="cv_synth",
        action="create",
        payload={
            "refs": [{"source_key": "experience", "item_id": str(item.id)}],
            "action": "summarize",
        },
    )
    await ProfileProposalService(db).approve(user.id, second.id)
    rows = (
        (await db.execute(select(CvSynthItem).where(CvSynthItem.user_id == user.id)))
        .scalars()
        .all()
    )
    assert sum(row.status == "active" for row in rows) == 1
    assert sum(row.status == "archived" for row in rows) == len(rows) - 1


async def test_cv_synth_card_queues_large_batch(db, auth_headers):
    """Plan 82A: >5 refs ride the existing cv_synth background job; the
    card is terminal BEFORE the apply (no duplicate-draft retries)."""
    from app.models.background_job_model import BackgroundJob

    user = await _auth_user(db)
    refs = [
        {"source_key": "experience", "item_id": f"00000000-0000-0000-0000-{i:012d}"}
        for i in range(6)
    ]
    proposal = await _propose(
        db,
        user,
        kind="cv_synth",
        action="create",
        payload={"refs": refs, "action": "restyle"},
    )
    resolved, applied, _ = await ProfileProposalService(db).approve(
        user.id, proposal.id
    )
    assert resolved.status == "approved"
    assert applied["queued"] is True
    assert applied["job_id"]

    jobs = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.user_id == user.id,
                    BackgroundJob.job_type == "cv_synth",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].payload["activate"] is True


async def test_cv_synth_stale_refs_fail_with_resolve_error(db, auth_headers):
    """Terminal-first: refs that no longer resolve leave an APPROVED card
    with a resolve_error — never a retryable pending one."""
    user = await _auth_user(db)
    proposal = await _propose(
        db,
        user,
        kind="cv_synth",
        action="create",
        payload={
            "refs": [
                {
                    "source_key": "experience",
                    "item_id": "00000000-0000-0000-0000-999999999999",
                }
            ],
        },
    )
    with pytest.raises(DomainError):
        await ProfileProposalService(db).approve(user.id, proposal.id)
    resolved = await ProfileProposalService(db).get(user.id, proposal.id)
    assert resolved.status == "approved"
    assert "context" in resolved.resolve_error


async def test_cv_synth_card_validates_shape(db, auth_headers):
    from pydantic import ValidationError as PydanticValidationError

    user = await _auth_user(db)
    with pytest.raises(DomainError):
        await _propose(db, user, kind="cv_synth", action="update", payload={})
    with pytest.raises(PydanticValidationError):
        await _propose(
            db,
            user,
            kind="cv_synth",
            action="create",
            payload={
                "refs": [{"source_key": "experience", "item_id": "x"}],
                "translate_of": "00000000-0000-0000-0000-000000000000",
            },
        )
    with pytest.raises(PydanticValidationError):
        await _propose(
            db,
            user,
            kind="cv_synth",
            action="create",
            payload={
                "refs": [
                    {"source_key": "experience", "item_id": str(i)} for i in range(11)
                ]
            },
        )


async def _education_row(db, user, in_progress: bool = True):
    from app.schemas.profile_entities import EducationItemIn
    from app.services.profile_entities_service import ProfileEntitiesService

    return await ProfileEntitiesService(db).create_education(
        user.id,
        EducationItemIn(
            institution="TU Munich",
            program="BSc Informatics",
            level="bachelor",
            in_progress=in_progress,
        ),
    )


async def _posting_row(db) -> object | None:
    from app.models.posting_model import JobPosting

    rows = await db.execute(select(JobPosting).limit(1))
    return rows.scalars().first()


async def test_cv_synth_card_abbreviated_multi_ref_label(db, auth_headers):
    user = await _auth_user(db)
    first = await _experience(db, user)
    second = await _experience(db, user, title="Thesis AI launcher")
    third = await _experience(db, user, title="Frame search index")
    proposal = await _propose(
        db,
        user,
        kind="cv_synth",
        action="create",
        payload={
            "refs": [
                {"source_key": "experience", "item_id": str(first.id)},
                {"source_key": "experience", "item_id": str(second.id)},
                {"source_key": "experience", "item_id": str(third.id)},
            ],
            "action": "restyle",
        },
    )
    # >2 refs abbreviate: primary label + hidden count (AD1 "≤2 labels")
    assert proposal.entity_label == "Siemens internship (+2) · restyle"
    by_field = {row["field"]: row for row in proposal.diff_json}
    assert [row["label"] for row in by_field["refs"]["after"]] == [
        "Siemens internship",
        "Thesis AI launcher",
        "Frame search index",
    ]


async def test_cv_synth_card_mixed_kinds_and_education_label(db, auth_headers):
    user = await _auth_user(db)
    item = await _experience(db, user, title="Helper building tool")
    education = await _education_row(db, user)
    proposal = await _propose(
        db,
        user,
        kind="cv_synth",
        action="create",
        payload={
            "refs": [
                {"source_key": "experience", "item_id": str(item.id)},
                {"source_key": "education", "item_id": str(education.id)},
            ],
            "action": "detail",
        },
    )
    by_field = {row["field"]: row for row in proposal.diff_json}
    assert by_field["refs"]["after"][1] == {
        "label": "BSc Informatics",
        "source_key": "education",
        "item_id": str(education.id),
    }


async def test_cv_synth_card_unknown_ref_degrades_label(db, auth_headers):
    user = await _auth_user(db)
    proposal = await _propose(
        db,
        user,
        kind="cv_synth",
        action="create",
        payload={
            "refs": [
                {
                    "source_key": "experience",
                    "item_id": "00000000-0000-0000-0000-777777777777",
                }
            ],
            "action": "summarize",
        },
    )
    assert proposal.entity_label == "Unknown item (experience) · summarize"


async def test_cv_synth_card_posting_ref_names_public_ref(db, auth_headers):
    user = await _auth_user(db)
    item = await _experience(db, user)
    posting = await _posting_row(db)
    if (
        posting is None
    ):  # postings fixtures may be empty — assert label-or-graceful only
        pytest.skip("no posting rows seeded")
    proposal = await _propose(
        db,
        user,
        kind="cv_synth",
        action="create",
        payload={
            "refs": [{"source_key": "experience", "item_id": str(item.id)}],
            "action": "posting_fit",
            "posting_id": str(posting.id),
        },
    )
    title = "Add CV variants · " + proposal.entity_label
    assert posting.ref in title
    by_field = {row["field"]: row for row in proposal.diff_json}
    assert by_field["posting_id"]["after"].startswith(str(posting.ref))


async def test_cv_synth_narration_refs_carry_labels(db, auth_headers):
    """Plan 101 AD5: the prepared_ops summary reads resolved labels —
    no raw id ever reaches the narration prompt."""
    from app.services.profile_proposal_service import (
        cv_synth_narration_refs,
        resolve_cv_synth_payload,
    )

    user = await _auth_user(db)
    item = await _experience(db, user)
    op = {
        "kind": "cv_synth",
        "action": "create",
        "payload": {"refs": [{"source_key": "experience", "item_id": str(item.id)}]},
    }
    resolved = await resolve_cv_synth_payload(db, user.id, op["payload"])
    refs = cv_synth_narration_refs(op, resolved)
    assert refs == ["Siemens internship (experience)"]
    missing = cv_synth_narration_refs(
        op,
        {
            "resolved_refs": [
                {
                    "label": "Unknown item (experience)",
                    "source_key": "experience",
                    "item_id": str(item.id),
                }
            ]
        },
    )
    assert missing == ["Unknown item (experience)"]
