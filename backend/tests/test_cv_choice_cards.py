"""cv_choice cards (plan 108): the multi-select picker that fans out
into canonical pending child proposals — creation-time payload
validation, option-selective materialization, and resolve semantics.
The card is a picker, never an executor: approving a parent only
creates children; each child resolves like any other card."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.errors import ValidationError
from app.models.profile_proposal_model import ProfileProposal
from app.models.user_model import User
from app.schemas.profile_proposal import CvChoiceOpPayload
from app.services.experience_service import ExperienceService
from app.services.profile_proposal_service import (
    ProfileProposalService,
    proposal_event,
)

from tests.test_profile_proposals import _auth_user


def _choice_payload(**overrides) -> dict:
    payload = {
        "question": "Which adjustments should I implement?",
        "options": [
            {
                "key": "tighten",
                "kind": "cv_synth",
                "action": "create",
                "label": "Tighten the full entry",
                "description": "CV-scoped restyle variant (this CV only)",
                "payload": {
                    "refs": [{"source_key": "projects", "item_id": "x"}],
                    "action": "restyle",
                },
            },
            {
                "key": "bullets",
                "kind": "profile_achievement",
                "action": "create",
                "label": "Add an achievement",
                "payload": {"title": "Speaker", "kind": "award"},
            },
        ],
    }
    payload.update(overrides)
    return payload


async def _user(db) -> User:
    return await _auth_user(db)


async def test_choice_validates_option_payloads(db, auth_headers) -> None:
    user = await _user(db)
    bad = {
        "question": "Pick",
        "options": [
            {
                "key": "a",
                "kind": "user_skill",
                "action": "create",
                "label": "A",
                "payload": {"level": 99, "skill_key": "go"},
            },
        ],
    }
    with pytest.raises(Exception):
        await ProfileProposalService(db).create(
            user.id, kind="cv_choice", action="create", payload=bad
        )


async def test_choice_rejects_nested_choices_and_single_option(
    db, auth_headers
) -> None:
    nested = {
        "question": "Pick",
        "min_select": 2,
        "max_select": 2,
        "options": [
            {
                "key": "a",
                "kind": "cv_choice",
                "action": "create",
                "label": "nested",
                "payload": {},
            },
            {
                "key": "b",
                "kind": "user_skill",
                "action": "create",
                "label": "B",
                "payload": {"skill_key": "go", "level": 3},
            },
        ],
    }
    with pytest.raises(Exception):
        CvChoiceOpPayload.model_validate(nested)
    single = {
        "question": "Pick",
        "max_select": 2,
        "options": [
            {
                "key": "lonely",
                "kind": "user_skill",
                "action": "create",
                "label": "only",
                "payload": {"skill_key": "go", "level": 3},
            },
        ],
    }
    with pytest.raises(Exception):
        CvChoiceOpPayload.model_validate(single)


async def test_create_persists_options_and_event_carries_payload(
    db, auth_headers
) -> None:
    user = await _user(db)
    proposal = await ProfileProposalService(db).create(
        user.id,
        kind="cv_choice",
        action="create",
        payload={
            "question": "Which one would you like to implement?",
            "max_select": 2,
            "options": [
                {
                    "key": "one",
                    "kind": "user_skill",
                    "action": "create",
                    "label": "Add Go (level 4)",
                    "description": "skill bump",
                    "payload": {"skill_key": "go", "level": 4},
                },
                {
                    "key": "two",
                    "kind": "user_skill",
                    "action": "create",
                    "label": "Add Rust (level 2)",
                    "payload": {"skill_key": "rust", "level": 2},
                },
            ],
        },
    )
    assert proposal.status == "pending"
    assert proposal.entity_label.startswith("Which one")
    event = proposal_event(proposal)
    opts = event["payload"]["options"]
    assert [o["key"] for o in opts] == ["one", "two"], (
        "picker cards must stream their option body from payload_json"
    )


async def test_approve_requires_selection_and_fans_out(db, auth_headers) -> None:
    user = await _user(db)
    service = ProfileProposalService(db)
    parent = await service.create(
        user.id,
        kind="cv_choice",
        action="create",
        payload={
            "question": "Pick adjustments",
            "max_select": 2,
            "options": [
                {
                    "key": "go",
                    "kind": "user_skill",
                    "action": "create",
                    "label": "Add Go (level 4)",
                    "payload": {"skill_key": "go", "level": 4},
                },
                {
                    "key": "achie",
                    "kind": "profile_achievement",
                    "action": "create",
                    "label": "Add an award",
                    "payload": {"title": "Hackathon winner", "kind": "award"},
                },
            ],
        },
    )
    with pytest.raises(ValidationError):
        await service.approve(user.id, parent.id)
    with pytest.raises(ValidationError):
        await service.approve(user.id, parent.id, option_keys=["nonsense"])

    approved, applied, already = await service.approve(
        user.id, parent.id, option_keys=["go", "achie"]
    )
    assert not already
    assert applied is not None
    children = applied["children"]
    assert len(children) == 2
    assert all(child.status == "pending" for child in children)
    assert approved.status == "approved"
    resolved = approved.payload_json["_resolved_options"]
    assert [entry["key"] for entry in resolved["children"]] == ["go", "achie"]

    stored = (
        (
            await db.execute(
                select(ProfileProposal).where(ProfileProposal.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    kinds = sorted(row.kind for row in stored)
    assert kinds == ["cv_choice", "profile_achievement", "user_skill"]
    for child in children:
        assert child.status == "pending"


async def test_approve_endpoint_serializes_children(db, client, auth_headers) -> None:
    """The approve response's children are full cards (title/payload/diff),
    not raw ORM rows with empty defaults."""
    user = await _user(db)
    parent = await ProfileProposalService(db).create(
        user.id,
        kind="cv_choice",
        action="create",
        payload={
            "question": "Pick adjustments",
            "max_select": 1,
            "options": [
                {
                    "key": "go",
                    "kind": "user_skill",
                    "action": "create",
                    "label": "Add Go (level 4)",
                    "payload": {"skill_key": "go", "level": 4},
                },
                {
                    "key": "achie",
                    "kind": "profile_achievement",
                    "action": "create",
                    "label": "Add an award",
                    "payload": {"title": "Hackathon winner", "kind": "award"},
                },
            ],
        },
    )
    response = await client.post(
        f"/api/v1/me/profile-proposals/{parent.id}/approve",
        json={"option_keys": ["achie"]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    children = response.json()["children"]
    assert len(children) == 1
    child = children[0]
    assert child["kind"] == "profile_achievement"
    assert child["title"], "the child card carries its title"
    assert child["payload"].get("title") == "Hackathon winner"
    assert child["destructive"] is False


async def test_approve_fanout_drops_invalid_children_with_reason(
    db, auth_headers
) -> None:
    user = await _user(db)
    item = await ExperienceService(db).create_item(
        user.id,
        {
            "title": "Job",
            "kind": "job",
            "org_name": "Org",
            "start": "2025-01-01",
            "open_ended": True,
        },
    )
    service = ProfileProposalService(db)
    parent = await service.create(
        user.id,
        kind="cv_choice",
        action="create",
        payload={
            "question": "Pick",
            "max_select": 2,
            "options": [
                {
                    "key": "title",
                    "kind": "experience_item",
                    "action": "update",
                    "entity_id": str(item.id),
                    "label": "Rename",
                    "payload": {"title": "Senior Job"},
                },
                {
                    "key": "bogus",
                    "kind": "experience_item",
                    "action": "update",
                    "entity_id": str(uuid4()),
                    "label": "Ghost rename",
                    "payload": {"title": "Renamed while gone"},
                },
            ],
        },
    )
    approved, applied, _ = await service.approve(
        user.id, parent.id, option_keys=["title", "bogus"]
    )
    assert len(applied["children"]) == 1
    assert applied["dropped"] and "bogus" in applied["dropped"][0]["key"]


async def test_reject_leaves_children_uncreated(db, auth_headers) -> None:
    user = await _user(db)
    service = ProfileProposalService(db)
    parent = await service.create(
        user.id,
        kind="cv_choice",
        action="create",
        payload={
            "question": "Pick",
            "options": [
                {
                    "key": "go",
                    "kind": "user_skill",
                    "action": "create",
                    "label": "Add Go",
                    "payload": {"skill_key": "go", "level": 4},
                },
                {
                    "key": "two",
                    "kind": "user_skill",
                    "action": "create",
                    "label": "Add Rust",
                    "payload": {"skill_key": "rust", "level": 2},
                },
            ],
        },
    )
    rejected = await service.reject(user.id, parent.id)
    assert rejected.status == "rejected"
    stored = (
        (
            await db.execute(
                select(ProfileProposal).where(ProfileProposal.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert [row.kind for row in stored] == ["cv_choice"]


async def test_unknown_option_keys_and_bounds_are_hard_errors(db, auth_headers) -> None:
    user = await _user(db)
    service = ProfileProposalService(db)
    parent = await service.create(
        user.id,
        kind="cv_choice",
        action="create",
        payload={
            "question": "Pick",
            "min_select": 1,
            "max_select": 1,
            "options": [
                {
                    "key": "go",
                    "kind": "user_skill",
                    "action": "create",
                    "label": "Add Go",
                    "payload": {"skill_key": "go", "level": 4},
                },
                {
                    "key": "two",
                    "kind": "user_skill",
                    "action": "create",
                    "label": "Add Rust",
                    "payload": {"skill_key": "rust", "level": 2},
                },
            ],
        },
    )
    with pytest.raises(ValidationError):
        await service.approve(user.id, parent.id, option_keys=["go", "two"])
    with pytest.raises(ValidationError):
        await service.approve(user.id, parent.id, option_keys=[])
    assert parent.status == "pending"
    stored = (
        (
            await db.execute(
                select(ProfileProposal).where(ProfileProposal.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(stored) == 1


async def test_choice_revert_is_not_available(db, auth_headers) -> None:
    user = await _user(db)
    service = ProfileProposalService(db)
    parent = await service.create(
        user.id,
        kind="cv_choice",
        action="create",
        payload={
            "question": "Pick",
            "options": [
                {
                    "key": "go",
                    "kind": "user_skill",
                    "action": "create",
                    "label": "Add Go",
                    "payload": {"skill_key": "go", "level": 4},
                },
                {
                    "key": "two",
                    "kind": "user_skill",
                    "action": "create",
                    "label": "Add Rust",
                    "payload": {"skill_key": "rust", "level": 2},
                },
            ],
        },
    )
    await service.approve(user.id, parent.id, option_keys=["go"])
    await db.refresh(parent)
    assert parent.status == "approved", (
        f"parent {parent.status} error={parent.resolve_error}"
    )
    with pytest.raises(ValidationError):
        await service.revert(user.id, parent.id)
    stored = (
        (
            await db.execute(
                select(ProfileProposal).where(ProfileProposal.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(row.status == "pending" and row.kind == "user_skill" for row in stored)
