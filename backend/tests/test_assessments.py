"""Phase 23: assessment pipeline — phases, scoring, AI, reconciliation."""

from app.services.assessment.question_kinds import handler_for
from app.services.job_worker import JobWorker


async def _post_answers(client, run_id, answers, headers):
    return await client.post(
        f"/api/v1/assessments/{run_id}/answers",
        json={"answers": answers},
        headers=headers,
    )


async def _answer(client, run_id, question, choice, headers):
    return await _post_answers(
        client,
        run_id,
        [{"question_id": question["id"], "answer": choice}],
        headers,
    )


async def test_phase_order_subsets_and_custom_context(
    client, auth_headers, profile_ready, seeded_catalog
):
    body = await client.post(
        "/api/v1/assessments",
        json={"kind": "custom", "context": {"phase_order": [2, 4]}},
        headers=auth_headers,
    )
    assert body.status_code == 201, body.text
    state = body.json()
    assert state["phase_order"] == [2, 4]
    assert state["current_phase"] == 2
    assert state["questions"], "phase 2 should materialize bank questions"
    kinds = {q["kind"] for q in state["questions"]}
    assert {"scenario_mcq", "time_allocation", "ranking"} <= kinds


async def test_full_run_e2e_mock_ai(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    """Full pipeline: phases 1→4, AI scenarios via mock, completion effects."""
    run = (
        await client.post(
            "/api/v1/assessments", json={"kind": "full"}, headers=auth_headers
        )
    ).json()
    run_id = run["id"]
    assert run["current_phase"] == 1
    assert run["phase_one_form"] is True  # phase 1 renders the profile form

    # advance past the form phase
    advanced = await client.post(
        f"/api/v1/assessments/{run_id}/advance", headers=auth_headers
    )
    assert advanced.json()["current_phase"] == 2

    state = (
        await client.get(f"/api/v1/assessments/{run_id}", headers=auth_headers)
    ).json()
    questions = state["questions"]
    assert 0 < len(questions) <= 15  # anti-fatigue cap

    # answer everything (a couple skipped — skips must stay neutral)
    payloads = []
    for index, question in enumerate(questions):
        if question["kind"] == "scenario_mcq":
            choice = (
                {"option_id": question["options"][0]["id"]}
                if index % 4 != 3
                else None  # skip
            )
        elif question["kind"] == "time_allocation":
            weights = {o["id"]: 0 for o in question["options"]}
            first = question["options"][0]["id"]
            weights[first] = 100
            choice = {"weights": weights}
        elif question["kind"] == "ranking":
            choice = {"order": [o["id"] for o in question["options"]]}
        else:
            choice = None
        if choice is None:
            payloads.append({"question_id": question["id"], "answer": {}})
        else:
            payloads.append({"question_id": question["id"], "answer": choice})
    saved = await _post_answers(client, run_id, payloads, auth_headers)
    assert saved.status_code == 200, saved.text

    # advance into the AI phase (mock provider drafts question set)
    advanced = await client.post(
        f"/api/v1/assessments/{run_id}/advance", headers=auth_headers
    )
    assert advanced.json()["current_phase"] == 3

    state = (
        await client.get(f"/api/v1/assessments/{run_id}", headers=auth_headers)
    ).json()
    ai_questions = state["questions"]
    assert ai_questions
    assert any(q["source"] == "ai" for q in ai_questions)
    for question in ai_questions:
        for option in question["options"]:
            for key in option["scores"]["skill_levels"]:
                assert key != ""  # taxonomy keys resolved or dropped

    # answer the AI scenarios (all skipped → still advances; skip neutrality)
    payloads = [{"question_id": q["id"], "answer": {}} for q in ai_questions]
    saved = await _post_answers(client, run_id, payloads, auth_headers)
    assert saved.status_code == 200

    advanced = await client.post(
        f"/api/v1/assessments/{run_id}/advance", headers=auth_headers
    )
    assert advanced.json()["current_phase"] == 4

    state = (
        await client.get(f"/api/v1/assessments/{run_id}", headers=auth_headers)
    ).json()
    phase4 = state["questions"]
    allocation = next(q for q in phase4 if q["kind"] == "time_allocation")
    sliders = [q for q in phase4 if q["kind"] == "slider"]
    assert sliders

    # answer the allocation (weights must sum to 100) + every slider
    job_options = allocation["options"][:2]
    payloads = [
        {
            "question_id": allocation["id"],
            "answer": {
                "weights": {
                    job_options[0]["id"]: 60,
                    job_options[1]["id"]: 40,
                }
            },
        }
    ]
    payloads += [{"question_id": q["id"], "answer": {"value": 7}} for q in sliders]
    saved = await _post_answers(client, run_id, payloads, auth_headers)
    assert saved.status_code == 200, saved.text

    # final advance completes + applies
    done = await client.post(
        f"/api/v1/assessments/{run_id}/advance", headers=auth_headers
    )
    assert done.json()["status"] == "completed"

    results = (
        await client.get(f"/api/v1/assessments/{run_id}/results", headers=auth_headers)
    ).json()
    assert results["status"] == "completed"
    assert results["selection"][job_options[1]["id"].removeprefix("job:")] == 7
    assert results["shortlist"]

    # completion effects: interests from selection + refit
    profile = (await client.get("/api/v1/profile", headers=auth_headers)).json()
    assert profile["interests"]

    # AI rationale queued on completion — run the worker
    worker = JobWorker(db)
    while await worker.run_once():
        pass
    insights = (await client.get("/api/v1/match/insights", headers=auth_headers)).json()
    assert any(i["ai_score"] is not None for i in insights)

    # resumable state: history shows the completed run
    history = (await client.get("/api/v1/assessments", headers=auth_headers)).json()
    assert any(h["id"] == run_id and h["status"] == "completed" for h in history)


async def test_answer_validation_and_question_scope(
    client, auth_headers, profile_ready, seeded_catalog
):
    run = (
        await client.post(
            "/api/v1/assessments", json={"kind": "full"}, headers=auth_headers
        )
    ).json()
    await client.post(f"/api/v1/assessments/{run['id']}/advance", headers=auth_headers)
    state = (
        await client.get(f"/api/v1/assessments/{run['id']}", headers=auth_headers)
    ).json()
    question = state["questions"][0]

    bad_option = await _answer(
        client, run["id"], question, {"option_id": "nope"}, auth_headers
    )
    assert bad_option.status_code == 400

    bad_sum = await _answer(
        client,
        run["id"],
        state["questions"][1],
        {"weights": {state["questions"][1]["options"][0]["id"]: 50}},
        auth_headers,
    )
    assert bad_sum.status_code == 400


async def test_custom_run_from_source_and_cancel(
    client, auth_headers, profile_ready, seeded_catalog
):
    first = (
        await client.post(
            "/api/v1/assessments",
            json={
                "kind": "custom",
                "context": {"phase_order": [2], "focus_family_keys": ["healthcare"]},
            },
            headers=auth_headers,
        )
    ).json()
    canceled = await client.post(
        f"/api/v1/assessments/{first['id']}/cancel", headers=auth_headers
    )
    assert canceled.json()["status"] == "abandoned"

    # starting a new run abandons stale in-progress runs
    second = (
        await client.post(
            "/api/v1/assessments", json={"kind": "full"}, headers=auth_headers
        )
    ).json()
    history = (await client.get("/api/v1/assessments", headers=auth_headers)).json()
    first_row = next(h for h in history if h["id"] == first["id"])
    assert first_row["status"] == "abandoned"
    assert any(
        h["id"] == second["id"] and h["status"] == "in_progress" for h in history
    )


async def test_bank_question_options_span_families(db, seeded_catalog):
    """Seed-review checklist: every scenario spans >= 3 job families."""
    from sqlalchemy import select

    from app.models.assessment_model import AssessmentQuestion

    rows = (
        (
            await db.execute(
                select(AssessmentQuestion).where(
                    AssessmentQuestion.run_id.is_(None),
                    AssessmentQuestion.kind == "scenario_mcq",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows
    for question in rows:
        tags = {
            t
            for option in question.options
            for t in (option.get("scores") or {}).get("interest_keys", [])
        }
        assert len(tags) >= 3, f"option set too narrow: {question.prompt}"


async def test_kind_handlers_validate_and_derive():
    mcq = {
        "options": [
            {
                "id": "a",
                "scores": {"skill_levels": {"sql": 4}, "interest_keys": ["tech"]},
            },
            {
                "id": "b",
                "scores": {"skill_levels": {"empathy": 2}, "interest_keys": []},
            },
        ]
    }
    handler = handler_for("scenario_mcq")
    assert handler.validate(mcq, {"option_id": "a"}) == {"option_id": "a"}
    derived = handler.derive(mcq, {"option_id": "a"})
    assert derived["skill_levels"] == {"sql": 4.0}
    assert derived["interest_keys"] == ["tech"]

    allocation = handler_for("time_allocation")
    validated = allocation.validate(mcq, {"weights": {"a": 70, "b": 30}})
    derived = allocation.derive(mcq, validated)
    assert abs(derived["skill_levels"]["sql"] - 2.8) < 1e-9
    assert abs(derived["skill_levels"]["empathy"] - 0.6) < 1e-9
    assert derived["interest_keys"] == ["tech"]

    ranking = handler_for("ranking")
    validated = ranking.validate(mcq, {"order": ["b", "a"]})
    derived = ranking.derive(mcq, validated)
    assert abs(derived["skill_levels"]["empathy"] - 2.0) < 1e-9
    assert abs(derived["skill_levels"]["sql"] - 4 * 0.5) < 1e-9


async def test_skill_conflict_flagged_not_overwritten(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    """Assessed level diverging >2 from self-report is flagged, not applied."""
    await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": "organization", "level": 9}]},
        headers=auth_headers,
    )
    run = (
        await client.post(
            "/api/v1/assessments", json={"kind": "full"}, headers=auth_headers
        )
    ).json()
    rid = run["id"]

    async def answer_phase():
        state = (
            await client.get(f"/api/v1/assessments/{rid}", headers=auth_headers)
        ).json()
        answers = []
        for q in state["questions"]:
            if q["kind"] == "scenario_mcq":
                answers.append(
                    {
                        "question_id": q["id"],
                        "answer": {"option_id": q["options"][0]["id"]},
                    }
                )
            elif q["kind"] == "time_allocation":
                answers.append(
                    {
                        "question_id": q["id"],
                        "answer": {"weights": {q["options"][0]["id"]: 100}},
                    }
                )
            elif q["kind"] == "ranking":
                answers.append(
                    {
                        "question_id": q["id"],
                        "answer": {"order": [o["id"] for o in q["options"]]},
                    }
                )
            else:
                answers.append({"question_id": q["id"], "answer": {"value": 7}})
        return await client.post(
            f"/api/v1/assessments/{rid}/answers",
            json={"answers": answers},
            headers=auth_headers,
        )

    for _ in range(6):
        await answer_phase()
        advanced = await client.post(
            f"/api/v1/assessments/{rid}/advance", headers=auth_headers
        )
        body = advanced.json()
        if body.get("status") == "completed":
            effects = body.get("effects") or {}
            conflicts = {c["key"] for c in effects.get("skill_conflicts", [])}
            assert "organization" in conflicts
            break

    # the self-reported 9 was kept untouched
    skills = (await client.get("/api/v1/me/skills", headers=auth_headers)).json()
    org = next(s for s in skills if s["key"] == "organization")
    assert org["level"] == 9
    assert org["source"] == "self_report"
