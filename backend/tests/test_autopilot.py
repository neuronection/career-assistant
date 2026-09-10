"""— Career Autopilot: goal CRUD, the checkpointed LangGraph run
(mock provider e2e), guardrails (budget abort, cooldown, pause), constraint
learning, transparency timeline, isolation and the no-apply invariant."""

from datetime import datetime, timezone
from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.models.autopilot_model import AutopilotFinding, AutopilotGoal, AutopilotRun
from app.models.enums import BackgroundJobType, ScheduleKind
from app.services.autopilot_service import AutopilotService
from app.services.scheduler.runner import KIND_TASKS


def _uid(auth_headers) -> UUID:
    from app.core.security import decode_access_token

    return decode_access_token(auth_headers["Authorization"].split(" ", 1)[1])[0]


async def _goal(client, auth_headers, **overrides) -> dict:
    payload = {
        "goal_text": "Find me a junior QA or data job where I can use programming",
        "constraints": {"salary_min": 1},
    }
    payload.update(overrides)
    response = await client.post(
        "/api/v1/autopilot/goals", json=payload, headers=auth_headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _service(db, auth_headers=None) -> tuple[AutopilotService, str]:
    from app.core.security import decode_access_token

    user_id = decode_access_token(auth_headers["Authorization"].split(" ", 1)[1])[0]
    return AutopilotService(db, checkpointer=InMemorySaver()), user_id


# ------------------------------------------------------------- registry wiring


def test_scheduler_maps_autopilot_kind_to_job():
    assert (
        KIND_TASKS[ScheduleKind.USER_AUTOPILOT.value]
        == BackgroundJobType.AUTOPILOT_RUN.value
    )


async def test_task_registered_in_registry():
    from app.ai.tasks import task_def

    definition = task_def("autopilot_run")
    assert definition.tier == "strong"
    assert definition.requires == "text"


# ------------------------------------------------------------------ goal CRUD


async def test_goal_crud_round_trip(client, auth_headers, db):
    created = await _goal(client, auth_headers)
    goal_id = created["id"]

    paused = await client.patch(
        f"/api/v1/autopilot/goals/{goal_id}",
        json={"status": "paused"},
        headers=auth_headers,
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    row = await db.get(AutopilotGoal, UUID(goal_id))
    assert row.status == "paused"

    deleted = await client.delete(
        f"/api/v1/autopilot/goals/{goal_id}", headers=auth_headers
    )
    assert deleted.status_code == 204
    remaining = (
        (
            await db.execute(
                select(AutopilotGoal).where(AutopilotGoal.id == UUID(goal_id))
            )
        )
        .scalars()
        .first()
    )
    assert remaining is None


async def test_goal_constraints_validated(client, auth_headers):
    conflict = await client.post(
        "/api/v1/autopilot/goals",
        json={
            "goal_text": "data work",
            "constraints": {"must_terms": ["python"], "never_terms": ["python"]},
        },
        headers=auth_headers,
    )
    assert conflict.status_code == 400, "must/never overlap rejected"

    bad_seniority = await client.post(
        "/api/v1/autopilot/goals",
        json={"goal_text": "data work", "constraints": {"seniority": ["wizard"]}},
        headers=auth_headers,
    )
    assert bad_seniority.status_code == 400


async def test_cadence_schedule_wiring(client, auth_headers, db):
    from app.models.schedule_model import Schedule

    created = await _goal(client, auth_headers)
    goal_id = created["id"]
    rows = await db.execute(
        select(Schedule).where(Schedule.kind == ScheduleKind.USER_AUTOPILOT.value)
    )
    assert rows.scalars().all() == [], "no cadence ⇒ no schedule"

    patched = await client.patch(
        f"/api/v1/autopilot/goals/{goal_id}",
        json={"cadence": {"type": "interval", "params": {"every_minutes": 1440}}},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    rows = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == ScheduleKind.USER_AUTOPILOT.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].payload == {"goal_id": goal_id}
    assert rows[0].task == "autopilot_run"

    removed = await client.patch(
        f"/api/v1/autopilot/goals/{goal_id}",
        json={"remove_cadence": True},
        headers=auth_headers,
    )
    assert removed.status_code == 200
    rows = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == ScheduleKind.USER_AUTOPILOT.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == []
    goal = await db.get(AutopilotGoal, UUID(goal_id))
    assert goal.cadence is None


# --------------------------------------------------------------------- e2e run


async def test_run_e2e_mock_provider(client, auth_headers, db, search_fixtures, kinds):
    """goal → plan → multi-search → filters → findings → notification."""
    from app.models.engagement_model import Notification

    created = await _goal(
        client,
        auth_headers,
        constraints={"salary_min": 1, "must_terms": ["programming"]},
    )
    service, user_id = _service(db, auth_headers)

    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    assert "skipped" not in result
    assert result["status"] in ("completed", "budget_aborted")
    assert result["resumed"] is False
    searches = [entry for entry in result["searches"] if entry.get("step") == "search"]
    assert len(searches) >= 2, "the mock planner emits multiple variants"
    assert all(entry["error"] == "" for entry in searches)

    findings = (
        (
            await db.execute(
                select(AutopilotFinding).where(
                    AutopilotFinding.run_id == UUID(result["run_id"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert findings, "mock curation delivers candidates with fit"
    for finding in findings:
        assert 0 <= float(finding.score) <= 10
        assert finding.why

    notification = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.dedup_key == f"autopilot:{result['run_id']}"
                )
            )
        )
        .scalars()
        .first()
    )
    assert notification is not None
    assert notification.source_ref["goal_id"] == created["id"]


async def test_runs_endpoint_transparency_timeline(
    client, auth_headers, db, search_fixtures
):
    """The run payload renders the 'what I searched & why' timeline."""
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    response = await client.get(
        f"/api/v1/autopilot/goals/{created['id']}/runs", headers=auth_headers
    )
    assert response.status_code == 200
    runs = response.json()
    assert runs and runs[0]["id"] == result["run_id"]
    timeline = runs[0]["searches_executed"]
    steps = [entry["step"] for entry in timeline]
    assert "search" in steps and "filter" in steps
    search_entry = next(e for e in timeline if e["step"] == "search")
    assert "query" in search_entry and "found" in search_entry
    filter_entry = next(e for e in timeline if e["step"] == "filter")
    assert {"seen", "never", "cooldown", "kept"} <= set(filter_entry)


# ------------------------------------------------------------------- filters


async def test_filters_honor_never_terms_and_seen(
    client, auth_headers, db, seeded_catalog, source, kinds
):
    """never-terms drop matches; seen/applied postings stay hidden."""
    from app.models.posting_model import PostingInteraction
    from tests.conftest import _add_posting_skill, _make_posting

    user_id = _uid(auth_headers)
    dev = await _make_posting(
        db, source, external_id="ex-dev", title="Python Developer"
    )
    qa = await _make_posting(db, source, external_id="ex-qa", title="QA Engineer")
    await _add_posting_skill(db, dev, "programming", 5, "must_have")
    await _add_posting_skill(db, qa, "programming", 5, "must_have")

    created = await _goal(
        client, auth_headers, constraints={"never_terms": ["qa"], "top_n": 5}
    )
    service = AutopilotService(db, checkpointer=InMemorySaver())
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    surfaced = [f["posting_id"] for f in result["findings"]]
    assert str(qa.id) not in surfaced, "never-term 'qa' must drop the QA posting"
    assert str(dev.id) in surfaced
    filter_entry = next(e for e in result["searches"] if e.get("step") == "filter")
    assert filter_entry["never"] == 1

    db.add(
        PostingInteraction(
            user_id=user_id, posting_id=dev.id, seen_at=datetime.now(timezone.utc)
        )
    )
    await db.commit()
    second = await _goal(client, auth_headers)
    result2 = await AutopilotService(db, checkpointer=InMemorySaver()).run_goal(
        UUID(second["id"]), user_id
    )
    await db.commit()
    surfaced2 = [f["posting_id"] for f in result2["findings"]]
    assert str(dev.id) not in surfaced2, "seen postings stay hidden"
    assert str(qa.id) in surfaced2


async def test_cooldown_suppresses_resurfacing(
    client, auth_headers, db, search_fixtures
):
    """A posting surfaced in a recent run isn't re-surfaced for N days."""
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    first = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    assert first["findings"], "first run surfaces candidates"

    repeat = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    first_ids = {f["posting_id"] for f in first["findings"]}
    repeat_ids = {f["posting_id"] for f in repeat["findings"]}
    assert not (first_ids & repeat_ids), "cooldown blocks re-surfacing within N days"
    filter_entry = next(e for e in repeat["searches"] if e.get("step") == "filter")
    assert filter_entry["cooldown"] >= 1


# ------------------------------------------------------------ budget abort


async def test_budget_abort_delivers_partials(
    client, auth_headers, db, search_fixtures
):
    """Run-level cap aborts cleanly; deterministic partials still ship."""
    created = await _goal(client, auth_headers, budget={"max_calls": 1})
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    assert result["status"] == "budget_aborted"
    run = await db.get(AutopilotRun, UUID(result["run_id"]))
    assert run.status == "budget_aborted"
    assert run.finished_at is not None
    assert result["findings"], "partials still delivered at budget"
    for finding in result["findings"]:
        assert finding["why"].startswith("Fit "), "fallback why is fit math"


# ------------------------------------------------------- constraint learning


async def test_feedback_learning_round_trip(client, auth_headers, db, search_fixtures):
    """hide → never_terms; more → must_terms; echoed back explicitly."""
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    assert result["findings"]
    finding = (
        (
            await db.execute(
                select(AutopilotFinding).order_by(AutopilotFinding.id).limit(1)
            )
        )
        .scalars()
        .first()
    )
    assert finding is not None

    hide = await client.post(
        f"/api/v1/autopilot/findings/{finding.id}/feedback",
        json={"feedback": "hide_like_this"},
        headers=auth_headers,
    )
    assert hide.status_code == 200, hide.text
    body = hide.json()
    assert body["learned_terms"], "learning is explicit"
    assert body["constraints"]["never_terms"]
    goal = await db.get(AutopilotGoal, UUID(created["id"]))
    assert set(body["learned_terms"]) <= set(goal.constraints["never_terms"])
    await db.refresh(finding)
    assert finding.dismissed_at is not None

    more = await client.post(
        f"/api/v1/autopilot/findings/{finding.id}/feedback",
        json={"feedback": "more_like_this"},
        headers=auth_headers,
    )
    assert more.status_code == 200
    await db.refresh(goal)
    assert goal.constraints["must_terms"], "'more' teaches must-terms"
    await db.refresh(finding)
    assert finding.dismissed_at is None, "un-dismissed on more-like-this"


async def test_pause_on_total_dismissal(client, auth_headers, db, search_fixtures):
    """Dismissing every finding of the latest run pauses the goal + nudges."""
    from app.models.engagement_model import Notification

    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    assert result["findings"]

    finding_rows = (
        (
            await db.execute(
                select(AutopilotFinding).where(
                    AutopilotFinding.run_id == UUID(result["run_id"])
                )
            )
        )
        .scalars()
        .all()
    )
    paused_flags = []
    for finding in finding_rows:
        response = await client.post(
            f"/api/v1/autopilot/findings/{finding.id}/feedback",
            json={"feedback": "hide_like_this"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        paused_flags.append(response.json()["goal_paused"])
    assert paused_flags[-1] is True, "the final dismissal pauses the goal"

    goal = await db.get(AutopilotGoal, UUID(created["id"]))
    assert goal.status == "paused"
    nudge = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.dedup_key == f"autopilot-stale:{created['id']}:paused"
                )
            )
        )
        .scalars()
        .all()
    )
    assert nudge, "refinement nudge emitted"


async def test_stale_goal_nudge_after_three_zero_runs(
    client, auth_headers, db, search_fixtures, kinds
):
    """N consecutive zero-finding runs → nudge; pausing stays manual."""
    from app.models.engagement_model import Notification

    created = await _goal(
        client, auth_headers, constraints={"never_terms": ["analyst"]}
    )
    service, user_id = _service(db, auth_headers)
    for _ in range(3):
        result = await service.run_goal(UUID(created["id"]), user_id)
        await db.commit()
        assert result["findings"] == []
    notifications = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.dedup_key == f"autopilot-stale:{created['id']}:3"
                )
            )
        )
        .scalars()
        .all()
    )
    assert notifications, "stale-goal nudge after 3 empty runs"
    goal = await db.get(AutopilotGoal, UUID(created["id"]))
    assert goal.status == "active", "stale nudge never auto-pauses"


# ------------------------------------------------- pause/resume + isolation


async def test_paused_goal_skips_runs(client, auth_headers, db, search_fixtures):
    created = await _goal(client, auth_headers)
    await client.patch(
        f"/api/v1/autopilot/goals/{created['id']}",
        json={"status": "paused"},
        headers=auth_headers,
    )
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    assert result.get("skipped") == "goal is paused"


async def test_cross_user_isolation(client, auth_headers, db, search_fixtures):
    from app.core.errors import PermissionDeniedError

    created = await _goal(client, auth_headers)
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "supersecret1"},
    )
    assert other.status_code == 201
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    listing = await client.get("/api/v1/autopilot/goals", headers=other_headers)
    assert listing.json() == []

    detail = await client.get(
        f"/api/v1/autopilot/goals/{created['id']}", headers=other_headers
    )
    assert detail.status_code == 403, "cross-user goal access denied"

    service = AutopilotService(db, checkpointer=InMemorySaver())
    try:
        await service.run_goal(UUID(created["id"]), _uid(other_headers))
        raise AssertionError("expected PermissionDeniedError")
    except PermissionDeniedError:
        pass


async def test_no_apply_invariant(client, auth_headers, db, search_fixtures):
    """Autopilot never applies: no interaction gains applied_at."""
    from app.models.posting_model import PostingInteraction

    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    assert result["findings"]
    rows = await db.execute(select(PostingInteraction))
    for interaction in rows.scalars().all():
        assert interaction.applied_at is None
        assert interaction.applied_via_url == ""


# ------------------------------------------------------------ graph internals


async def test_graph_resume_from_checkpoint(db, search_fixtures, auth_headers):
    """Family graph-testing rule: mid-flow state via update_state; a run
    whose checkpoint sits after `plan` continues (not restarts) on resume."""
    from app.ai.graphs.autopilot import (
        GraphDeps,
        build_autopilot_graph,
        initial_state,
    )

    user_id = _uid(auth_headers)
    goal = AutopilotGoal(
        user_id=user_id,
        goal_text="programming work",
        constraints={},
        budget={},
    )
    db.add(goal)
    await db.flush()
    run = AutopilotRun(goal_id=goal.id)
    db.add(run)
    await db.commit()

    deps = GraphDeps(db=db)
    graph = build_autopilot_graph(deps, InMemorySaver())
    config = {"configurable": {"thread_id": str(run.id)}}
    state = initial_state(
        user_id=user_id,
        goal_id=goal.id,
        run_id=run.id,
        goal_text=goal.goal_text,
        constraints={},
        budget={},
    )
    # Simulate a crash right after `plan`: checkpoint the full state plus
    # that node's output, as if the worker died before `search` started.
    graph.update_state(config, {**state, "plan": {"variants": []}}, as_node="plan")
    snapshot = graph.get_state(config)
    assert snapshot.values.get("plan"), "plan checkpointed"
    assert snapshot.next, "flow is paused mid-graph, not finished"

    final = await graph.ainvoke(None, config)
    assert final.get("searches") is not None
    assert final.get("findings") is not None


async def test_chat_tools_registered():
    """run_autopilot + my_autopilot register with chat audience."""
    from app.ai.tools.registry import list_tools

    tools = {t["key"]: t for t in list_tools()}
    assert tools["run_autopilot"]["audiences"] == ["chat"]
    assert tools["my_autopilot"]["audiences"] == ["chat"]
    assert tools["run_autopilot"]["requires_user"] is True


async def test_migration_head_is_0024():
    """Guard: the revision chain stays linear on a single head."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0024"]
