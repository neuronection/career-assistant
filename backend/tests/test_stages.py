"""Phase 25 career stages: derivation, presets, stage-gated content."""

from uuid import UUID


from app.core.security import decode_access_token
from app.models.enums import CareerStage
from app.services.stages_service import (
    derive_career_stage,
    effective_stage,
    feature_flags,
    max_birth_year,
    stage_preset,
)


def _basics(**overrides) -> dict:
    base = {"birth_year": 2008, "education_level": "high_school"}
    base.update(overrides)
    return base


def _user_id(auth_headers) -> UUID:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    user_id, _version = decode_access_token(token)
    return user_id


# ------------------------------------------------------------- derivation


def test_derivation_student_by_age_and_education():
    assert derive_career_stage(_basics(), []) == CareerStage.STUDENT


def test_derivation_experienced_beats_young_age():
    experience = [
        {
            "kind": "freelance",
            "start_year": 2016,
            "end_year": 2026,
            "hours_per_week": 30,
        }
    ]
    assert derive_career_stage(_basics(birth_year=1998), experience) == (
        CareerStage.EXPERIENCED
    )


def test_derivation_early_career_from_short_evidence():
    experience = [
        {
            "kind": "internship",
            "start_year": 2025,
            "end_year": 2026,
            "hours_per_week": 20,
        }
    ]
    assert derive_career_stage(_basics(birth_year=2002), experience) == (
        CareerStage.EARLY_CAREER
    )


def test_derivation_returning_after_gap():
    experience = [
        {
            "kind": "part_time",
            "start_year": 2015,
            "end_year": 2022,
            "hours_per_week": 30,
        }
    ]
    assert derive_career_stage(_basics(birth_year=1990), experience) == (
        CareerStage.RETURNING
    )


def test_manual_override_wins_and_falls_back_when_cleared():
    basics = _basics(career_stage="switching")
    assert effective_stage(basics, []) == (CareerStage.SWITCHING, "explicit")
    basics.pop("career_stage")
    assert effective_stage(basics, [])[1] == "derived"


def test_stage_presets_are_suggestions_within_slider_range():
    for stage in CareerStage:
        preset = stage_preset(stage)
        assert set(preset) == {
            "skills",
            "location",
            "experience",
            "education",
            "interests",
        }
        assert all(1 <= value <= 5 for value in preset.values())
    student = stage_preset(CareerStage.STUDENT)
    experienced = stage_preset(CareerStage.EXPERIENCED)
    assert student["education"] > experienced["education"]
    assert student["experience"] < experienced["experience"]


# ------------------------------------------------------- profile validation


async def test_birth_year_accepts_older_users(client, auth_headers, profile_ready):
    response = await client.put(
        "/api/v1/profile",
        json={"basics": {"birth_year": 1985, "education_level": "bachelor"}},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    too_young = await client.put(
        "/api/v1/profile",
        json={"basics": {"birth_year": max_birth_year() + 1}},
        headers=auth_headers,
    )
    assert too_young.status_code == 422


async def test_grade_and_gpa_nullable_for_non_students(
    client, auth_headers, profile_ready
):
    response = await client.put(
        "/api/v1/profile",
        json={
            "basics": {
                "birth_year": 1990,
                "education_level": "bachelor",
                "career_stage": "returning",
            },
            "academics": {"favorite_subjects": [{"key": "mathematics", "weight": 4}]},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["basics"]["grade"] is None
    assert body["academics"]["gpa_band"] is None
    assert body["career_stage"] == "returning"
    assert body["stage_source"] == "explicit"


async def test_non_student_stage_strips_stale_student_fields(
    client, auth_headers, profile_ready
):
    await client.put(
        "/api/v1/profile",
        json={"academics": {"gpa_band": "excellent", "favorite_subjects": []}},
        headers=auth_headers,
    )
    switched = await client.put(
        "/api/v1/me/stage", json={"career_stage": "experienced"}, headers=auth_headers
    )
    assert switched.status_code == 200, switched.text
    profile = (await client.get("/api/v1/profile", headers=auth_headers)).json()
    assert profile["academics"]["gpa_band"] is None
    assert profile["basics"]["grade"] is None


# ---------------------------------------------------------------- presets


async def test_fit_uses_stage_preset_until_user_overrides(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.services.deps import get_profile_for_user
    from app.services.fit.service import FitService

    profile = await get_profile_for_user(db, _user_id(auth_headers))
    derived_weights = await FitService(db).scoring_weights(profile)
    assert derived_weights["experience"] == 1
    assert derived_weights["education"] == 5

    await client.put(
        "/api/v1/me/preferences/scoring",
        json={
            "skills": 5,
            "location": 5,
            "experience": 5,
            "education": 5,
            "interests": 5,
        },
        headers=auth_headers,
    )
    db.expire_all()
    profile = await get_profile_for_user(db, _user_id(auth_headers))
    overridden = await FitService(db).scoring_weights(profile)
    assert overridden == {
        "skills": 5,
        "location": 5,
        "experience": 5,
        "education": 5,
        "interests": 5,
    }


async def test_stage_switch_refits_and_returns_bootstrap(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    switched = await client.put(
        "/api/v1/me/stage", json={"career_stage": "experienced"}, headers=auth_headers
    )
    assert switched.status_code == 200, switched.text
    payload = switched.json()
    assert payload["career_stage"] == "experienced"
    assert payload["stage_source"] == "explicit"
    assert payload["refitted"] > 0
    assert payload["suggested_scoring_weights"] == stage_preset(CareerStage.EXPERIENCED)

    cleared = await client.put("/api/v1/me/stage", json={}, headers=auth_headers)
    assert cleared.status_code == 200
    assert cleared.json()["stage_source"] == "derived"


# ------------------------------------------------------- assessment content


async def test_question_selection_filters_by_audience_stages(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.services.assessment.phases import StandardScenarios
    from app.services.assessment.runner import AssessmentService

    service = AssessmentService(db)
    run = await service.create_run(_user_id(auth_headers), "full")
    phase = StandardScenarios()

    await client.put(
        "/api/v1/profile",
        json={"basics": {"career_stage": "student"}},
        headers=auth_headers,
    )
    student_prompts = [q.prompt for q in await phase.build_questions(db, run, {})]
    assert any("project month" in p for p in student_prompts)
    assert not any("Saturday shadowing" in p for p in student_prompts)

    await client.put(
        "/api/v1/profile",
        json={"basics": {"career_stage": "returning"}},
        headers=auth_headers,
    )
    run2 = await service.create_run(_user_id(auth_headers), "full")
    returner_prompts = [q.prompt for q in await phase.build_questions(db, run2, {})]
    assert any("Saturday shadowing" in p for p in returner_prompts)
    assert not any("project month" in p for p in returner_prompts)


async def test_mock_ai_phase3_prompt_includes_stage(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.ai.agents.assessment_designer import _mock_question_set
    from app.ai.agents.context import context_json
    from app.services.assessment.phases import AIScenarios
    from app.services.assessment.runner import AssessmentService

    prompt = context_json(
        {
            "profile": {},
            "top_family_keys": ["technology"],
            "skill_taxonomy": ["programming"],
            "career_stage": "returning",
            "count": 2,
        }
    )
    mocked = _mock_question_set(dict, prompt)
    assert mocked["questions"]
    assert all("returning stage" in q["prompt"] for q in mocked["questions"])

    await client.put(
        "/api/v1/profile",
        json={"basics": {"career_stage": "switching"}},
        headers=auth_headers,
    )
    service = AssessmentService(db)
    run = await service.create_run(_user_id(auth_headers), "full")
    built = await AIScenarios().build_questions(db, run, {})
    assert built
    assert any("switching stage" in q.prompt for q in built)


# ------------------------------------------------------------ bootstrap flags


async def test_bootstrap_flags_gate_universities_for_non_students(
    client, auth_headers, profile_ready
):
    student = (await client.get("/api/v1/me/bootstrap", headers=auth_headers)).json()
    assert student["features"]["universities"] is True
    assert student["stage_source"] in {"derived", "explicit"}

    await client.put(
        "/api/v1/me/stage", json={"career_stage": "experienced"}, headers=auth_headers
    )
    experienced = (
        await client.get("/api/v1/me/bootstrap", headers=auth_headers)
    ).json()
    assert experienced["career_stage"] == "experienced"
    assert experienced["features"]["universities"] is False
    assert experienced["features"]["grade_fields"] is False
    assert experienced["stage_source"] == "explicit"


def test_flags_and_ceiling_helpers():
    assert feature_flags(CareerStage.STUDENT)["universities"] is True
    assert not feature_flags(CareerStage.SWITCHING)["universities"]
    assert max_birth_year() == __import__("datetime").datetime.now().year - 14
