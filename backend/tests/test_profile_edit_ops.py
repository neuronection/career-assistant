"""Plan 99.2 — anchored text edits, granular collection edits, and the
retirement of full-replace update semantics."""

import uuid

import pytest

from sqlalchemy import select

from app.models.enums import AITaskType
from app.models.experience_model import (
    ExperienceItem,
    ExperienceSkill as ExperienceSkillLink,
)
from app.services.experience_service import ExperienceService
from app.services.profile_proposal_service import ProfileProposalService

from tests.test_profile_edit_grounding import _auth_user, _rich_item


@pytest.fixture
def service(db):
    return ProfileProposalService(db)


async def test_replace_anchor_resolves_the_field(service, db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    created, dropped = await service.create_from_ops(
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
                        "find": "Owned monitoring, alerting and incident "
                        "response for the landscape.",
                        "text": "Ran observability for the platform team.",
                    }
                ],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert dropped == []
    proposal = created[0]
    stored = proposal.payload_json
    assert "Ran observability" in stored["description"]
    assert "Owned monitoring" not in stored["description"]
    assert stored["description"].startswith("Worked as Support Engineer"), (
        "the untouched prose survives — only the anchor moved"
    )
    edit_ops = stored["_edit_ops"]
    assert edit_ops["text_edits"][0]["op"] == "replace"


async def test_replace_anchor_must_be_unique(service, db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    op = {
        "kind": "experience_item",
        "action": "update",
        "entity_id": str(item.id),
        "text_edits": [
            {"field": "description", "op": "replace", "find": "and", "text": "X"}
        ],
    }
    created, dropped = await service.create_from_ops(
        user.id, [op], grounding={f"read:experience_item:{item.id}"}
    )
    assert created == []
    assert dropped[0]["reason"].startswith("anchor_ambiguous")


async def test_replace_zero_match_is_an_anchor_mismatch(service, db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    created, dropped = await service.create_from_ops(
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
                        "find": "text that was never written",
                        "text": "X",
                    }
                ],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert created == []
    assert dropped[0]["reason"].startswith("anchor_mismatch")


async def test_append_prepend_join_and_empty_content(service, db, auth_headers):
    user = await _auth_user(db)
    item = await ExperienceService(db).create_item(
        user.id, {"title": "Empty", "kind": "project", "open_ended": True}
    )
    created, dropped = await service.create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "text_edits": [
                    {"field": "description", "op": "append", "text": "Second line."},
                    {"field": "description", "op": "prepend", "text": "First line."},
                ],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert dropped == []
    description = created[0].payload_json["description"]
    assert description == "First line.\nSecond line.", (
        "sequential: prepend anchors against the append's output"
    )


async def test_payload_text_edit_collision_conflicts(service, db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    created, dropped = await service.create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "payload": {"description": "full rewrite"},
                "text_edits": [
                    {"field": "description", "op": "append", "text": "more"}
                ],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert created == []
    assert dropped[0]["reason"].startswith("conflicting_edit")


async def test_collection_add_remove_skills_by_id_and_key(service, db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    read = await ProfileProposalService(db).read_entity_content(
        "experience_item", user.id, item.id
    )
    electron_id = read["content"]["skills"][0]["id"]

    created, dropped = await service.create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "collection_edits": [
                    {
                        "collection": "skills",
                        "op": "remove",
                        "match": {"id": electron_id},
                    },
                    {
                        "collection": "skills",
                        "op": "add",
                        "value": {"skill_key": "python", "role_in_item": "primary"},
                    },
                    {
                        "collection": "skills",
                        "op": "add",
                        "value": "docker",
                    },
                ],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert dropped == []
    skills = created[0].payload_json["skills"]
    assert [row["skill_key"] for row in skills] == ["typescript", "python", "docker"]
    assert skills[0]["role_in_item"] == "secondary"


async def test_collection_unknown_skill_anchor_drops(service, db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    created, dropped = await service.create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "collection_edits": [
                    {
                        "collection": "skills",
                        "op": "remove",
                        "match": {"id": str(uuid.uuid4())},
                    }
                ],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert created == []
    assert dropped[0]["reason"].startswith("anchor_mismatch")


async def test_collection_duplicate_skill_add_conflicts(service, db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    created, dropped = await service.create_from_ops(
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
                        "value": {"skill_key": "electron"},
                    }
                ],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert created == []
    assert dropped[0]["reason"].startswith("conflicting_edit")


async def test_achievement_and_link_edits(service, db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    read = await ProfileProposalService(db).read_entity_content(
        "experience_item", user.id, item.id
    )
    achievement_id = read["content"]["achievements"][0]["id"]

    created, dropped = await service.create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "collection_edits": [
                    {
                        "collection": "achievements",
                        "op": "remove",
                        "match": {"id": achievement_id},
                    },
                    {
                        "collection": "achievements",
                        "op": "add",
                        "value": {
                            "text": "Automated the nightly batch",
                            "metric": {"kind": "time_saved", "value": 6, "unit": "h"},
                        },
                    },
                    {
                        "collection": "links",
                        "op": "add",
                        "value": "https://github.com/example/ops",
                    },
                    {
                        "collection": "links",
                        "op": "remove",
                        "match": {"url": "https://github.com/example/support"},
                    },
                ],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert dropped == []
    stored = created[0].payload_json
    assert [row["text"] for row in stored["achievements"]] == [
        "Automated the nightly batch"
    ]
    assert [row["url"] for row in stored["links"]] == ["https://github.com/example/ops"]


async def test_text_edits_require_update_and_supported_fields(
    service, db, auth_headers
):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    grounding = {f"read:experience_item:{item.id}"}
    _, dropped = await service.create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "create",
                "payload": {"title": "New", "kind": "project", "open_ended": True},
                "text_edits": [{"field": "description", "op": "append", "text": "x"}],
            }
        ],
        grounding=set(),
    )
    assert "apply to update ops" in dropped[0]["reason"]
    _, dropped2 = await service.create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "text_edits": [{"field": "title", "op": "append", "text": "x"}],
            }
        ],
        grounding=grounding,
    )
    assert dropped2[0]["reason"].startswith("anchor_mismatch"), (
        "title is not an editable prose field"
    )


async def test_duplicate_target_second_op_drops(service, db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    grounding = {f"read:experience_item:{item.id}"}
    created, dropped = await service.create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "text_edits": [
                    {"field": "description", "op": "append", "text": "One."}
                ],
            },
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "text_edits": [
                    {"field": "description", "op": "append", "text": "Two."}
                ],
            },
        ],
        grounding=grounding,
    )
    assert len(created) == 1
    assert dropped[0]["reason"].startswith("duplicate_target")
    assert created[0].payload_json["description"].endswith("One.")


async def test_dropped_first_op_does_not_poison_the_second(service, db, auth_headers):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    created, dropped = await service.create_from_ops(
        user.id,
        [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "payload": {"hours_per_week": 999},
            },
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": str(item.id),
                "text_edits": [
                    {"field": "description", "op": "append", "text": "Valid."}
                ],
            },
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert len(dropped) == 1
    assert len(created) == 1
    assert created[0].payload_json["description"].endswith("Valid.")


async def test_approved_anchored_op_applies_through_the_form_service(
    service, db, auth_headers
):
    user = await _auth_user(db)
    item = await _rich_item(db, user)
    await db.refresh(item)
    description_before = item.description
    created, dropped = await service.create_from_ops(
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
                        "text": "Tuned the nightly batch job.",
                    }
                ],
                "collection_edits": [
                    {
                        "collection": "skills",
                        "op": "add",
                        "value": {"skill_key": "sql"},
                    }
                ],
            }
        ],
        grounding={f"read:experience_item:{item.id}"},
    )
    assert dropped == []
    proposal, applied, already = await service.approve(user.id, created[0].id)
    assert already is False
    await db.refresh(item)
    assert item.description == (f"{description_before}\nTuned the nightly batch job.")
    from sqlalchemy.orm import selectinload

    rows = (
        (
            await db.execute(
                select(ExperienceItem)
                .options(
                    selectinload(ExperienceItem.skills).selectinload(
                        ExperienceSkillLink.skill
                    )
                )
                .where(ExperienceItem.id == item.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    keys = [link.skill.key for link in rows[0].skills]
    assert keys == ["electron", "typescript", "sql"]


async def test_turn_with_text_edit_appends_and_preserves(client, db, auth_headers):
    """The plan-99 golden flow (the live overwrite failure): 'add X to my
    experience' must APPEND — the existing bullet survives, the card
    shows both, and approval applies exactly the anchored change."""
    import json as _json

    from app.ai import gateway as gateway_module
    from app.ai.mock_chat import mock_chat_reply
    from app.models.enums import AITaskType
    from app.models.profile_proposal_model import ProfileProposal

    user = await _auth_user(db)
    item = await _rich_item(db, user)
    await db.refresh(item)
    description_before = item.description

    def append_ops(schema, user_prompt):
        ctx = _json.loads(user_prompt.split("CONTEXT_JSON: ", 1)[1])
        tools = ctx.get("tool_results") or {}
        reads = tools.get("read_profile_item") or []
        items = (tools.get("my_experience") or {}).get("items") or []
        if not (items and reads):
            return {"answer": "grounding first"}
        return {
            "answer": "I have prepared a proposal to add that to your role.",
            "profile_ops": [
                {
                    "kind": "experience_item",
                    "action": "update",
                    "entity_id": items[0]["id"],
                    "text_edits": [
                        {
                            "field": "description",
                            "op": "append",
                            "text": "Tuned the nightly batch job.",
                        }
                    ],
                }
            ],
        }

    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "append"}, headers=auth_headers
        )
    ).json()
    gateway_module.register_mock_fixture(AITaskType.CHAT, append_ops)
    try:
        response = await client.post(
            f"/api/v1/chat/sessions/{session['id']}/messages",
            json={"content": "add to my experience item: tuned the nightly batch"},
            params={"stream": "true"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
    finally:
        gateway_module.register_mock_fixture(AITaskType.CHAT, mock_chat_reply)

    from tests.test_chat_streaming import _parse_sse

    events = _parse_sse(response.text)
    cards = [p for n, p in events if n == "proposal"]
    assert len(cards) == 1, events
    diff = {row["field"]: row for row in cards[0]["diff"]}
    assert description_before in diff["description"]["before"]
    assert "Tuned the nightly batch job." in diff["description"]["after"]
    assert "Owned monitoring" in diff["description"]["after"], (
        "the existing bullet survives the append"
    )

    approved = await client.post(
        f"/api/v1/me/profile-proposals/{cards[0]['id']}/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 200, approved.text
    await db.refresh(item)
    assert item.description == (f"{description_before}\nTuned the nightly batch job.")
    stored = (
        (
            await db.execute(
                select(ProfileProposal).where(
                    ProfileProposal.id == item.id.__class__(cards[0]["id"])
                )
            )
        )
        .scalars()
        .one()
    )
    stored = stored  # noqa: F841 — kept for readability
    assert stored.payload_json["_edit_ops"]["text_edits"][0]["op"] == "append"


async def test_repair_heals_anchor_mismatch(client, db, auth_headers):
    """The self-healing loop: a bad anchor drafts → anchor_mismatch → ONE
    repair round with the verbatim feedback → healed op → one card,
    audited as ops_draft + ops_repair:1 stages."""
    import json as _json

    from app.ai import gateway as gateway_module
    from app.ai.mock_chat import mock_chat_reply, mock_ops_draft
    from app.models.ai_model import AIGeneration
    from app.models.enums import AITaskType
    from tests.test_chat_profile_ops import _send

    user = await _auth_user(db)
    await _rich_item(db, user)
    calls = {"n": 0}

    def draft_with_bug(schema, user_prompt):
        calls["n"] += 1
        ctx = _json.loads(user_prompt.split("CONTEXT_JSON: ", 1)[1])
        tools = ctx.get("tool_results") or {}
        items = (tools.get("my_experience") or {}).get("items") or []
        if not items:
            return {"ops": []}
        if ctx.get("op_errors"):
            return {
                "ops": [
                    {
                        "kind": "experience_item",
                        "action": "update",
                        "entity_id": items[0]["id"],
                        "text_edits": [
                            {
                                "field": "description",
                                "op": "append",
                                "text": "Tuned the nightly batch job.",
                            }
                        ],
                    }
                ]
            }
        return {
            "ops": [
                {
                    "kind": "experience_item",
                    "action": "update",
                    "entity_id": items[0]["id"],
                    "text_edits": [
                        {
                            "field": "description",
                            "op": "replace",
                            "find": "text that was never written",
                            "text": "X",
                        }
                    ],
                }
            ]
        }

    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "repair"}, headers=auth_headers
        )
    ).json()
    gateway_module.register_mock_fixture(AITaskType.CHAT_OPS, draft_with_bug)
    try:
        events = await _send(
            client, session["id"], auth_headers, "update my project: nightly batch"
        )
    finally:
        gateway_module.register_mock_fixture(AITaskType.CHAT_OPS, mock_ops_draft)
        gateway_module.register_mock_fixture(AITaskType.CHAT, mock_chat_reply)

    cards = [p for n, p in events if n == "proposal"]
    assert len(cards) == 1, "the repair healed the op"
    assert calls["n"] == 2, "exactly one repair round"
    audits = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.CHAT_OPS.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert {row.run_stage for row in audits} == {"ops_draft", "ops_repair:1"}


async def test_non_edit_turn_skips_pipeline(client, db, auth_headers):
    """A question turn makes no CHAT_OPS call."""
    from app.models.ai_model import AIGeneration
    from tests.test_chat_profile_ops import _send, _session

    user = await _auth_user(db)
    await _rich_item(db, user)
    session = await _session(client, auth_headers)
    events = await _send(
        client, session["id"], auth_headers, "What do you think about my experience?"
    )
    rows = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.CHAT_OPS.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == []
    assert not [p for n, p in events if n == "proposal"]
