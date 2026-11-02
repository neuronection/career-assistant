"""Plan 169 — per-goal profile usage: the ProfileUsage block on
AutopilotConstraints, its full-replace update semantics and the
``POST /autopilot/profile-context`` draft preview."""

import json
from uuid import UUID

from sqlalchemy import select

from app.models.autopilot_model import AutopilotGoal
from app.models.taxonomy_model import Skill
from app.schemas.autopilot import AutopilotConstraints, ProfileUsage
from app.services.growth.autopilot_service import AutopilotService
from app.services.profile.stages_service import stage_from_seniority

DEFAULT_PROFILE = {
    "use_skills": True,
    "use_education": True,
    "use_languages": True,
    "use_location": True,
    "use_experience": True,
    "use_lifestyle": True,
    "stage_source": "profile",
}


def _uid(auth_headers) -> UUID:
    from tests.conftest import decode_session_token

    return decode_session_token(auth_headers["Authorization"].split(" ", 1)[1])[0]


def _service(db, auth_headers=None) -> tuple[AutopilotService, str]:
    from langgraph.checkpoint.memory import InMemorySaver

    return AutopilotService(db, checkpointer=InMemorySaver()), _uid(auth_headers)


async def _goal(client, auth_headers, **overrides) -> dict:
    payload = {
        "goal_text": "Find me a junior QA or data job where I can use programming",
        "constraints": {"salary_min": 1},
    }
    payload.update(overrides)
    response = await client.post("/api/v1/autopilot/goals", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _detail(client, auth_headers, goal_id: str) -> dict:
    response = await client.get(f"/api/v1/autopilot/goals/{goal_id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


# ----------------------------------------------------------------- schema


def test_old_constraints_parse_to_default_profile():
    constraints = AutopilotConstraints.model_validate({"salary_min": 1})
    assert constraints.profile == ProfileUsage()
    assert constraints.profile.model_dump() == DEFAULT_PROFILE


def test_profile_usage_rejects_unknown_fields():
    from pydantic import ValidationError as PydanticValidationError

    try:
        ProfileUsage.model_validate({"use_skills": True, "bogus_flag": True})
    except PydanticValidationError:
        pass
    else:
        raise AssertionError("unknown profile-usage fields must be rejected")


def test_stage_from_seniority_mapping_table():
    from app.models.enums import CareerStage

    assert stage_from_seniority(["intern"]) == CareerStage.STUDENT
    assert stage_from_seniority(["junior"]) == CareerStage.EARLY_CAREER
    assert stage_from_seniority(["mid"]) == CareerStage.EARLY_CAREER
    assert stage_from_seniority(["senior"]) == CareerStage.EXPERIENCED
    assert stage_from_seniority(["lead"]) == CareerStage.EXPERIENCED
    assert stage_from_seniority(["principal"]) == CareerStage.EXPERIENCED
    assert stage_from_seniority(["junior", "principal"]) == CareerStage.EXPERIENCED, (
        "the max rank (target level) decides"
    )
    assert stage_from_seniority([]) is None, "empty selection keeps the profile stage"
    assert stage_from_seniority(["wizard"]) is None


# ---------------------------------------------------------------- goal API


async def test_goal_round_trip_carries_the_profile_block(client, auth_headers, db):
    created = await _goal(
        client,
        auth_headers,
        constraints={
            "salary_min": 1,
            "profile": {"use_skills": False, "stage_source": "goal"},
        },
    )
    detail = await _detail(client, auth_headers, created["id"])
    assert detail["constraints"]["profile"] == {
        **DEFAULT_PROFILE,
        "use_skills": False,
        "stage_source": "goal",
    }
    row = await db.get(AutopilotGoal, UUID(created["id"]))
    assert row.constraints["profile"]["use_skills"] is False


async def test_update_without_profile_resets_the_block(client, auth_headers, db):
    created = await _goal(
        client,
        auth_headers,
        constraints={"profile": {"use_skills": False, "use_languages": False}},
    )
    patched = await client.patch(
        f"/api/v1/autopilot/goals/{created['id']}",
        json={"constraints": {"salary_min": 2}},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    detail = await _detail(client, auth_headers, created["id"])
    assert detail["constraints"]["profile"] == DEFAULT_PROFILE, (
        "full-replace semantics: a PATCH without profile resets the block"
    )


async def test_goal_rejects_unknown_profile_fields(client, auth_headers):
    response = await client.post(
        "/api/v1/autopilot/goals",
        json={
            "goal_text": "data work",
            "constraints": {"profile": {"use_skills": True, "bogus_flag": True}},
        },
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text


# ----------------------------------------------------------------- preview


async def test_preview_defaults_match_the_profile_snapshot(client, auth_headers, profile_ready):
    response = await client.post(
        "/api/v1/autopilot/profile-context",
        json={"profile": {}, "seniority": []},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert snapshot["education_level"] == "high_school"
    assert snapshot["city"] == "Athens"
    assert snapshot["stage"] == "student", "the profile stage for the fixture user"
    assert snapshot["stage_source"] == "profile"
    assert snapshot["languages"] == [{"code": "en", "level": "advanced"}]
    assert snapshot["lifestyle_count"] == 1, "hours_available_per_week is set"


async def test_preview_goal_stage_derivation(client, auth_headers, profile_ready):
    response = await client.post(
        "/api/v1/autopilot/profile-context",
        json={"profile": {"stage_source": "goal"}, "seniority": ["junior", "senior"]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert snapshot["stage"] == "experienced", "the max seniority rank decides"
    assert snapshot["stage_source"] == "goal"


async def test_preview_stage_source_goal_without_seniority_falls_back(
    client, auth_headers, profile_ready
):
    response = await client.post(
        "/api/v1/autopilot/profile-context",
        json={"profile": {"stage_source": "goal"}, "seniority": []},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert snapshot["stage"] == "student"
    assert snapshot["stage_source"] == "profile"


async def test_preview_disabled_toggles_drop_their_keys(client, auth_headers, profile_ready):
    response = await client.post(
        "/api/v1/autopilot/profile-context",
        json={
            "profile": {"use_languages": False, "use_experience": False, "use_lifestyle": False},
            "seniority": [],
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert "languages" not in snapshot
    assert "stage" not in snapshot and "stage_source" not in snapshot
    assert "lifestyle_count" not in snapshot


async def test_preview_rejects_unknown_seniority(client, auth_headers, profile_ready):
    response = await client.post(
        "/api/v1/autopilot/profile-context",
        json={"profile": {}, "seniority": ["wizard"]},
        headers=auth_headers,
    )
    assert response.status_code == 400, response.text


async def test_preview_requires_auth(client):
    response = await client.post("/api/v1/autopilot/profile-context", json={"profile": {}})
    assert response.status_code == 401


# ------------------------------------------------------------- S3: planner gating


async def test_collect_profile_context_gates_fields(
    db, client, auth_headers, profile_ready, seeded_catalog
):
    from app.ai.graphs.autopilot import collect_profile_context
    from app.models.user_model import UserSkill

    user_id = _uid(auth_headers)
    skill = (await db.execute(select(Skill).where(Skill.key == "mathematics"))).scalars().first()
    db.add(UserSkill(user_id=user_id, skill_id=skill.id, level=5, source="self_report"))
    await db.commit()

    full = await collect_profile_context(db, user_id, {"seniority": ["junior"]})
    assert full["skills"] == [{"key": "mathematics", "level": 5}]
    assert full["education_level"] == "high_school"
    assert full["city"] == "Athens"
    assert full["languages"] == [{"code": "en", "level": "advanced"}]
    assert full["stage"] == "student" and full["stage_source"] == "profile"
    assert full["target_seniority"] == ["junior"]

    gated = await collect_profile_context(
        db,
        user_id,
        {
            "seniority": ["junior"],
            "profile": {
                "use_skills": False,
                "use_education": False,
                "use_location": False,
                "use_languages": False,
            },
        },
    )
    assert "skills" not in gated
    assert "education_level" not in gated
    assert "country" not in gated and "city" not in gated
    assert "languages" not in gated
    assert gated["stage"] == "student", "experience stays on unless its own flag is off"
    assert gated["target_seniority"] == ["junior"], "the goal's own constraint always stays"

    all_off = await collect_profile_context(
        db,
        user_id,
        {
            "seniority": [],
            "profile": {
                "use_skills": False,
                "use_education": False,
                "use_location": False,
                "use_languages": False,
                "use_experience": False,
            },
        },
    )
    assert all_off == {"target_seniority": []}, "all flags off plans from the goal text alone"


async def test_collect_profile_context_goal_stage(
    db, client, auth_headers, profile_ready, seeded_catalog
):
    from app.ai.graphs.autopilot import collect_profile_context

    user_id = _uid(auth_headers)
    context = await collect_profile_context(
        db,
        user_id,
        {"seniority": ["senior"], "profile": {"stage_source": "goal"}},
    )
    assert context["stage"] == "experienced"
    assert context["stage_source"] == "goal"

    context = await collect_profile_context(
        db,
        user_id,
        {
            "seniority": ["senior"],
            "profile": {"stage_source": "goal", "use_experience": False},
        },
    )
    assert "stage" not in context and "stage_source" not in context


async def test_plan_vocabulary_skips_user_neighbourhood(
    db, client, auth_headers, profile_ready, seeded_catalog
):
    from app.ai.graphs.autopilot import plan_vocabulary
    from app.models.user_model import UserSkill

    user_id = _uid(auth_headers)
    skill_rows = (await db.execute(select(Skill).where(Skill.key == "mathematics"))).scalars().all()
    assert skill_rows, "seeded taxonomy carries mathematics"
    db.add(
        UserSkill(
            user_id=user_id,
            skill_id=skill_rows[0].id,
            level=5,
            source="self_report",
        )
    )
    await db.commit()

    vocab_on = await plan_vocabulary(db, user_id, use_skills=True)
    assert "mathematics" in vocab_on["skills"], "own skills lead the vocabulary"

    vocab_off = await plan_vocabulary(db, user_id, use_skills=False)
    assert "mathematics" not in vocab_off["skills"], (
        "the user-skill neighbourhood is skipped; frequency padding only"
    )
    assert vocab_off["families"] == vocab_on["families"]
    assert vocab_off["sources"] == vocab_on["sources"]


async def test_planner_prompt_payload_excludes_disabled_fields():
    from app.ai.graphs.autopilot import _plan_user_prompt

    state = {
        "goal_text": "junior data analyst",
        "constraints": {"seniority": ["junior"], "must_terms": ["sql"]},
        "profile_context": {"target_seniority": ["junior"]},
    }
    payload = json.loads(_plan_user_prompt(state, {"skills": ["sql"]}))
    assert payload["profile_context"] == {"target_seniority": ["junior"]}
    assert payload["skill_keys"] == ["sql"]


async def test_deterministic_why_skips_disabled_dims():
    from app.ai.graphs.autopilot import _deterministic_why

    candidate = {
        "fit": 6.4,
        "breakdown": {
            "skills": {
                "score": 7.0,
                "detail": "skills disabled for this goal",
                "neutral": True,
                "disabled": True,
            },
            "prereqs": {"score": 5.0, "detail": "language de not evidenced"},
            "location_remote": {"score": 7.0, "detail": "location neutral", "neutral": True},
            "seniority_stage": {"score": 10.0, "detail": "junior role for a student"},
        },
        "skills": [],
    }
    why = _deterministic_why(candidate)
    assert "skills 7.0/10" not in why, "a disabled dim is never cited"
    assert "prereqs 5.0/10" in why and "seniority stage 10.0/10" in why
    assert "location remote 7.0/10" in why

    all_disabled = {
        "fit": 7.0,
        "breakdown": {
            "skills": {"score": 7.0, "detail": "x", "disabled": True},
            "prereqs": {"score": 7.0, "detail": "y", "disabled": True},
        },
        "skills": [],
    }
    assert _deterministic_why(all_disabled).startswith("Fit 7.0/10"), (
        "with none remaining the why falls back to the fit-only line"
    )


async def test_curator_prompt_carries_the_disabled_instruction():
    from app.ai.graphs.autopilot import _curate_system

    system = _curate_system(5)
    assert "disabled" in system
    assert "never cite them" in system


async def test_mock_planner_resolves_with_all_flags_off(
    client, auth_headers, db, search_fixtures, kinds
):
    created = await _goal(
        client,
        auth_headers,
        constraints={
            "salary_min": 1,
            "profile": {
                "use_skills": False,
                "use_education": False,
                "use_location": False,
                "use_languages": False,
                "use_experience": False,
                "use_lifestyle": False,
            },
        },
    )
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    assert result["status"] in ("completed", "budget_aborted"), result
    searches = [entry for entry in result["searches"] if entry.get("step") == "search"]
    assert searches and all(entry["error"] == "" for entry in searches)
