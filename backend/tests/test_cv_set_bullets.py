"""cv_set_bullets HITL proposals (plan 107): grounding, apply, conflict,
revert — the chat path onto the plan-106 CV-local override layer."""

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import ValidationError
from app.models.experience_model import ExperienceItem
from app.models.user_model import User
from app.schemas.cv import CvDocumentCreate, CvDocumentUpdate
from app.services.cv_service import CvService
from app.services.experience_service import ExperienceService
from app.services.profile_proposal_service import ProfileProposalService

from tests.test_profile_proposals import _auth_user


async def _cv(db, user) -> "object":
    return await CvService(db).create(
        user.id, CvDocumentCreate(title="Target CV", kind="resume")
    )


async def _experience(db, user) -> ExperienceItem:
    return await ExperienceService(db).create_item(
        user.id,
        {
            "title": "Backend internship",
            "kind": "internship",
            "org_name": "Acme",
            "start": "2025-06-01",
            "open_ended": True,
            "achievements": [{"text": "Profile bullet one"}],
        },
    )


async def _propose_bullets(db, user, cv, item, bullets):
    return await ProfileProposalService(db).create(
        user.id,
        kind="cv_set_bullets",
        action="update",
        payload={
            "cv_id": str(cv.id),
            "source_key": "experience",
            "item_id": str(item.id),
            "bullets": bullets,
        },
    )


async def test_create_grounds_before_and_labels(db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    proposal = await _propose_bullets(db, user, cv, item, ["CV bullet A"])

    assert proposal.status == "pending"
    assert proposal.entity_id == cv.id
    assert proposal.base_updated_at is not None
    payload = proposal.payload_json
    assert payload["item_label"] == "Backend internship"
    assert payload["cv_title"] == "Target CV"
    assert payload["before"] == [{"text": "Profile bullet one"}]
    assert proposal.diff_json == [
        {"field": "removed_bullet", "from": "Profile bullet one", "to": None},
        {"field": "added_bullet", "from": None, "to": "CV bullet A"},
    ]


async def test_create_rejects_item_off_the_cv(db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    ghost = uuid.uuid4()
    with pytest.raises(ValidationError, match="context"):
        await ProfileProposalService(db).create(
            user.id,
            kind="cv_set_bullets",
            action="update",
            payload={
                "cv_id": str(cv.id),
                "source_key": "experience",
                "item_id": str(ghost),
                "bullets": ["x"],
            },
        )


async def test_apply_writes_override_entries(db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    proposal = await _propose_bullets(db, user, cv, item, ["CV bullet A"])

    _proposal, applied, _idempotent = await _approve(db, user, proposal)
    assert applied["kind"] == "cv_set_bullets"
    fresh = await CvService(db).get_owned(cv.id, user.id)
    overrides = (fresh.working_content or {}).get("overrides") or {}
    assert overrides[f"experience:{item.id}"]["achievements"] == [
        {"text": "CV bullet A"}
    ]


async def _approve(db, user, proposal):
    return await ProfileProposalService(db).approve(user.id, proposal.id)


async def test_conflict_when_cv_moved_since_proposal(db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    proposal = await _propose_bullets(db, user, cv, item, ["CV bullet A"])
    await CvService(db).update(
        cv.id,
        user.id,
        CvDocumentUpdate(working_content={"blocks": [], "overrides": {}}),
    )
    from app.core.errors import ConflictError

    with pytest.raises(ConflictError):
        await _approve(db, user, proposal)


async def test_revert_restores_the_prior_override(db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    from app.schemas.cv import CvDocumentUpdate

    await CvService(db).update(
        cv.id,
        user.id,
        CvDocumentUpdate(
            working_content={
                "blocks": [],
                "overrides": {
                    f"experience:{item.id}": {
                        "achievements": [{"text": "Earlier manual bullet"}]
                    }
                },
            }
        ),
    )
    proposal = await _propose_bullets(db, user, cv, item, ["CV bullet A"])
    await _approve(db, user, proposal)
    reverted = await ProfileProposalService(db).revert(user.id, proposal.id)

    assert reverted.status == "reverted"
    fresh = await CvService(db).get_owned(cv.id, user.id)
    overrides = (fresh.working_content or {}).get("overrides") or {}
    assert overrides[f"experience:{item.id}"]["achievements"] == [
        {"text": "Earlier manual bullet"}
    ]


async def test_revert_without_prior_override_drops_the_key(db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    proposal = await _propose_bullets(db, user, cv, item, ["CV bullet A"])
    await _approve(db, user, proposal)
    await ProfileProposalService(db).revert(user.id, proposal.id)

    fresh = await CvService(db).get_owned(cv.id, user.id)
    overrides = (fresh.working_content or {}).get("overrides") or {}
    assert f"experience:{item.id}" not in overrides
    rows = await db.execute(select(User).where(User.id == user.id))
    assert rows.scalars().one() is not None


async def test_bullets_clamped_and_extra_forbidden(db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    proposal = await _propose_bullets(db, user, cv, item, ["  spaced  ", "", "x" * 600])
    assert proposal.payload_json["bullets"] == ["spaced", "x" * 500]
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        await ProfileProposalService(db).create(
            user.id,
            kind="cv_set_bullets",
            action="update",
            payload={
                "cv_id": str(cv.id),
                "source_key": "education",
                "item_id": str(item.id),
                "bullets": ["x"],
            },
        )


async def test_read_items_and_set_bullets_tools(db, auth_headers):
    from app.ai.tools import run_tool

    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    listed = await run_tool(
        db, "cv_read_items", user.id, {"cv_id": str(cv.id)}
    )
    rows = {row["item_id"]: row for row in listed["items"]}
    row = rows[str(item.id)]
    assert row["bullets"] == ["Profile bullet one"]
    assert row["bullets_overridden_for_this_cv"] is False

    out = await run_tool(
        db,
        "cv_set_bullets",
        user.id,
        {
            "cv_id": str(cv.id),
            "source_key": "experience",
            "item_id": str(item.id),
            "bullets": ["Tailored bullet"],
        },
    )
    assert out["ok"] is True

    relisted = await run_tool(
        db, "cv_read_items", user.id, {"cv_id": str(cv.id)}
    )
    row = {r["item_id"]: r for r in relisted["items"]}[str(item.id)]
    assert row["bullets"] == ["Tailored bullet"]
    assert row["bullets_overridden_for_this_cv"] is True


def test_mock_emits_cv_set_bullets_after_the_read():
    from app.ai.mock_chat import mock_profile_ops

    ops = mock_profile_ops(
        {
            "cv_read_items": {
                "cv_id": "0b8f8d36-0000-0000-0000-000000000001",
                "items": [
                    {
                        "source_key": "experience",
                        "item_id": "e1",
                        "title": "Backend Intern",
                    }
                ],
            }
        },
        "update the bullets on this cv",
    )
    assert ops and ops[0]["kind"] == "cv_set_bullets"
    assert ops[0]["payload"]["item_id"] == "e1"
