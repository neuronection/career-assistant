"""Plan 225 S1: the assessment-question bank — adopt, apply, retire, empty."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.assessment_model import AssessmentAnswer, AssessmentQuestion
from app.models.seed_model import SeedItemProvenance
from tests.seed_pack_fixture import apply_bank_pack, bank_items
from tests.test_seed_apply import _service, _source, _store, _version
from tests.test_seed_pack import _envelope, _pack

BANK_PHASE = 2

Q1 = {
    "seed_key": "assessment-question:synthetic-one",
    "prompt": "Synthetic one?",
    "help": "Pick a role.",
    "phase": BANK_PHASE,
    "kind": "scenario_mcq",
    "options": [
        {
            "id": "o1",
            "label": "Build it",
            "detail": "Hands on.",
            "scores": {
                "skill_levels": {"programming": 3},
                "interest_keys": ["technology-software"],
            },
        },
        {
            "id": "o2",
            "label": "Explain it",
            "detail": "People facing.",
            "scores": {"skill_levels": {"teaching": 3}, "interest_keys": ["people-teaching"]},
        },
    ],
    "sort_index": 3,
    "audience_stages": ["student"],
    "time_split": {"style": 1.0},
}
Q2 = {
    "seed_key": "assessment-question:synthetic-two",
    "prompt": "Synthetic two?",
    "help": "Rank them.",
    "phase": BANK_PHASE,
    "kind": "ranking",
    "options": [
        {
            "id": "o1",
            "label": "Desk",
            "detail": "",
            "scores": {
                "skill_levels": {"programming": 2},
                "interest_keys": ["technology-software"],
            },
        },
        {
            "id": "o2",
            "label": "Floor",
            "detail": "",
            "scores": {"skill_levels": {"empathy": 2}, "interest_keys": ["people-health"]},
        },
    ],
    "sort_index": 4,
    "audience_stages": [],
}


def _question_pack(
    items: list | None, *, version: str = "1.0.0", replaces=None
) -> dict[str, bytes]:
    return _pack(
        {
            "items/assessment_questions/questions.json": _envelope(
                "assessment_questions", items or []
            )
        },
        manifest={"version": version, "replaces": replaces or []},
    )


def _bank_items() -> list[dict]:
    return [dict(item) for item in bank_items("assessment_questions")]


async def _operator_source(db):
    source = await _source(db)
    source.trust_tier = "operator"
    await db.commit()
    await db.refresh(source)
    return source


def _answer_for(question: dict) -> dict:
    if question["kind"] == "scenario_mcq":
        return {"option_id": question["options"][0]["id"]}
    if question["kind"] == "time_allocation":
        return {"weights": {question["options"][0]["id"]: 100}}
    if question["kind"] == "ranking":
        return {"order": [option["id"] for option in question["options"]]}
    return {"value": 7}


async def test_question_pack_parses_plans_applies_noops_updates_and_retires(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    version = await _version(db, store, source, _question_pack([Q1, Q2]))

    plan = await _service(db, store).build_plan(source, version)
    assert plan.status == "ok"
    question_items = [item for item in plan.items if item.entity_type == "assessment_question"]
    assert {item.action for item in question_items} == {"create"}
    first_preview = next(item.preview for item in question_items if item.seed_key.endswith("one"))
    assert first_preview == {
        "prompt": "Synthetic one?",
        "phase": BANK_PHASE,
        "kind": "scenario_mcq",
        "options": 2,
    }

    applied = await _service(db, store).apply(source, version)
    assert applied.status == "applied", applied.error
    rows = {
        row.seed_key: row
        for row in (
            await db.execute(select(AssessmentQuestion).where(AssessmentQuestion.run_id.is_(None)))
        )
        .scalars()
        .all()
    }
    assert set(rows) == {Q1["seed_key"], Q2["seed_key"]}
    one = rows[Q1["seed_key"]]
    assert one.source == "bank" and one.status == "active"
    assert [option["id"] for option in one.options] == ["o1", "o2"]
    assert one.options[0]["label"] == "Build it"
    assert one.options[0]["scores"]["skill_levels"] == {"programming": 3.0}
    assert one.help == Q1["help"]
    assert one.phase == BANK_PHASE
    assert one.kind == "scenario_mcq"
    assert one.sort_index == 3
    assert one.audience_stages == ["student"]
    assert one.time_split == {"style": 1.0}
    provenance = await db.scalar(
        select(SeedItemProvenance).where(
            SeedItemProvenance.entity_type == "assessment_question",
            SeedItemProvenance.entity_id == one.id,
        )
    )
    planned_one = next(item for item in question_items if item.seed_key == Q1["seed_key"])
    assert provenance is not None
    assert provenance.content_hash == planned_one.content_hash

    again = await _service(db, store).apply(source, version)
    assert again.status == "noop"

    edited = dict(Q1, help="Updated guidance.")
    changed = await _version(db, store, source, _question_pack([edited], version="2.0.0"))
    changed_plan = await _service(db, store).build_plan(source, changed)
    actions = {
        item.seed_key: item.action
        for item in changed_plan.items
        if item.entity_type == "assessment_question"
    }
    assert actions[Q1["seed_key"]] == "update"
    assert actions[Q2["seed_key"]] == "retire"

    applied = await _service(db, store).apply(source, changed)
    assert applied.status == "applied", applied.error
    one = await db.scalar(
        select(AssessmentQuestion).where(AssessmentQuestion.seed_key == Q1["seed_key"])
    )
    two = await db.scalar(
        select(AssessmentQuestion).where(AssessmentQuestion.seed_key == Q2["seed_key"])
    )
    assert one is not None and one.help == "Updated guidance." and one.status == "active"
    assert two is not None and two.status == "retired"

    restored = await _version(db, store, source, _question_pack([edited, Q2], version="3.0.0"))
    restored_plan = await _service(db, store).build_plan(source, restored)
    assert any(
        item.seed_key == Q2["seed_key"] and item.action == "update"
        for item in restored_plan.items
        if item.entity_type == "assessment_question"
    )
    applied = await _service(db, store).apply(source, restored)
    assert applied.status == "applied", applied.error
    two = await db.scalar(
        select(AssessmentQuestion).where(AssessmentQuestion.seed_key == Q2["seed_key"])
    )
    assert two is not None and two.status == "active"

    removed = await _version(db, store, source, _question_pack([], version="4.0.0"))
    applied = await _service(db, store).apply(source, removed)
    assert applied.status == "applied", applied.error
    retired = (
        (await db.execute(select(AssessmentQuestion).where(AssessmentQuestion.run_id.is_(None))))
        .scalars()
        .all()
    )
    assert len(retired) == 2
    assert {row.status for row in retired} == {"retired"}


async def test_a_pack_adopts_the_reference_bank_without_duplicates(db, tmp_path):
    fixture = await apply_bank_pack(db)
    before = {
        row.seed_key: row.id
        for row in (
            await db.execute(select(AssessmentQuestion).where(AssessmentQuestion.run_id.is_(None)))
        )
        .scalars()
        .all()
    }
    assert len(before) == len(_bank_items())
    assert None not in before

    version = await _version(db, fixture.store, fixture.source, _question_pack(_bank_items()))

    plan = await _service(db, fixture.store).build_plan(fixture.source, version)
    assert not [item for item in plan.items if item.action in ("create", "retire", "delete")]
    assert {item.action for item in plan.items if item.entity_type == "assessment_question"} <= {
        "update",
        "noop",
    }

    applied = await _service(db, fixture.store).apply(fixture.source, version)
    assert applied.status in ("applied", "noop"), applied.error
    again = await _service(db, fixture.store).apply(fixture.source, version)
    assert again.status == "noop"
    rows = (
        (await db.execute(select(AssessmentQuestion).where(AssessmentQuestion.run_id.is_(None))))
        .scalars()
        .all()
    )
    assert len(rows) == len(_bank_items())
    assert {row.id for row in rows} == set(before.values())
    assert {row.seed_key for row in rows} == set(before)
    assert {row.source for row in rows} == {"bank"}
    assert all(row.options for row in rows)
    assert {row.status for row in rows} == {"active"}


async def test_a_completed_run_survives_question_retirement(
    client, db, auth_headers, profile_ready, fixture_banks
):
    store = fixture_banks.store
    source = fixture_banks.source

    created = await client.post(
        "/api/v1/assessments",
        json={"kind": "custom", "context": {"phase_order": [BANK_PHASE]}},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    run = created.json()
    run_id = run["id"]
    questions = run["questions"]
    assert questions
    clone_ids = {question["id"] for question in questions}

    saved = await client.post(
        f"/api/v1/assessments/{run_id}/answers",
        json={
            "answers": [
                {"question_id": question["id"], "answer": _answer_for(question)}
                for question in questions
            ]
        },
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    done = await client.post(f"/api/v1/assessments/{run_id}/advance", headers=auth_headers)
    assert done.json()["status"] == "completed"

    removed_key = "assessment-question:charity-event-role"
    remaining = [item for item in _bank_items() if item["seed_key"] != removed_key]
    retired_version = await _version(db, store, source, _question_pack(remaining, version="2.0.0"))
    retired_plan = await _service(db, store).build_plan(source, retired_version)
    assert any(
        item.seed_key == removed_key and item.action == "retire" for item in retired_plan.items
    )
    retired = await _service(db, store).apply(source, retired_version)
    assert retired.status == "applied", retired.error

    bank_row = await db.scalar(
        select(AssessmentQuestion).where(
            AssessmentQuestion.seed_key == removed_key,
            AssessmentQuestion.run_id.is_(None),
        )
    )
    assert bank_row is not None and bank_row.status == "retired"
    clones = (
        (
            await db.execute(
                select(AssessmentQuestion).where(AssessmentQuestion.run_id == uuid.UUID(run_id))
            )
        )
        .scalars()
        .all()
    )
    assert {str(clone.id) for clone in clones} == clone_ids
    assert all(clone.status != "retired" for clone in clones)
    answers = (
        (
            await db.execute(
                select(AssessmentAnswer).where(AssessmentAnswer.run_id == uuid.UUID(run_id))
            )
        )
        .scalars()
        .all()
    )
    assert len(answers) == len(questions)

    still = await client.get(f"/api/v1/assessments/{run_id}", headers=auth_headers)
    assert still.status_code == 200
    assert still.json()["status"] == "completed"
    results = await client.get(f"/api/v1/assessments/{run_id}/results", headers=auth_headers)
    assert results.status_code == 200


async def test_a_pack_without_questions_does_not_retire_the_bank(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(db, store, source, _question_pack([Q1, Q2]))
    applied = await _service(db, store).apply(source, first)
    assert applied.status == "applied", applied.error

    templates_only = _pack(
        {"items/assessment_templates/templates.json": _envelope("assessment_templates", [])},
        manifest={"version": "2.0.0", "replaces": []},
    )
    second = await _version(db, store, source, templates_only)
    plan = await _service(db, store).build_plan(source, second)
    assert not [
        item
        for item in plan.items
        if item.entity_type == "assessment_question" and item.action == "retire"
    ]

    applied = await _service(db, store).apply(source, second)
    assert applied.status in ("applied", "noop"), applied.error
    rows = (
        (await db.execute(select(AssessmentQuestion).where(AssessmentQuestion.run_id.is_(None))))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {row.status for row in rows} == {"active"}


async def test_a_zero_question_bank_phase_is_skipped_with_a_notice(
    client, db, auth_headers, profile_ready
):
    from sqlalchemy import update

    from app.models.enums import QuestionStatus

    await db.execute(
        update(AssessmentQuestion)
        .where(
            AssessmentQuestion.run_id.is_(None),
            AssessmentQuestion.phase == BANK_PHASE,
        )
        .values(status=QuestionStatus.RETIRED.value)
    )
    db.add(
        AssessmentQuestion(
            run_id=None,
            seed_key="assessment-question:experienced-only",
            phase=BANK_PHASE,
            kind="scenario_mcq",
            prompt="Only experienced candidates see this.",
            help="",
            options=[
                {
                    "id": "o1",
                    "label": "A",
                    "detail": "",
                    "scores": {"skill_levels": {}, "interest_keys": ["technology-software"]},
                }
            ],
            source="bank",
            status=QuestionStatus.ACTIVE.value,
            sort_index=0,
            audience_stages=["experienced"],
        )
    )
    await db.commit()

    created = await client.post(
        "/api/v1/assessments",
        json={"kind": "custom", "context": {"phase_order": [BANK_PHASE, 4]}},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    state = created.json()
    assert state["current_phase"] == 4
    assert not [question for question in state["questions"] if question["phase"] == BANK_PHASE]
    notice = state["phase_notices"]["2"]
    assert notice["code"] == "ASSESSMENT_BANK_PHASE_EMPTY"
    assert notice["pack"] == "neuronection-reference-banks"
    assert state["context"]["phase_notices"]["2"]["phase"] == 2


async def test_a_run_refuses_when_the_whole_bank_is_missing(client, auth_headers):
    refused = await client.post("/api/v1/assessments", json={"kind": "full"}, headers=auth_headers)
    assert refused.status_code == 409
    assert "neuronection-reference-banks" in refused.json()["detail"]
    history = (await client.get("/api/v1/assessments", headers=auth_headers)).json()
    assert history == []

    profile = await client.get("/api/v1/profile", headers=auth_headers)
    assert profile.status_code == 200
    cv = await client.get("/api/v1/cv", headers=auth_headers)
    assert cv.status_code == 200


@pytest.mark.parametrize("phase", [3, 4])
async def test_non_bank_runs_do_not_need_the_bank(client, auth_headers, phase):
    created = await client.post(
        "/api/v1/assessments",
        json={"kind": "custom", "context": {"phase_order": [phase]}},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["current_phase"] == phase
