"""Plan 169 — per-goal profile usage: the ProfileUsage block on
AutopilotConstraints, its full-replace update semantics and the
``POST /autopilot/profile-context`` draft preview."""

from uuid import UUID

from app.models.autopilot_model import AutopilotGoal
from app.schemas.autopilot import AutopilotConstraints, ProfileUsage
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
