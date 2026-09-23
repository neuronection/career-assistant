"""cv_set_bullets HITL proposals (plan 107): grounding, apply, conflict,
revert — the chat path onto the two-layer bullets model (a bullets
variant pinned on the CV via the single synth-pin slot (plan 110))."""

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import ValidationError
from app.models.cv_synth_model import CvSynthItem
from app.models.experience_model import ExperienceItem
from app.models.user_model import User
from app.schemas.cv import CvDocumentCreate
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


async def test_resolver_tolerates_a_stray_entity_id(db, auth_headers):
    """Models echo an entity_id on cv_set_bullets ops even though the
    identity rides the payload (cv_id / source_key / item_id) — the
    resolver must clamp it, not drop the card."""
    from app.services.profile_proposal_service import resolve_ops

    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    resolved, failures = await resolve_ops(
        db,
        user.id,
        [
            {
                "kind": "cv_set_bullets",
                "action": "update",
                "entity_id": str(item.id),
                "payload": {
                    "cv_id": str(cv.id),
                    "source_key": "experience",
                    "item_id": str(item.id),
                    "bullets": ["CV bullet A"],
                },
            }
        ],
        grounding=set(),
    )
    assert not failures
    assert len(resolved) == 1
    assert resolved[0]["entity_id"] is None


async def test_create_strips_echoed_heading_from_proposed_bullets(db, auth_headers):
    """Bullets must not reopen with the item's heading (title/org render
    above them): an echo lead is cut deterministically, an echo-only
    bullet is dropped."""
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    proposal = await _propose_bullets(
        db,
        user,
        cv,
        item,
        [
            "Backend internship — resolved stencil tickets",
            "Backend internship, Acme — triaged queues",
            "Backend internship",  # echo-only → dropped
            "Migrated the staging vault",  # no echo → untouched
        ],
    )
    assert proposal.payload_json["bullets"] == [
        "resolved stencil tickets",
        "triaged queues",
        "Migrated the staging vault",
    ]
    assert proposal.diff_json[0]["after"] == [
        {"text": "resolved stencil tickets"},
        {"text": "triaged queues"},
        {"text": "Migrated the staging vault"},
    ]


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
        {
            "field": "bullets",
            "label": "Bullets",
            "before": [{"text": "Profile bullet one"}],
            "after": [{"text": "CV bullet A"}],
        }
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


async def test_apply_writes_a_bullets_variant_and_pins_it(db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    proposal = await _propose_bullets(db, user, cv, item, ["CV bullet A"])

    _proposal, applied, _idempotent = await _approve(db, user, proposal)
    assert applied["kind"] == "cv_set_bullets"
    fresh = await CvService(db).get_owned(cv.id, user.id)
    pins = (fresh.context or {}).get("synth_pins") or {}
    variant_id = pins[f"experience:{item.id}"]
    variant = await db.get(CvSynthItem, uuid.UUID(variant_id))
    assert variant.scope == "bullets"
    assert variant.payload["achievements"] == [{"text": "CV bullet A"}]


async def _approve(db, user, proposal):
    return await ProfileProposalService(db).approve(user.id, proposal.id)


async def test_conflict_when_the_item_moved_since_proposal(db, auth_headers):
    """The granular sentinel: the conflict fires when the target item's
    own bullet state moved (edited achievements, repinned variant) —
    an unrelated CV mutation must not poison the card (each approval
    rewrites cv.context pins and bumps the CV's timestamp)."""
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    other = await ExperienceService(db).create_item(
        user.id,
        {
            "title": "Second internship",
            "kind": "internship",
            "org_name": "Beta",
            "start": "2025-07-01",
            "open_ended": True,
            "achievements": [{"text": "Profile bullet two"}],
        },
    )
    proposal = await _propose_bullets(db, user, cv, item, ["CV bullet A"])
    sibling = await _propose_bullets(db, user, cv, other, ["CV bullet two revised"])
    await ExperienceService(db).update_item(
        user.id,
        item.id,
        {"achievements": [{"text": "Profile bullet one CHANGED"}]},
    )
    await _approve(db, user, sibling)

    from app.core.errors import ConflictError

    with pytest.raises(ConflictError):
        await _approve(db, user, proposal)


async def test_sibling_bullets_cards_apply_after_one_approval(db, auth_headers):
    """Approving one bullets card bumps the CV (context pin) — the
    remaining card on the SAME CV for a DIFFERENT item must still apply
    instead of false-conflicting."""
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    other = await ExperienceService(db).create_item(
        user.id,
        {
            "title": "Second internship",
            "kind": "internship",
            "org_name": "Beta",
            "start": "2025-07-01",
            "open_ended": True,
            "achievements": [{"text": "Profile bullet two"}],
        },
    )
    proposal = await _propose_bullets(db, user, cv, item, ["CV bullet A"])
    sibling = await _propose_bullets(db, user, cv, other, ["CV bullet two revised"])
    await _approve(db, user, proposal)
    applied = await _approve(db, user, sibling)

    assert applied is not None
    pins = ((await CvService(db).get_owned(cv.id, user.id)).context or {}).get(
        "synth_pins"
    ) or {}
    assert f"experience:{item.id}" in pins
    assert f"experience:{other.id}" in pins


async def test_revert_unpins_the_bullets_variant(db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    proposal = await _propose_bullets(db, user, cv, item, ["CV bullet A"])
    await _approve(db, user, proposal)
    reverted = await ProfileProposalService(db).revert(user.id, proposal.id)

    assert reverted.status == "reverted"
    fresh = await CvService(db).get_owned(cv.id, user.id)
    pins = (fresh.context or {}).get("synth_pins") or {}
    assert f"experience:{item.id}" not in pins, (
        "revert unpins — the profile bullets render again"
    )


async def test_revert_without_a_variant_is_a_clean_noop(db, auth_headers):
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    proposal = await _propose_bullets(db, user, cv, item, ["CV bullet A"])
    await _approve(db, user, proposal)
    await ProfileProposalService(db).revert(user.id, proposal.id)
    await ProfileProposalService(db).revert(user.id, proposal.id)

    fresh = await CvService(db).get_owned(cv.id, user.id)
    pins = (fresh.context or {}).get("synth_pins") or {}
    assert f"experience:{item.id}" not in pins
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
    listed = await run_tool(db, "read_cv_items", user.id, {"cv_id": str(cv.id)})
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

    relisted = await run_tool(db, "read_cv_items", user.id, {"cv_id": str(cv.id)})
    row = {r["item_id"]: r for r in relisted["items"]}[str(item.id)]
    assert row["bullets"] == ["Tailored bullet"]
    assert row["bullets_overridden_for_this_cv"] is True


def test_mock_emits_cv_set_bullets_after_the_read():
    from app.ai.mock_chat import mock_profile_ops

    ops = mock_profile_ops(
        {
            "read_cv_items": {
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


async def _builder_env(db, monkeypatch):
    """Mirror of the handoff suite's env: template bank + no PDF engine."""
    from tests.test_cv_assistant import _raise_engine_unavailable

    monkeypatch.setattr(
        "app.ai.agents.cv_builder_chat.measure_pages",
        _raise_engine_unavailable,
    )
    return db


async def test_chat_proposes_and_approval_applies_cv_bullets(
    client, db, auth_headers, monkeypatch
):
    """The full plan-107 flow: attached CV + bullet edit intent → builder
    loop → set_bullets op → override lands (no HITL card on this path)."""
    from app.seeds.cv_templates import seed_cv_template_bank
    from tests.test_chat_builder_handoff import _session

    await seed_cv_template_bank(db)
    await _builder_env(db, monkeypatch)
    user = await _auth_user(db)
    cv = await _cv(db, user)
    item = await _experience(db, user)
    session = await _session(client, auth_headers)
    response = await client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        json={
            "content": "update the bullets on this cv",
            "attachments": [{"kind": "cv", "cv_id": str(cv.id)}],
        },
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert "set_bullets" in response.text, "a cv_set_bullets card was proposed"

    listed = (
        await client.get("/api/v1/me/profile-proposals", headers=auth_headers)
    ).json()
    card = next(row for row in listed["proposals"] if row["kind"] == "cv_set_bullets")
    assert card["status"] == "pending"
    approved = await client.post(
        f"/api/v1/me/profile-proposals/{card['id']}/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["proposal"]["status"] == "approved", body["proposal"].get(
        "resolve_error"
    )

    fetched = await client.get(f"/api/v1/cv/{cv.id}", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text()
    pins = (fetched.json().get("context") or {}).get("synth_pins") or {}
    variant_id = pins[f"experience:{item.id}"]
    variant = await db.get(CvSynthItem, uuid.UUID(variant_id))
    assert variant.payload["achievements"] == [{"text": "tailored for this CV"}], (
        "the echoed heading lead is stripped at card creation"
    )
