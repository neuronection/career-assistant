"""Assessment template library (plan 37): kind registry, validation,
versioning, import/export, engine parity, visibility ladder."""

import pytest
from sqlalchemy import select

from app.models.assessment_template_model import AssessmentTemplate
from app.models.experience_model import SkillEvidence
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill
from app.schemas.assessment_template import (
    Normalization,
    OptionScores,
    ResultBand,
    TemplateContent,
    TemplateOption,
    TemplatePhase,
    TemplateQuestion,
    Statement,
)
from app.services.assessment.question_kinds import (
    handler_for,
    is_scoring_capable,
    reset_registry,
)


def _mcq(skill_key="programming", delta=3.0):
    return TemplateQuestion(
        kind="scenario_mcq",
        prompt="The deadline moves up. What do you do?",
        options=[
            TemplateOption(
                id="o1",
                label="Re-plan",
                scores=OptionScores(skill_levels={skill_key: delta}),
            ),
            TemplateOption(
                id="o2",
                label="Renegotiate",
                scores=OptionScores(skill_levels={skill_key: 1.0}),
            ),
        ],
    )


def _content(skill_key="programming") -> TemplateContent:
    return TemplateContent(
        phases=[
            TemplatePhase(
                title="Core",
                questions=[
                    _mcq(skill_key),
                    TemplateQuestion(
                        kind="likert_matrix",
                        prompt="Rate your agreement",
                        statements=[
                            Statement(
                                id="st1",
                                text="I enjoy organizing work",
                                scores=OptionScores(skill_levels={skill_key: 2.0}),
                            ),
                            Statement(
                                id="st2",
                                text="I avoid planning",
                                reverse=True,
                                scores=OptionScores(skill_levels={skill_key: 2.0}),
                            ),
                        ],
                    ),
                ],
            )
        ],
        normalization=Normalization(
            bands=[
                ResultBand(
                    min=0,
                    max=6,
                    label="Exploring",
                    summary="Early signal.",
                    suggested_levels={skill_key: 3},
                ),
                ResultBand(
                    min=6,
                    max=10,
                    label="Building",
                    summary="Solid.",
                    suggested_levels={skill_key: 6},
                ),
            ]
        ),
    )


# ------------------------------------------------------------- kind registry


def test_built_in_kinds_round_trip():
    for kind in (
        "scenario_mcq",
        "multi_select",
        "forced_choice",
        "likert_matrix",
        "numeric_input",
        "eligibility_gate",
        "short_text",
    ):
        handler = handler_for(kind)
        assert is_scoring_capable(kind) == handler.scoring_capable


def test_multi_select_k_bounds():
    question = {
        "kind": "multi_select",
        "options": [
            {"id": f"o{i}", "label": f"opt{i}", "scores": {"skill_levels": {"s": 1}}}
            for i in range(1, 4)
        ],
        "time_split": {"min_select": 1, "max_select": 2},
    }
    handler = handler_for("multi_select")
    with pytest.raises(Exception):
        handler.validate(question, {"selected": ["o1", "o2", "o3"]})
    validated = handler.validate(question, {"selected": ["o1"]})
    assert validated == {"selected": ["o1"]}
    derived = handler.derive(question, validated)
    assert derived["skill_levels"] == {"s": 1.0}


def test_numeric_input_bounds():
    question = {
        "kind": "numeric_input",
        "options": [],
        "time_split": {
            "min": 0,
            "max": 60,
            "skill_key": "s",
            "per_unit": 0.1,
            "cap": 6,
        },
    }
    handler = handler_for("numeric_input")
    with pytest.raises(Exception):
        handler.validate(question, {"value": 100})
    derived = handler.derive(question, handler.validate(question, {"value": 30}))
    assert derived["skill_levels"] == {"s": 3.0}


def test_gate_touches_constraints_not_skills():
    question = {
        "kind": "eligibility_gate",
        "options": [
            {"id": "o1", "label": "Yes", "scores": {"constraint_value": "true"}},
            {"id": "o2", "label": "No", "scores": {"constraint_value": "false"}},
        ],
        "time_split": {"constraint_key": "willing_to_relocate"},
    }
    handler = handler_for("eligibility_gate")
    derived = handler.derive(question, handler.validate(question, {"option_id": "o1"}))
    assert derived["skill_levels"] == {}
    assert derived["constraints"] == {"willing_to_relocate": "true"}


def test_short_text_is_evidence_only():
    handler = handler_for("short_text")
    derived = handler.derive({}, handler.validate({}, {"text": "I led a team"}))
    assert derived["skill_levels"] == {} and derived["evidence"] == "I led a team"
    assert is_scoring_capable("short_text") is False


def test_likert_reverse_flags():
    question = {
        "kind": "likert_matrix",
        "options": [],
        "time_split": {
            "statements": [
                {
                    "id": "st1",
                    "text": "I plan ahead",
                    "scores": {"skill_levels": {"s": 2}},
                },
                {
                    "id": "st2",
                    "text": "I avoid planning",
                    "reverse": True,
                    "scores": {"skill_levels": {"s": 2}},
                },
            ]
        },
    }
    handler = handler_for("likert_matrix")
    answer = handler.validate(question, {"values": {"st1": 5, "st2": 5}})
    derived = handler.derive(question, answer)
    # strongly agree with the positive statement: +2; strongly agree with
    # the reverse statement: −2
    assert derived["skill_levels"]["s"] == 0.0
    answer = handler.validate(question, {"values": {"st1": 5, "st2": 1}})
    derived = handler.derive(question, answer)
    assert derived["skill_levels"]["s"] == 4.0


# ----------------------------------------------------------------- validator


def test_evidence_only_kind_cannot_carry_deltas():
    with pytest.raises(Exception):
        TemplateQuestion(
            kind="short_text",
            prompt="Tell us more",
            options=[
                TemplateOption(
                    id="o1", label="x", scores=OptionScores(skill_levels={"s": 1})
                ),
                TemplateOption(id="o2", label="y"),
            ],
        )


def test_delta_bounds_enforced():
    with pytest.raises(Exception):
        TemplateQuestion(
            kind="scenario_mcq",
            prompt="x",
            options=[
                TemplateOption(
                    id="o1", label="a", scores=OptionScores(skill_levels={"s": 50})
                ),
                TemplateOption(id="o2", label="b"),
            ],
        )


# ------------------------------------------------------------------ service


async def _skill_key(db) -> str:
    row = (await db.execute(select(Skill).limit(1))).scalars().first()
    return row.key


async def test_authoring_rejects_unknown_keys(client, auth_headers, seeded_catalog):
    body = {
        "title": "My test",
        "content": _content("no-such-skill").model_dump(mode="json"),
    }
    response = await client.post(
        "/api/v1/assessments/templates", json=body, headers=auth_headers
    )
    assert response.status_code == 400
    assert "no-such-skill" in response.json()["detail"]


async def test_authoring_publish_and_immutable_versions(
    client, auth_headers, seeded_catalog, db
):
    skill_key = await _skill_key(db)
    body = {
        "title": "Work style test",
        "content": _content(skill_key).model_dump(mode="json"),
    }
    created = await client.post(
        "/api/v1/assessments/templates", json=body, headers=auth_headers
    )
    assert created.status_code == 201, created.text
    template = created.json()
    assert template["status"] == "draft"
    original_hash = template["content_hash"]

    published = await client.patch(
        f"/api/v1/assessments/templates/{template['id']}",
        json={"status": "published"},
        headers=auth_headers,
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    edited = await client.patch(
        f"/api/v1/assessments/templates/{template['id']}",
        json={"title": "Work style test v2"},
        headers=auth_headers,
    )
    assert edited.json()["version"] == 2
    rows = (
        (
            await db.execute(
                select(AssessmentTemplate).where(
                    AssessmentTemplate.key == template["key"]
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert rows[0].content_hash == original_hash or rows[1].content_hash == (
        original_hash
    )
    hashes = {r.version: r.content_hash for r in rows}
    assert hashes[1] == original_hash  # v1 immutable


async def test_visibility_ladder_public_unreachable(
    client, auth_headers, seeded_catalog, db
):
    skill_key = await _skill_key(db)
    body = {
        "title": "Public attempt",
        "visibility": "public",
        "content": _content(skill_key).model_dump(mode="json"),
    }
    response = await client.post(
        "/api/v1/assessments/templates", json=body, headers=auth_headers
    )
    assert response.status_code == 400


async def test_export_import_round_trip_byte_stable(
    client, auth_headers, seeded_catalog, db
):
    skill_key = await _skill_key(db)
    created = await client.post(
        "/api/v1/assessments/templates",
        json={
            "title": "Portable test",
            "content": _content(skill_key).model_dump(mode="json"),
        },
        headers=auth_headers,
    )
    template_id = created.json()["id"]
    exported = await client.get(
        f"/api/v1/assessments/templates/{template_id}/export",
        headers=auth_headers,
    )
    assert exported.status_code == 200
    package = exported.json()

    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "importer37@example.com", "password": "supersecret1"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    imported = await client.post(
        "/api/v1/assessments/templates/import",
        json={"package": package},
        headers=other_headers,
    )
    assert imported.status_code == 201
    data = imported.json()
    assert data["content_hash"] == package["content_hash"]
    assert data["source"] == "imported"
    assert data["visibility"] == "private"
    assert data["import_report"]["proposed"] == []

    tampered = dict(package)
    tampered["content_hash"] = "0" * 64
    rejected = await client.post(
        "/api/v1/assessments/templates/import",
        json={"package": tampered},
        headers=other_headers,
    )
    assert rejected.status_code == 400


async def test_import_unknown_keys_propose_not_reject(
    client, auth_headers, seeded_catalog, db
):
    content = _content("brand-new-skill-37")
    package = {
        "schema_version": 1,
        "metadata": {"title": "Fresh keys"},
        "content": content.model_dump(mode="json"),
        "content_hash": None,
    }
    imported = await client.post(
        "/api/v1/assessments/templates/import",
        json={"package": package},
        headers=auth_headers,
    )
    assert imported.status_code == 201
    assert imported.json()["import_report"]["proposed"] == ["brand-new-skill-37"]
    rows = (
        (await db.execute(select(Skill).where(Skill.key == "brand-new-skill-37")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "proposed"
    assert rows[0].origin == "import"


async def test_template_run_engine_parity(
    client, auth_headers, seeded_catalog, db, kinds
):
    """Template run → 23 engine parity: same answer shapes, evidence
    upserts, fit refresh."""
    from app.models.matching_model import MatchInsight

    skill_key = await _skill_key(db)
    created = await client.post(
        "/api/v1/assessments/templates",
        json={
            "title": "Run me",
            "content": _content(skill_key).model_dump(mode="json"),
        },
        headers=auth_headers,
    )
    template_id = created.json()["id"]
    await client.patch(
        f"/api/v1/assessments/templates/{template_id}",
        json={"status": "published"},
        headers=auth_headers,
    )
    state = await client.post(
        f"/api/v1/assessments/templates/{template_id}/run", headers=auth_headers
    )
    assert state.status_code == 200, state.text
    run = state.json()
    assert run["kind"] == "template"
    assert run["phase_order"] == [5]
    questions = run["questions"]
    assert len(questions) == 2

    answers = []
    for question in questions:
        if question["kind"] == "scenario_mcq":
            answers.append(
                {"question_id": question["id"], "answer": {"option_id": "o1"}}
            )
        else:
            answers.append(
                {
                    "question_id": question["id"],
                    "answer": {"values": {"st1": 5, "st2": 1}},
                }
            )
    submitted = await client.post(
        f"/api/v1/assessments/{run['id']}/answers",
        json={"answers": answers},
        headers=auth_headers,
    )
    assert submitted.status_code == 200
    advanced = await client.post(
        f"/api/v1/assessments/{run['id']}/advance", headers=auth_headers
    )
    assert advanced.status_code == 200
    effects = advanced.json().get("effects") or {}
    assert effects.get("applied_skills") == 1
    assert effects.get("band", {}).get("label") in ("Exploring", "Building")

    user_skills = (await db.execute(select(UserSkill))).scalars().all()
    assert len(user_skills) == 1
    assert user_skills[0].source == "assessment"
    evidence = (await db.execute(select(SkillEvidence))).scalars().all()
    assert len(evidence) == 1
    assert str(evidence[0].assessment_run_id) == run["id"]
    fits = (await db.execute(select(MatchInsight))).scalars().all()
    assert fits, "fit refresh should have created insights"


async def test_ai_draft_requires_review_before_publish(
    client, auth_headers, seeded_catalog, db
):
    draft = await client.post(
        "/api/v1/assessments/templates/draft-ai",
        json={"brief": {"title": "Team style", "question_count": 2}},
        headers=auth_headers,
    )
    assert draft.status_code == 200
    content = draft.json()["content"]
    assert draft.json()["status"] == "draft_review"
    saved = await client.post(
        "/api/v1/assessments/templates",
        json={"title": "Team style", "content": content},
        headers=auth_headers,
    )
    assert saved.status_code == 201
    assert saved.json()["status"] == "draft"
    rows = (await db.execute(select(AssessmentTemplate))).scalars().all()
    assert all(r.status != "published" for r in rows)


def test_plugin_kind_registry_isolation():
    reset_registry()
    from app.services.assessment.question_kinds import REGISTRY

    assert "scenario_mcq" in REGISTRY
    reset_registry()
