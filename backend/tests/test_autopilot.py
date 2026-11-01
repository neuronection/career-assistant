"""— Career Autopilot: goal CRUD, the checkpointed LangGraph run
(mock provider e2e), guardrails (budget abort, cooldown, pause), constraint
learning, transparency timeline, retrieval quality (grounded planner,
guaranteed must-terms, semantic + graph recall, replan), isolation and the
no-apply invariant."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.models.autopilot_model import AutopilotFinding, AutopilotGoal, AutopilotRun
from app.models.enums import BackgroundJobType, ScheduleKind
from app.services.growth.autopilot_service import AutopilotService
from app.services.scheduler.runner import KIND_TASKS
from tests.conftest import session_headers


@pytest.fixture
def autopilot_mock():
    """Script the AUTOPILOT_RUN mock fixture for one test, then restore.

    The graph module registers the default fixture at import time, so it
    must be imported BEFORE the script is saved — otherwise a lazy import
    inside the run would overwrite the script.
    """
    import app.ai.graphs.autopilot  # noqa: F401 — registers the default fixture
    from app.ai.gateway import MOCK_FIXTURES, register_mock_fixture
    from app.models.enums import AITaskType

    key = AITaskType.AUTOPILOT_RUN.value
    saved = MOCK_FIXTURES.get(key)

    def script(builder) -> None:
        register_mock_fixture(AITaskType.AUTOPILOT_RUN, builder)

    yield script
    if saved is not None:
        MOCK_FIXTURES[key] = saved


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


def _service(db, auth_headers=None) -> tuple[AutopilotService, str]:
    from tests.conftest import decode_session_token

    user_id = decode_session_token(auth_headers["Authorization"].split(" ", 1)[1])[0]
    return AutopilotService(db, checkpointer=InMemorySaver()), user_id


# ------------------------------------------------------------- registry wiring


def test_scheduler_maps_autopilot_kind_to_job():
    assert KIND_TASKS[ScheduleKind.USER_AUTOPILOT.value] == BackgroundJobType.AUTOPILOT_RUN.value


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

    deleted = await client.delete(f"/api/v1/autopilot/goals/{goal_id}", headers=auth_headers)
    assert deleted.status_code == 204
    remaining = (
        (await db.execute(select(AutopilotGoal).where(AutopilotGoal.id == UUID(goal_id))))
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
                select(Schedule).where(Schedule.kind == ScheduleKind.USER_AUTOPILOT.value)
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
                select(Schedule).where(Schedule.kind == ScheduleKind.USER_AUTOPILOT.value)
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
                select(AutopilotFinding).where(AutopilotFinding.run_id == UUID(result["run_id"]))
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
    assert notification.payload["link"] == f"/autopilot/runs/{result['run_id']}", (
        "the deliver notification deep-links the run page (plan 175)"
    )


async def test_runs_endpoint_transparency_timeline(client, auth_headers, db, search_fixtures):
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
    dev = await _make_posting(db, source, external_id="ex-dev", title="Python Developer")
    qa = await _make_posting(db, source, external_id="ex-qa", title="QA Engineer")
    await _add_posting_skill(db, dev, "programming", 5, "must_have")
    await _add_posting_skill(db, qa, "programming", 5, "must_have")

    created = await _goal(client, auth_headers, constraints={"never_terms": ["qa"], "top_n": 5})
    service = AutopilotService(db, checkpointer=InMemorySaver())
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    surfaced = [f["posting_id"] for f in result["findings"]]
    assert str(qa.id) not in surfaced, "never-term 'qa' must drop the QA posting"
    assert str(dev.id) in surfaced
    filter_entry = next(e for e in result["searches"] if e.get("step") == "filter")
    assert filter_entry["never"] == 1

    db.add(PostingInteraction(user_id=user_id, posting_id=dev.id, seen_at=datetime.now(UTC)))
    await db.commit()
    second = await _goal(client, auth_headers)
    result2 = await AutopilotService(db, checkpointer=InMemorySaver()).run_goal(
        UUID(second["id"]), user_id
    )
    await db.commit()
    surfaced2 = [f["posting_id"] for f in result2["findings"]]
    assert str(dev.id) not in surfaced2, "seen postings stay hidden"
    assert str(qa.id) in surfaced2


async def test_cooldown_suppresses_resurfacing(client, auth_headers, db, search_fixtures):
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


async def test_budget_abort_delivers_partials(client, auth_headers, db, search_fixtures):
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
        (await db.execute(select(AutopilotFinding).order_by(AutopilotFinding.id).limit(1)))
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
                select(AutopilotFinding).where(AutopilotFinding.run_id == UUID(result["run_id"]))
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

    created = await _goal(client, auth_headers, constraints={"never_terms": ["analyst"]})
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
    other_headers = session_headers(other)

    listing = await client.get("/api/v1/autopilot/goals", headers=other_headers)
    assert listing.json() == []

    detail = await client.get(f"/api/v1/autopilot/goals/{created['id']}", headers=other_headers)
    assert detail.status_code == 403, "cross-user goal access denied"

    service = AutopilotService(db, checkpointer=InMemorySaver())
    try:
        await service.run_goal(UUID(created["id"]), _uid(other_headers))
        raise AssertionError("expected PermissionDeniedError")
    except PermissionDeniedError:
        pass


async def test_no_apply_invariant(client, auth_headers, db, search_fixtures):
    """Autopilot never applies: no application row is ever created."""
    from app.models.application_model import Application

    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    assert result["findings"]
    rows = await db.execute(select(Application))
    assert rows.scalars().all() == []


# ------------------------------------------ findings feed + runs rail (175)


async def _feed_posting(db, external_id, **kw):
    from app.models.posting_model import JobPosting, JobSource

    source = kw.pop("source", None)
    if source is None:
        existing = (
            (await db.execute(select(JobSource).where(JobSource.key == "feed-main")))
            .scalars()
            .first()
        )
        if existing is not None:
            source = existing
        else:
            source = JobSource(key="feed-main", connector_key="synthetic", config={}, enabled=True)
            db.add(source)
            await db.flush()
    posting = JobPosting(
        source_id=source.id,
        external_id=external_id,
        title=kw.pop("title", f"Role {external_id}"),
        org=kw.pop("org", "FeedCo"),
        url=kw.pop("url", f"https://feed.example/{external_id}"),
        content_hash="0" * 64,
        # Long past: the posted_within filter reads the EFFECTIVE posted
        # date (coalesce(posted_at, created_at)) — unseeded rows would all
        # be "fresh" by ingestion.
        posted_at=kw.pop("posted_at", datetime(2026, 8, 1, tzinfo=UTC)),
        **kw,
    )
    db.add(posting)
    await db.flush()
    return posting


def _feed_finding(run, posting, score, created_at, **kw):
    return AutopilotFinding(
        run_id=run.id,
        posting_id=posting.id,
        score=score,
        why=kw.pop("why", f"Fit {score}/10."),
        evidence=kw.pop(
            "evidence",
            {
                "quotes": [f"{posting.title} needs programming"],
                "verified": True,
                "must_coverage": {"hits": 1, "total": 2},
                "breakdown": {
                    "skills": {"score": 7.0},
                    "prereqs": {"score": 7.0, "neutral": True, "disabled": True},
                },
            },
        ),
        created_at=created_at,
        dismissed_at=kw.pop("dismissed_at", None),
        **kw,
    )


async def _seed_feed(db, user_id):
    """Goal + two runs + three postings at fixed timestamps.

    r1 (older): posting-a 6.0, posting-b 8.0 (dismissed).
    r2 (newer, examined 40+12 in the timeline): posting-a 7.5,
    posting-b 9.1, posting-c 5.2 — the latest evaluations.
    """
    from app.models.autopilot_model import AutopilotRun

    goal = AutopilotGoal(user_id=user_id, goal_text="feed goal", constraints={}, budget={})
    db.add(goal)
    await db.flush()
    run1 = AutopilotRun(
        goal_id=goal.id,
        status="completed",
        tokens_used=100,
        searches_executed=[{"step": "search", "query": "old", "examined": 7}],
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        started_at=datetime(2026, 9, 1, tzinfo=UTC),
        finished_at=datetime(2026, 9, 1, minute=1, tzinfo=UTC),
    )
    run2 = AutopilotRun(
        goal_id=goal.id,
        status="completed",
        tokens_used=250,
        searches_executed=[
            {"step": "search", "query": "qa", "examined": 40},
            {"step": "search", "query": "data", "examined": 12},
        ],
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
        started_at=datetime(2026, 9, 5, tzinfo=UTC),
        finished_at=datetime(2026, 9, 5, minute=2, tzinfo=UTC),
    )
    db.add_all([run1, run2])
    await db.flush()
    a = await _feed_posting(db, "ex-a", title="Analyst A")
    b = await _feed_posting(db, "ex-b", title="Analyst B")
    c = await _feed_posting(db, "ex-c", title="Analyst C")
    db.add_all(
        [
            _feed_finding(run1, a, 6.0, datetime(2026, 9, 1, second=1, tzinfo=UTC)),
            _feed_finding(
                run1,
                b,
                8.0,
                datetime(2026, 9, 1, second=2, tzinfo=UTC),
                dismissed_at=datetime(2026, 9, 2, tzinfo=UTC),
            ),
            _feed_finding(run2, a, 7.5, datetime(2026, 9, 5, second=1, tzinfo=UTC)),
            _feed_finding(run2, b, 9.1, datetime(2026, 9, 5, second=2, tzinfo=UTC)),
            _feed_finding(run2, c, 5.2, datetime(2026, 9, 5, second=3, tzinfo=UTC)),
        ]
    )
    await db.commit()
    return goal, run1, run2, (a, b, c)


async def test_findings_feed_default_dedupes_and_hides_dismissed(client, auth_headers, db):
    user_id = _uid(auth_headers)
    goal, _run1, _run2, (a, b, c) = await _seed_feed(db, user_id)

    body = (await client.get("/api/v1/autopilot/findings", headers=auth_headers)).json()
    refs = [item["posting"]["ref"] for item in body["items"]]
    assert refs == [c.ref, b.ref, a.ref], "newest first, one row per posting"
    top = next(item for item in body["items"] if item["score"] == 9.1)
    assert top["posting"]["ref"] == b.ref
    assert top["score"] == 9.1
    assert top["quotes"] == ["Analyst B needs programming"]
    assert top["must_coverage"] == {"hits": 1, "total": 2}
    assert top["disabled_dims"] == 1, "plan-169 disabled dims counted"
    assert top["run_status"] == "completed"
    assert top["goal_id"] == str(goal.id)
    assert top["goal_text"] == "feed goal"
    assert top["applied"] is False
    assert top["dismissed_at"] is None
    assert all(item["score"] not in (6.0, 8.0) for item in body["items"]), (
        "older evaluations deduped away"
    )
    posting = top["posting"]
    assert posting["title"] == "Analyst B"
    assert posting["org"] == "FeedCo"
    assert posting["url"].startswith("https://feed.example/")
    assert posting["status"] == "new"
    assert posting["source"] == "feed-main"
    assert posting["extracted"] is False


async def test_findings_feed_state_param(client, auth_headers, db):
    user_id = _uid(auth_headers)
    _goal_row, _run1, _run2, (a, b, c) = await _seed_feed(db, user_id)

    all_body = (
        await client.get(
            "/api/v1/autopilot/findings", params={"state": "all"}, headers=auth_headers
        )
    ).json()
    assert len(all_body["items"]) == 3, "latest rows across states"

    dismissed = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"state": "dismissed"},
            headers=auth_headers,
        )
    ).json()
    assert len(dismissed["items"]) == 0, "only newest evaluations count"

    open_latest = (
        await client.get(
            "/api/v1/autopilot/findings", params={"state": "open"}, headers=auth_headers
        )
    ).json()
    assert {item["posting"]["ref"] for item in open_latest["items"]} == {a.ref, b.ref, c.ref}


async def test_findings_feed_latest_per_posting_toggle(client, auth_headers, db):
    user_id = _uid(auth_headers)
    _goal_row, run1, _run2, (a, b, _c) = await _seed_feed(db, user_id)

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"latest_per_posting": "false", "state": "all"},
            headers=auth_headers,
        )
    ).json()
    assert len(body["items"]) == 5, "history preserved"
    run_ids = {item["run_id"] for item in body["items"]}
    assert len(run_ids) == 2, "both runs' evaluations ride the flat feed"
    old_b = next(item for item in body["items"] if item["dismissed_at"] is not None)
    assert old_b["run_id"] == str(run1.id)
    assert old_b["posting"]["ref"] == b.ref
    assert a.ref in {item["posting"]["ref"] for item in body["items"]}


async def test_findings_feed_ownership_cross_user(client, auth_headers, db):
    user_id = _uid(auth_headers)
    await _seed_feed(db, user_id)
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "feed-other@example.com", "password": "supersecret1"},
    )
    assert other.status_code == 201
    other_headers = session_headers(other)
    body = (await client.get("/api/v1/autopilot/findings", headers=other_headers)).json()
    assert body["items"] == [], "another user's findings are invisible"
    rail = (await client.get("/api/v1/autopilot/runs", headers=other_headers)).json()
    assert rail == []


async def test_findings_feed_sort_score_orders_desc(client, auth_headers, db):
    user_id = _uid(auth_headers)
    await _seed_feed(db, user_id)
    body = (
        await client.get(
            "/api/v1/autopilot/findings", params={"sort": "score"}, headers=auth_headers
        )
    ).json()
    scores = [item["score"] for item in body["items"]]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 9.1


async def test_findings_feed_cursor_pages_without_repeats(client, auth_headers, db):
    user_id = _uid(auth_headers)
    await _seed_feed(db, user_id)
    seen = []
    cursor = None
    for _page in range(5):
        params = {"limit": 2, "sort": "score"}
        if cursor:
            params["cursor"] = cursor
        body = (
            await client.get("/api/v1/autopilot/findings", params=params, headers=auth_headers)
        ).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 3, "paged through the whole feed"
    assert len(seen) == len(set(seen)), "no repeats across pages"


async def test_findings_feed_applied_badge_from_join(client, auth_headers, db):
    from app.models.application_model import Application

    user_id = _uid(auth_headers)
    _goal_row, _run1, _run2, (a, _b, _c) = await _seed_feed(db, user_id)
    db.add(
        Application(
            user_id=user_id,
            posting_id=a.id,
            applied_at=datetime(2026, 9, 6, tzinfo=UTC),
        )
    )
    await db.commit()

    body = (await client.get("/api/v1/autopilot/findings", headers=auth_headers)).json()
    applied = {item["posting"]["ref"]: item["applied"] for item in body["items"]}
    assert applied[a.ref] is True, "badge derives from the applications join"
    assert len([flag for flag in applied.values() if not flag]) == 2


async def test_findings_feed_goal_and_run_filters(client, auth_headers, db):
    user_id = _uid(auth_headers)
    goal, run1, _run2, (_a, _b, _c) = await _seed_feed(db, user_id)

    by_goal = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"goal_id": str(goal.id), "state": "all", "latest_per_posting": "false"},
            headers=auth_headers,
        )
    ).json()
    assert len(by_goal["items"]) == 5, "everything under the goal"

    by_run = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={
                "run_id": str(run1.id),
                "state": "all",
                "latest_per_posting": "false",
            },
            headers=auth_headers,
        )
    ).json()
    assert {item["run_id"] for item in by_run["items"]} == {str(run1.id)}
    assert all(item["goal_text"] == "feed goal" for item in by_run["items"])
    assert all(item["goal_id"] == str(goal.id) for item in by_run["items"])


async def test_runs_rail_rows_carry_counts(client, auth_headers, db):
    from app.models.application_model import Application

    user_id = _uid(auth_headers)
    goal, run1, run2, (a, _b, _c) = await _seed_feed(db, user_id)

    rows = (await client.get("/api/v1/autopilot/runs", headers=auth_headers)).json()
    assert [row["id"] for row in rows] == [str(run2.id), str(run1.id)], "newest first"
    top = rows[0]
    assert top["goal_id"] == str(goal.id)
    assert top["goal_text"] == "feed goal"
    assert top["status"] == "completed"
    assert top["tokens_used"] == 250
    assert top["findings_count"] == 3, "live findings"
    assert top["examined_sum"] == 52, "Σ the timeline's examined"
    assert "searches_executed" not in top, "the timeline stays on run detail"
    older = rows[1]
    assert older["findings_count"] == 1, "the dismissed evaluation is not live"
    assert older["examined_sum"] == 7

    db.add(Application(user_id=user_id, posting_id=a.id))
    await db.commit()
    rows = (await client.get("/api/v1/autopilot/runs", headers=auth_headers)).json()
    assert rows[0]["findings_count"] == 3, "applied findings stay on the rail"


# ------------------------------------------------- S2 filters, facets, sort


async def _seed_feed_extra(db, goal):
    """A second source + a fresh remote mid posting with its own finding."""
    from app.models.autopilot_model import AutopilotRun
    from app.models.posting_model import JobPosting, JobSource
    from app.services.growth.autopilot_service import _utcnow

    other = JobSource(key="feed-other", connector_key="synthetic", config={}, enabled=True)
    db.add(other)
    await db.flush()
    fresh = JobPosting(
        source_id=other.id,
        external_id="ex-fresh",
        title="Fresh Remote",
        org="FeedCo",
        url="https://feed.example/fresh",
        content_hash="1" * 64,
        seniority="mid",
        onsite_policy="remote",
        posted_at=_utcnow() - timedelta(hours=2),
    )
    db.add(fresh)
    run = AutopilotRun(
        goal_id=goal.id,
        status="completed",
        searches_executed=[],
        created_at=datetime(2026, 9, 7, tzinfo=UTC),
    )
    db.add(run)
    await db.flush()
    db.add(_feed_finding(run, fresh, 6.4, datetime(2026, 9, 7, second=1, tzinfo=UTC)))
    await db.commit()
    return fresh


async def test_findings_feed_min_score_and_org_filters(client, auth_headers, db):
    user_id = _uid(auth_headers)
    _goal_row, _run1, _run2, (_a, _b, _c) = await _seed_feed(db, user_id)

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"min_score": 7},
            headers=auth_headers,
        )
    ).json()
    scores = [item["score"] for item in body["items"]]
    assert scores and all(score >= 7 for score in scores)

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"org": "feedco"},
            headers=auth_headers,
        )
    ).json()
    assert len(body["items"]) == 3, "org ilike is case-insensitive"
    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"org": "nowhere"},
            headers=auth_headers,
        )
    ).json()
    assert body["items"] == []


async def test_findings_feed_posting_axes_filters(client, auth_headers, db):
    user_id = _uid(auth_headers)
    goal, _run1, _run2, (_a, _b, _c) = await _seed_feed(db, user_id)
    fresh = await _seed_feed_extra(db, goal)

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"source": "feed-other"},
            headers=auth_headers,
        )
    ).json()
    assert [item["posting"]["ref"] for item in body["items"]] == [fresh.ref]

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"seniority": "mid"},
            headers=auth_headers,
        )
    ).json()
    assert [item["posting"]["ref"] for item in body["items"]] == [fresh.ref]

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"remote": "true"},
            headers=auth_headers,
        )
    ).json()
    assert {item["posting"]["ref"] for item in body["items"]} == {fresh.ref}

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"posted_within": "24h"},
            headers=auth_headers,
        )
    ).json()
    assert [item["posting"]["ref"] for item in body["items"]] == [fresh.ref]

    body = await client.get(
        "/api/v1/autopilot/findings",
        params={"posted_within": "bogus"},
        headers=auth_headers,
    )
    assert body.status_code == 400


async def test_findings_feed_coverage_min_and_hide_applied(client, auth_headers, db):
    from app.models.application_model import Application

    user_id = _uid(auth_headers)
    _goal_row, _run1, _run2, (a, _b, _c) = await _seed_feed(db, user_id)
    db.add(Application(user_id=user_id, posting_id=a.id))
    await db.commit()

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"coverage_min": 1},
            headers=auth_headers,
        )
    ).json()
    assert body["items"], "every seeded finding carries must_coverage hits ≥ 1"
    assert all((item["must_coverage"] or {}).get("hits", 0) >= 1 for item in body["items"])

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"coverage_min": 5},
            headers=auth_headers,
        )
    ).json()
    assert body["items"] == [], "coverage beyond the seeded hits filters everything out"

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"hide_applied": "true", "state": "all", "latest_per_posting": "false"},
            headers=auth_headers,
        )
    ).json()
    assert not [item for item in body["items"] if item["applied"]], (
        "hide_applied drops the applied row"
    )


async def test_findings_feed_facets_are_self_excluding(client, auth_headers, db):
    from app.models.autopilot_model import AutopilotGoal, AutopilotRun

    user_id = _uid(auth_headers)
    goal, _run1, _run2, (_a, _b, _c) = await _seed_feed(db, user_id)
    fresh = await _seed_feed_extra(db, goal)
    other_goal = AutopilotGoal(user_id=user_id, goal_text="second goal", constraints={}, budget={})
    db.add(other_goal)
    await db.flush()
    other_run = AutopilotRun(goal_id=other_goal.id, status="completed", searches_executed=[])
    db.add(other_run)
    await db.flush()
    another = await _feed_posting(db, "ex-second", title="Second Goal Role")
    db.add(_feed_finding(other_run, another, 4.4, datetime(2026, 9, 9, tzinfo=UTC)))
    await db.commit()

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"source": "feed-other"},
            headers=auth_headers,
        )
    ).json()
    facets = body["facets"]
    assert facets["source"].get("feed-other") == 1
    assert facets["source"].get("feed-main") == 4, "selected source stays counted"
    assert facets["seniority"].get("mid") == 1, "seniority recounted without its filter"
    assert facets["state"] == {"open": 1, "dismissed": 0}, (
        "state facets count the other-filters' set (source stays applied)"
    )

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"goal_id": str(goal.id)},
            headers=auth_headers,
        )
    ).json()
    facets = body["facets"]
    assert facets["goal"].get(str(goal.id)) == 4, "selected goal stays counted"
    assert facets["goal"].get(str(other_goal.id)) == 1, "other goals ignore the filter"

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"state": "dismissed", "latest_per_posting": "false"},
            headers=auth_headers,
        )
    ).json()
    assert body["facets"]["state"]["dismissed"] == 1, (
        "the dismissed old evaluation counts once the dedupe is off"
    )
    assert body["facets"]["state"]["open"] == 6, "state facet is self-excluding"

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"seniority": "mid"},
            headers=auth_headers,
        )
    ).json()
    assert [item["posting"]["ref"] for item in body["items"]] == [fresh.ref]
    assert body["facets"]["source"] == {"feed-other": 1}, (
        "source facet counts the seniority-filtered set (only its own dimension is skipped)"
    )
    assert body["facets"]["seniority"].get("mid") == 1, "selected seniority stays counted"


async def test_findings_feed_cursor_stable_for_both_sorts(client, auth_headers, db):
    """Keyset pages through the whole feed with no repeats for BOTH sorts,
    including a score tie (the tie group is reached exactly once)."""
    user_id = _uid(auth_headers)
    goal, _run1, _run2, (_a, _b, _c) = await _seed_feed(db, user_id)
    from app.models.autopilot_model import AutopilotRun

    tie_run = AutopilotRun(goal_id=goal.id, status="completed", searches_executed=[])
    db.add(tie_run)
    await db.flush()
    tie = await _feed_posting(db, "ex-tie", title="Tie Role")
    db.add(_feed_finding(tie_run, tie, 7.5, datetime(2026, 9, 6, tzinfo=UTC)))
    await db.commit()

    for sort in ("newest", "score"):
        seen: list[str] = []
        cursor: str | None = None
        for _page in range(10):
            params: dict = {"limit": 2, "sort": sort}
            if cursor:
                params["cursor"] = cursor
            body = (
                await client.get("/api/v1/autopilot/findings", params=params, headers=auth_headers)
            ).json()
            seen.extend(item["id"] for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert len(seen) == 4, f"{sort}: paged through the whole feed"
        assert len(seen) == len(set(seen)), f"{sort}: no repeats across pages"

    body = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"sort": "score", "limit": 2},
            headers=auth_headers,
        )
    ).json()
    assert any(item["score"] == 7.5 for item in body["items"]), (
        "the tie group starts a page cleanly"
    )


async def test_findings_feed_cursor_survives_re_rank_drift(client, auth_headers, db):
    """Documented drift semantics: the keyset runs over the deduped row's
    own (sort_key, id). A newer evaluation displacing the cursor row
    between pages is accepted drift — page 2 still returns, never loops,
    never repeats page 1's ids."""
    user_id = _uid(auth_headers)
    _goal_row, _run1, run2, (a, _b, _c) = await _seed_feed(db, user_id)

    page1 = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"sort": "newest", "limit": 2},
            headers=auth_headers,
        )
    ).json()
    cursor = page1["next_cursor"]
    assert cursor is not None

    from app.models.autopilot_model import AutopilotRun

    drift_run = AutopilotRun(goal_id=run2.goal_id, status="completed", searches_executed=[])
    db.add(drift_run)
    await db.flush()
    db.add(_feed_finding(drift_run, a, 9.9, datetime(2026, 9, 8, tzinfo=UTC)))
    await db.commit()

    page2 = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"sort": "newest", "limit": 2, "cursor": cursor},
            headers=auth_headers,
        )
    ).json()
    page1_ids = {item["id"] for item in page1["items"]}
    assert not page1_ids.intersection(item["id"] for item in page2["items"])


# ------------------------------------------------------ S4 applications + bulk


async def test_bulk_dismiss_marks_only_that_run(client, auth_headers, db):
    """Dismiss-all marks only that run's open findings; no constraint
    learning, no feedback overwrite; the filters respect it."""
    from app.models.autopilot_model import AutopilotGoal, AutopilotRun

    user_id = _uid(auth_headers)
    goal, run1, run2, (_a, _b, _c) = await _seed_feed(db, user_id)
    other_goal = AutopilotGoal(
        user_id=user_id, goal_text="untouched goal", constraints={}, budget={}
    )
    db.add(other_goal)
    await db.flush()
    other_run = AutopilotRun(goal_id=other_goal.id, status="completed", searches_executed=[])
    db.add(other_run)
    await db.flush()
    another = await _feed_posting(db, "ex-other", title="Other Run Role")
    db.add(_feed_finding(other_run, another, 5.5, datetime(2026, 9, 9, tzinfo=UTC)))
    await db.commit()

    response = await client.post(
        f"/api/v1/autopilot/runs/{run2.id}/dismiss-findings", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["dismissed"] == 3, "every open finding of the run"

    feed = (
        await client.get(
            "/api/v1/autopilot/findings",
            params={"state": "all", "latest_per_posting": "false"},
            headers=auth_headers,
        )
    ).json()
    run2_ids = {item["id"] for item in feed["items"] if item["run_id"] == str(run2.id)}
    assert run2_ids and all(
        item["dismissed_at"] is not None for item in feed["items"] if item["run_id"] == str(run2.id)
    ), "that run's findings are dismissed"
    untouched = [
        item
        for item in feed["items"]
        if item["run_id"] in (str(run1.id), str(other_run.id)) and item["dismissed_at"] is None
    ]
    assert len(untouched) == 2, "other runs' open findings stay open"

    await db.refresh(goal)
    assert goal.constraints == {}, "bulk dismiss learns nothing"
    body = (await client.get("/api/v1/autopilot/findings", headers=auth_headers)).json()
    assert [item["run_id"] for item in body["items"]] == [str(other_run.id)], (
        "the default open+latest feed keeps only the untouched run's rows"
    )

    foreign = await client.post(
        f"/api/v1/autopilot/runs/{other_run.id}/dismiss-findings",
        headers=auth_headers,
    )
    assert foreign.status_code == 200
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "bulk-other@example.com", "password": "supersecret1"},
    )
    assert other.status_code == 201
    other_headers = session_headers(other)
    missing = await client.post(
        f"/api/v1/autopilot/runs/{run2.id}/dismiss-findings", headers=other_headers
    )
    assert missing.status_code == 404, "a foreign run answers the same 404"


async def test_bulk_dismiss_unknown_run_404(client, auth_headers):
    response = await client.post(
        "/api/v1/autopilot/runs/00000000-0000-0000-0000-000000000001/dismiss-findings",
        headers=auth_headers,
    )
    assert response.status_code == 404


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
    assert any(
        str(entry.get("rationale") or "").startswith("curated graph expansion")
        for entry in final.get("searches") or []
    ), "the resumed flow traverses the graph sweep"


async def test_chat_tools_registered():
    """run_autopilot + my_autopilot register with chat audience."""
    from app.ai.tools.registry import list_tools

    tools = {t["key"]: t for t in list_tools()}
    assert tools["run_autopilot"]["audiences"] == ["chat"]
    assert tools["my_autopilot"]["audiences"] == ["chat"]
    assert tools["run_autopilot"]["requires_user"] is True


async def test_migration_head_is_linear():
    """Guard: the revision chain stays linear on a single head."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0084"]


# --------------------------------------------------- S1 planner grounding


async def test_profile_context_feeds_the_plan_state(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    """`collect_profile_context` composes skills/education/location and
    `initial_state` carries it into the first checkpoint (plan 158 S1.1)."""
    from app.ai.graphs.autopilot import collect_profile_context, initial_state
    from app.models.taxonomy_model import Skill
    from app.models.user_model import UserSkill

    user_id = _uid(auth_headers)
    programming = (
        (await db.execute(select(Skill).where(Skill.key == "programming"))).scalars().first()
    )
    db.add(UserSkill(user_id=user_id, skill_id=programming.id, level=7))
    await db.commit()

    context = await collect_profile_context(db, user_id, {"seniority": ["junior"]})
    assert context["skills"] == [{"key": "programming", "level": 7}]
    assert context["education_level"] == "high_school"
    assert context["country"] == "Greece" and context["city"] == "Athens"
    assert context["target_seniority"] == ["junior"]

    state = initial_state(
        user_id=user_id,
        goal_id=UUID(int=1),
        run_id=UUID(int=2),
        goal_text="data work",
        constraints={},
        budget={},
        profile_context=context,
    )
    assert state["profile_context"] == context
    assert (
        initial_state(
            user_id=user_id,
            goal_id=UUID(int=1),
            run_id=UUID(int=2),
            goal_text="data work",
            constraints={},
            budget={},
        )["profile_context"]
        == {}
    )


async def test_plan_prompt_carries_the_vocabulary_and_skill_neighbourhood(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    """Closed enums + allowed keys in the system prompt; the user's own
    skills then their graph neighbourhood precede frequency padding
    (plan 158 S1.2)."""
    from app.ai.graphs.autopilot import (
        PLAN_SKILL_LIMIT,
        _plan_system,
        _plan_user_prompt,
        plan_vocabulary,
    )
    from app.models.taxonomy_model import Skill
    from app.models.user_model import UserSkill
    from app.services.postings.explore_service import (
        ALLOWED_FILTER_KEYS,
        BENEFIT_KIND_VALUES,
        REMOTE_VALUES,
        SCHEDULE_CUE_VALUES,
        SENIORITY_VALUES,
        SKILL_EXPAND_MODES,
        SKILL_MODE_VALUES,
    )

    user_id = _uid(auth_headers)
    skills = {
        key: (await db.execute(select(Skill).where(Skill.key == key))).scalars().first()
        for key in ("programming", "data-analysis")
    }
    skills["data-analysis"].parent_id = skills["programming"].id
    db.add(UserSkill(user_id=user_id, skill_id=skills["programming"].id, level=7))
    await db.commit()

    system = _plan_system()
    for key in ALLOWED_FILTER_KEYS:
        assert key in system
    for value in (*SENIORITY_VALUES, *REMOTE_VALUES, *SCHEDULE_CUE_VALUES, *BENEFIT_KIND_VALUES):
        assert value in system
    assert f"skill_expand values: {', '.join(SKILL_EXPAND_MODES)}" in system
    assert f"skill_mode values: {', '.join(SKILL_MODE_VALUES)}" in system
    assert "keywords" in system and "q" in system

    vocabulary = await plan_vocabulary(db, user_id)
    assert vocabulary["skills"][0] == "programming", "own skill first"
    assert vocabulary["skills"][1] == "data-analysis", "then the graph neighbourhood"
    assert len(vocabulary["skills"]) <= PLAN_SKILL_LIMIT
    assert vocabulary["families"]
    assert isinstance(vocabulary["sources"], list)

    prompt = json.loads(
        _plan_user_prompt(
            {"goal_text": "data work", "constraints": {}},
            vocabulary,
        )
    )
    assert prompt["skill_keys"][:2] == ["programming", "data-analysis"]
    assert set(prompt["valid_filter_keys"]) == set(ALLOWED_FILTER_KEYS)
    assert prompt["family_keys"] == vocabulary["families"]
    assert prompt["source_keys"] == vocabulary["sources"]


def test_mock_planner_emits_only_valid_keys_and_keyword_variants():
    """The deterministic mock demonstrates the contract it pins
    (plan 158 S1.4): keyword-array variants, valid keys only."""
    from app.ai.graphs.autopilot import _mock_autopilot
    from app.ai.schemas import SearchPlan
    from app.services.postings.explore_service import (
        ALLOWED_FILTER_KEYS,
        parse_explore_filters,
    )

    prompt = json.dumps(
        {
            "goal": "junior QA or data job where I can use programming",
            "must_terms": ["programming"],
            "target_families": ["technology"],
            "seniority": ["junior"],
            "skill_keys": ["programming", "data-analysis"],
        }
    )
    plan = SearchPlan.model_validate(_mock_autopilot(SearchPlan, prompt))
    assert len(plan.variants) >= 3
    for variant in plan.variants:
        assert set(variant.filters) <= ALLOWED_FILTER_KEYS
        parse_explore_filters(dict(variant.filters))
    keyword_variants = [v for v in plan.variants if v.filters.get("keywords")]
    assert keyword_variants, "keyword-style variants, not natural-language q"
    assert all(v.query == "" for v in keyword_variants)
    assert any(v.filters.get("skills") for v in plan.variants)


async def test_unknown_filter_key_degrades_that_variant_only(
    client, auth_headers, db, search_fixtures, autopilot_mock
):
    """A variant outside the vocabulary is dropped with a timeline error;
    the other variants still deliver (plan 158 S1.5)."""
    from app.ai.graphs.autopilot import _mock_autopilot
    from app.ai.schemas import SearchPlan

    def scripted(schema, user_prompt):
        if schema is SearchPlan:
            return {
                "variants": [
                    {
                        "rationale": "invented filter key",
                        "query": "",
                        "filters": {"wizardry": ["yes"]},
                    },
                    {"rationale": "broad net", "query": "", "filters": {}},
                ]
            }
        return _mock_autopilot(schema, user_prompt)

    autopilot_mock(scripted)
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    searches = [entry for entry in result["searches"] if entry.get("step") == "search"]
    broken = next(entry for entry in searches if entry.get("rationale") == "invented filter key")
    assert "wizardry" in broken["error"]
    assert any(entry["error"] == "" and entry["found"] > 0 for entry in searches)
    assert result["findings"]


# ------------------------------------------------- S2 must-term guarantees


async def test_must_hits_outrank_fit_when_ranking(client, auth_headers, db, search_fixtures):
    """A must-term-covering candidate outranks a higher-fit candidate
    without it, and the coverage lands in the persisted evidence
    (plan 158 S2)."""
    from sqlalchemy import update

    from app.models.posting_model import JobPosting

    a, _b, _c = search_fixtures
    await db.execute(update(JobPosting).where(JobPosting.id == a.id).values(title="Covered Role"))
    await db.commit()

    created = await _goal(
        client,
        auth_headers,
        constraints={"must_terms": ["covered"], "top_n": 2},
    )
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    assert result["findings"], "coverage never gates a candidate out"
    assert result["findings"][0]["posting_id"] == str(a.id), (
        "the must-term match ranks first even at a lower fit"
    )
    rows = (
        (
            await db.execute(
                select(AutopilotFinding).where(AutopilotFinding.run_id == UUID(result["run_id"]))
            )
        )
        .scalars()
        .all()
    )
    coverage = {row.posting_id: row.evidence["must_coverage"] for row in rows}
    assert coverage[a.id] == {"hits": 1, "total": 1}
    assert all(
        entry == {"hits": 0, "total": 1} for pid, entry in coverage.items() if pid != a.id
    ), "candidates without the must-term carry zero coverage, not a missing field"


def test_curate_prompt_carries_must_coverage():
    """Curation sees each candidate's coverage against the goal's total
    (plan 158 S2.2)."""
    from app.ai.graphs.autopilot import _curate_user_prompt

    prompt = json.loads(
        _curate_user_prompt(
            {
                "goal_text": "data work",
                "constraints": {"must_terms": ["sql", "python"]},
            },
            [
                {"title": "Analyst", "org": "Extro", "fit": 7.5, "must_hits": 2},
                {"title": "Reporter", "org": "Num", "fit": 8.5},
            ],
        )
    )
    assert prompt["candidates"][0]["must_hits"] == 2
    assert prompt["candidates"][0]["must_total"] == 2
    assert prompt["candidates"][1]["must_hits"] == 0


# ------------------------------------------------------- S3 semantic recall


def _narrow_planner(extra: dict | None = None):
    """A scripted planner whose variants match no posting by text, so only
    a recall sweep can surface one."""

    def scripted(schema, user_prompt):
        from app.ai.graphs.autopilot import _mock_autopilot
        from app.ai.schemas import SearchPlan

        if schema is SearchPlan:
            return {
                "variants": [
                    {
                        "rationale": "narrow lexical probe",
                        "query": "",
                        "filters": {"keywords": ["zzz-no-such-role"]},
                        **(extra or {}),
                    }
                ]
            }
        return _mock_autopilot(schema, user_prompt)

    return scripted


async def _embed_for(db, posting, text: str) -> None:
    """Store the deterministic mock embedding of `text` on one posting."""
    from app.ai.gateway import embed_texts
    from app.services.embedding_service import KIND_POSTING, EmbeddingService

    vector = (await embed_texts(db, [text]))[0]
    await EmbeddingService(db).upsert_embedding(
        KIND_POSTING, posting.id, f"embedding fixture for {posting.ref}", vector=vector
    )


async def test_semantic_sweep_surfaces_a_posting_no_variant_matches(
    client, auth_headers, db, seeded_catalog, source, kinds, autopilot_mock
):
    """Embedding recall adds postings the lexical variants cannot see
    (plan 158 S3.1/S3.4)."""
    from tests.conftest import _make_posting

    autopilot_mock(_narrow_planner())
    goal_text = "junior data analyst role, remote, where I can use programming"
    posting = await _make_posting(
        db,
        source,
        external_id="ex-embed",
        title="Zebra wrangler",
        org="Zoological Hotel",
        skills_raw=[],
        raw={"description": "Wrangling striped animals at the hotel lobby."},
    )
    await _embed_for(db, posting, goal_text)

    created = await _goal(client, auth_headers, goal_text=goal_text, constraints={})
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    assert str(posting.id) in [finding["posting_id"] for finding in result["findings"]]
    sweep = next(
        entry
        for entry in result["searches"]
        if entry.get("rationale") == "semantic sweep over stored posting embeddings"
    )
    assert sweep["step"] == "search" and sweep["query"] == ""
    assert sweep["found"] == 1
    assert sweep["error"] == ""


async def test_semantic_sweep_degrades_without_embeddings(
    client, auth_headers, db, search_fixtures, autopilot_mock
):
    """No stored vectors → no error, no crash, lexical results unaffected
    (plan 158 S3.2)."""
    autopilot_mock(_narrow_planner())
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    sweep = next(
        entry
        for entry in result["searches"]
        if entry.get("rationale") == "semantic sweep over stored posting embeddings"
    )
    assert sweep["found"] == 0 and sweep["error"] == ""
    assert result["status"] == "completed"


async def test_semantic_sweep_degrades_on_a_dim_mismatch(
    client, auth_headers, db, search_fixtures, source, autopilot_mock
):
    """A stored vector of another dimension is skipped, not fatal: the
    sweep returns no semantic candidates, notes the skip and the lexical
    run completes (plan 158 S3.2)."""
    from app.services.embedding_service import KIND_POSTING, EmbeddingService
    from tests.conftest import _make_posting

    autopilot_mock(_narrow_planner())
    posting = await _make_posting(
        db,
        source,
        external_id="ex-embed-wrong-dim",
        title="Zebra wrangler",
        org="Zoological Hotel",
        skills_raw=[],
        raw={"description": "Wrangling striped animals at the hotel lobby."},
    )
    await EmbeddingService(db).upsert_embedding(
        KIND_POSTING,
        posting.id,
        "embedding fixture with a foreign dimension",
        vector=[0.1, 0.2, 0.3],
    )
    await db.commit()

    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    sweep = next(
        entry
        for entry in result["searches"]
        if entry.get("rationale") == "semantic sweep over stored posting embeddings"
    )
    assert sweep["found"] == 0
    assert "dimension mismatch" in sweep["error"]
    assert result["status"] == "completed"


async def test_semantic_sweep_skips_gated_postings(
    client, auth_headers, db, seeded_catalog, source, kinds, autopilot_mock
):
    """A seen posting is excluded from the sweep like everywhere else
    (plan 158 S3.4, S4.7)."""
    from app.models.posting_model import PostingInteraction
    from tests.conftest import _make_posting

    autopilot_mock(_narrow_planner())
    goal_text = "junior data analyst role, remote, where I can use programming"
    posting = await _make_posting(
        db,
        source,
        external_id="ex-embed-seen",
        title="Zebra wrangler",
        org="Zoological Hotel",
        skills_raw=[],
        raw={"description": "Wrangling striped animals at the hotel lobby."},
    )
    await _embed_for(db, posting, goal_text)
    db.add(
        PostingInteraction(
            user_id=_uid(auth_headers), posting_id=posting.id, seen_at=datetime.now(UTC)
        )
    )
    await db.commit()

    created = await _goal(client, auth_headers, goal_text=goal_text, constraints={})
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    assert result["findings"] == []
    sweep = next(
        entry
        for entry in result["searches"]
        if entry.get("rationale") == "semantic sweep over stored posting embeddings"
    )
    assert sweep["found"] == 0


# --------------------------------------------- S4 recall depth + performance


async def test_search_timeline_reports_examined(client, auth_headers, db, search_fixtures):
    """Each search entry says how many postings it actually examined, next
    to the filtered total (plan 158 S4.3)."""
    from app.ai.graphs.autopilot import SEARCH_LIMIT

    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    searches = [entry for entry in result["searches"] if entry.get("step") == "search"]
    assert searches
    for entry in searches:
        assert "examined" in entry
        assert 0 <= entry["examined"] <= SEARCH_LIMIT


async def test_search_windows_hold_fresh_candidates_only(
    client, auth_headers, db, seeded_catalog, source, kinds
):
    """The fit window excludes seen/applied/hidden postings in SQL, so a
    mostly-seen catalog still fills its slots with fresh candidates
    (plan 158 S4.7)."""
    from app.models.posting_model import PostingInteraction
    from tests.conftest import _make_posting

    user_id = _uid(auth_headers)
    postings = []
    for index in range(6):
        postings.append(
            await _make_posting(
                db, source, external_id=f"fresh-{index}", title=f"Fresh Role {index}"
            )
        )
    fresh = postings[-1]
    for posting in postings[:-1]:
        db.add(
            PostingInteraction(user_id=user_id, posting_id=posting.id, seen_at=datetime.now(UTC))
        )
    await db.commit()

    created = await _goal(client, auth_headers, constraints={"top_n": 3})
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    assert [finding["posting_id"] for finding in result["findings"]] == [str(fresh.id)]
    filter_entry = next(entry for entry in result["searches"] if entry.get("step") == "filter")
    assert filter_entry["seen"] == 0, "seen postings never reach the filter node"


async def test_candidate_cap_bounds_the_checkpoint(
    db, auth_headers, seeded_catalog, source, kinds, autopilot_mock
):
    """A run that merges more than CANDIDATE_CAP postings checkpoints at
    most CANDIDATE_CAP of them (plan 158 S4.6)."""
    from app.ai.graphs.autopilot import (
        CANDIDATE_CAP,
        GraphDeps,
        build_autopilot_graph,
        initial_state,
    )
    from app.ai.schemas import SearchPlan
    from tests.conftest import _make_posting

    names = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
    for index in range(CANDIDATE_CAP + 12):
        await _make_posting(
            db,
            source,
            external_id=f"cap-{index}",
            title=f"{names[index % len(names)].title()} Capped Role {index}",
        )

    def scripted(schema, user_prompt):
        from app.ai.graphs.autopilot import _mock_autopilot

        if schema is SearchPlan:
            return {
                "variants": [
                    {"rationale": f"sweep {name}", "query": "", "filters": {"keywords": [name]}}
                    for name in names
                ]
            }
        return _mock_autopilot(schema, user_prompt)

    autopilot_mock(scripted)
    user_id = _uid(auth_headers)
    goal = AutopilotGoal(user_id=user_id, goal_text="capped sweep", constraints={}, budget={})
    db.add(goal)
    await db.flush()
    run = AutopilotRun(goal_id=goal.id)
    db.add(run)
    await db.commit()

    graph = build_autopilot_graph(GraphDeps(db=db), InMemorySaver())
    config = {"configurable": {"thread_id": str(run.id)}}
    await graph.ainvoke(
        initial_state(
            user_id=user_id,
            goal_id=goal.id,
            run_id=run.id,
            goal_text="capped sweep",
            constraints={},
            budget={},
        ),
        config,
    )
    await db.commit()

    snapshots = [
        snapshot.values.get("candidates") or [] for snapshot in graph.get_state_history(config)
    ]
    assert max(len(candidates) for candidates in snapshots) == CANDIDATE_CAP


# --------------------------------------------------- S5 replan once on empty


def _empty_then_broad():
    """First plan finds nothing; the replan broadens to a filterless net."""

    def scripted(schema, user_prompt):
        from app.ai.graphs.autopilot import _mock_autopilot
        from app.ai.schemas import SearchPlan

        if schema is SearchPlan:
            ctx = json.loads(user_prompt)
            if ctx.get("previous_variants") is not None:
                return {
                    "variants": [
                        {"rationale": "widened net", "query": "", "filters": {}},
                    ]
                }
            return {
                "variants": [
                    {
                        "rationale": "narrow lexical probe",
                        "query": "",
                        "filters": {"keywords": ["zzz-no-such-role"]},
                    }
                ]
            }
        return _mock_autopilot(schema, user_prompt)

    return scripted


def _never_broad():
    """Both passes stay narrow: nothing is ever found."""

    def scripted(schema, user_prompt):
        from app.ai.graphs.autopilot import _mock_autopilot
        from app.ai.schemas import SearchPlan

        if schema is SearchPlan:
            return {
                "variants": [
                    {
                        "rationale": "narrow lexical probe",
                        "query": "",
                        "filters": {"keywords": ["zzz-no-such-role"]},
                    }
                ]
            }
        return _mock_autopilot(schema, user_prompt)

    return scripted


async def _autopilot_calls(db, auth_headers) -> int:
    from app.models.ai_model import AIGeneration

    rows = await db.execute(
        select(AIGeneration).where(
            AIGeneration.user_id == _uid(auth_headers),
            AIGeneration.task_type == "autopilot_run",
        )
    )
    return len(rows.scalars().all())


async def test_replan_recovers_a_thin_first_pass(
    client, auth_headers, db, search_fixtures, autopilot_mock
):
    """All variants come back empty → one broaden pass → findings ship
    (plan 158 S5.1/S5.5)."""
    autopilot_mock(_empty_then_broad())
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    assert result["findings"], "the widen pass delivers"
    steps = [entry.get("step") for entry in result["searches"]]
    assert steps.count("replan") == 1
    replan_entry = next(entry for entry in result["searches"] if entry.get("step") == "replan")
    assert replan_entry["rationale"]
    assert await _autopilot_calls(db, auth_headers) == 3, "plan + one replan + curate"


async def test_replan_stays_single_when_both_passes_are_empty(
    client, auth_headers, db, search_fixtures, autopilot_mock
):
    """Two empty passes still mean exactly one replan (plan 158 S5.5)."""
    autopilot_mock(_never_broad())
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    assert result["findings"] == []
    assert [entry.get("step") for entry in result["searches"]].count("replan") == 1
    assert await _autopilot_calls(db, auth_headers) == 2


async def test_progress_never_regresses_across_the_replan_reentry(
    client, auth_headers, db, search_fixtures, autopilot_mock
):
    """Re-entering the search node after a replan reports forward-only
    progress (plan 158 S5.6a)."""
    autopilot_mock(_empty_then_broad())
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    reported: list[int] = []

    async def progress(pct: int, _stage: str) -> None:
        reported.append(int(pct))

    result = await service.run_goal(UUID(created["id"]), user_id, progress=progress)
    await db.commit()

    assert result["findings"], "the replan delivers"
    assert [entry.get("step") for entry in result["searches"]].count("replan") == 1
    assert reported, "the run reports progress"
    assert reported == sorted(reported), f"progress regressed: {reported}"


async def test_budget_cap_suppresses_the_replan(
    client, auth_headers, db, search_fixtures, autopilot_mock
):
    """An already-spent run budget skips the replan call entirely
    (plan 158 S5.2)."""
    autopilot_mock(_empty_then_broad())
    created = await _goal(client, auth_headers, budget={"max_calls": 1})
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    assert result["status"] == "budget_aborted"
    assert await _autopilot_calls(db, auth_headers) == 1, "no replan gateway call"


async def test_replan_then_budget_abort_still_ships_partials(
    client, auth_headers, db, search_fixtures, autopilot_mock
):
    """Plan + replan exhaust a 2-call cap before curate: deterministic
    findings still ship (plan 158 S5.6b)."""
    autopilot_mock(_empty_then_broad())
    created = await _goal(client, auth_headers, budget={"max_calls": 2})
    service, user_id = _service(db, auth_headers)

    first = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    assert await _autopilot_calls(db, auth_headers) == 2
    assert first["findings"], "partials by design"
    assert first["findings"][0]["why"].startswith("Fit ")
    assert first["status"] == "budget_aborted"


# ------------------------------------------- S7 curated job-relation sweep


async def _related_catalog_jobs(db) -> tuple:
    """Two published catalog jobs joined by a curated similar_to edge."""
    from sqlalchemy import select as _select

    from app.models.enums import RelationType
    from app.models.job_model import Job, JobRelation

    jobs = (
        (
            await db.execute(
                _select(Job).where(Job.status == "published").order_by(Job.code).limit(2)
            )
        )
        .scalars()
        .all()
    )
    source_job, related_job = jobs
    db.add(
        JobRelation(
            from_job_id=source_job.id,
            to_job_id=related_job.id,
            relation_type=RelationType.SIMILAR_TO.value,
            weight=0.9,
            source="manual",
        )
    )
    await db.commit()
    return source_job, related_job


async def test_graph_sweep_surfaces_a_related_roles_posting(
    client, auth_headers, db, seeded_catalog, source, kinds, autopilot_mock
):
    """A posting under a similar_to-related catalog job surfaces even when
    no variant's text matches it (plan 158 S7.1/S7.3)."""
    from tests.conftest import _make_posting

    source_job, related_job = await _related_catalog_jobs(db)
    seed = await _make_posting(
        db,
        source,
        external_id="g-seed",
        title="Alpha Seed Role",
        skills_raw=[],
        raw={"description": "Seed role."},
    )
    neighbour = await _make_posting(
        db,
        source,
        external_id="g-neighbour",
        title="Omega Neighbour Role",
        skills_raw=[],
        raw={"description": "Neighbour role."},
    )
    seed.catalog_job_id = source_job.id
    neighbour.catalog_job_id = related_job.id
    await db.commit()

    def scripted(schema, user_prompt):
        from app.ai.graphs.autopilot import _mock_autopilot
        from app.ai.schemas import SearchPlan

        if schema is SearchPlan:
            return {
                "variants": [
                    {
                        "rationale": "narrow lexical probe",
                        "query": "",
                        "filters": {"keywords": ["alpha"]},
                    }
                ]
            }
        return _mock_autopilot(schema, user_prompt)

    autopilot_mock(scripted)
    created = await _goal(client, auth_headers, constraints={"top_n": 3})
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    surfaced = [finding["posting_id"] for finding in result["findings"]]
    assert str(neighbour.id) in surfaced
    sweep = next(
        entry
        for entry in result["searches"]
        if str(entry.get("rationale") or "").startswith("curated graph expansion from")
    )
    assert sweep["found"] >= 1
    assert "Alpha Seed Role" in sweep["rationale"]


async def test_graph_sweep_keeps_gated_postings_out(
    client, auth_headers, db, seeded_catalog, source, kinds, autopilot_mock
):
    """Seen and never-term postings stay out of the sweep's pool
    (plan 158 S7.1/S7.3)."""
    from app.models.posting_model import PostingInteraction
    from tests.conftest import _make_posting

    source_job, related_job = await _related_catalog_jobs(db)
    seed = await _make_posting(
        db, source, external_id="g2-seed", title="Alpha Seed Role", skills_raw=[], raw={}
    )
    seen = await _make_posting(
        db, source, external_id="g2-seen", title="Omega Seen Role", skills_raw=[], raw={}
    )
    banned = await _make_posting(
        db, source, external_id="g2-banned", title="Omega Banned Role", skills_raw=[], raw={}
    )
    for posting in (seed, seen, banned):
        posting.catalog_job_id = source_job.id if posting is seed else related_job.id
    db.add(
        PostingInteraction(
            user_id=_uid(auth_headers), posting_id=seen.id, seen_at=datetime.now(UTC)
        )
    )
    await db.commit()

    def scripted(schema, user_prompt):
        from app.ai.graphs.autopilot import _mock_autopilot
        from app.ai.schemas import SearchPlan

        if schema is SearchPlan:
            return {
                "variants": [
                    {
                        "rationale": "narrow lexical probe",
                        "query": "",
                        "filters": {"keywords": ["alpha"]},
                    }
                ]
            }
        return _mock_autopilot(schema, user_prompt)

    autopilot_mock(scripted)
    created = await _goal(client, auth_headers, constraints={"top_n": 3, "never_terms": ["banned"]})
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    surfaced = {finding["posting_id"] for finding in result["findings"]}
    assert str(seen.id) not in surfaced
    assert str(banned.id) not in surfaced


async def test_graph_sweep_recuts_the_pool_and_degrades_without_relations(
    db, auth_headers, seeded_catalog, source, kinds, autopilot_mock
):
    """The sweep never grows the pool past the curator pool, and a catalog
    with no relations yields a no-op entry (plan 158 S7.2/S7.3)."""
    from sqlalchemy import select as _select

    from app.ai.graphs.autopilot import (
        GraphDeps,
        build_autopilot_graph,
        curator_pool,
        initial_state,
    )
    from app.ai.schemas import SearchPlan
    from app.models.job_model import Job
    from tests.conftest import _make_posting

    source_job = (
        (await db.execute(_select(Job).where(Job.status == "published").order_by(Job.code)))
        .scalars()
        .first()
    )
    for index in range(20):
        posting = await _make_posting(
            db, source, external_id=f"g3-{index}", title=f"Alpha Bulk Role {index}", raw={}
        )
        posting.catalog_job_id = source_job.id
    await db.commit()

    def scripted(schema, user_prompt):
        from app.ai.graphs.autopilot import _mock_autopilot

        if schema is SearchPlan:
            return {
                "variants": [
                    {"rationale": "broad net", "query": "", "filters": {"keywords": ["alpha"]}}
                ]
            }
        return _mock_autopilot(schema, user_prompt)

    autopilot_mock(scripted)
    user_id = _uid(auth_headers)
    goal = AutopilotGoal(user_id=user_id, goal_text="alpha roles", constraints={}, budget={})
    db.add(goal)
    await db.flush()
    run = AutopilotRun(goal_id=goal.id)
    db.add(run)
    await db.commit()

    graph = build_autopilot_graph(GraphDeps(db=db), InMemorySaver())
    config = {"configurable": {"thread_id": str(run.id)}}
    final = await graph.ainvoke(
        initial_state(
            user_id=user_id,
            goal_id=goal.id,
            run_id=run.id,
            goal_text="alpha roles",
            constraints={},
            budget={},
        ),
        config,
    )
    await db.commit()

    assert len(final["candidates"]) <= curator_pool(5)
    assert len(final["findings"]) <= 5
    sweep = next(
        entry
        for entry in final["searches"]
        if str(entry.get("rationale") or "").startswith("curated graph expansion")
    )
    assert sweep["found"] == 0, "no relations ⇒ no-op entry"


# ------------------------------------------------- run trace (plan 168 S1)


async def _trace_of(db, run_id: str) -> list[dict]:
    run = await db.get(AutopilotRun, UUID(run_id))
    return list(run.run_steps or [])


def _broad_planner():
    """One filterless variant — a wide net with no replan trigger."""

    def scripted(schema, user_prompt):
        from app.ai.graphs.autopilot import _mock_autopilot
        from app.ai.schemas import SearchPlan

        if schema is SearchPlan:
            return {"variants": [{"rationale": "broad net", "query": "", "filters": {}}]}
        return _mock_autopilot(schema, user_prompt)

    return scripted


async def test_run_steps_record_the_full_node_sequence(
    client, auth_headers, db, search_fixtures, autopilot_mock
):
    """A clean mock run lands one trace entry per executed node, in
    execution order, with the full entry shape (plan 168 S1.2)."""
    autopilot_mock(_broad_planner())
    created = await _goal(client, auth_headers, constraints={"top_n": 1})
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    steps = await _trace_of(db, result["run_id"])
    assert [entry["step"] for entry in steps] == [
        "plan",
        "search",
        "filter",
        "evaluate",
        "graph_sweep",
        "budget_guard",
        "curate",
        "deliver",
    ]
    for entry in steps:
        assert {
            "step",
            "kind",
            "iteration",
            "at",
            "duration_ms",
            "args",
            "output",
            "error",
            "abort",
        } <= set(entry)
        assert entry["iteration"] == 1
        assert entry["abort"] == ""
    assert steps[0]["kind"] == "llm" and steps[-1]["kind"] == "deterministic"
    assert steps[-1]["output"]["status"] == "completed"
    assert steps[-1]["output"]["notified"] is True


async def test_run_stages_land_on_ledger_rows(
    client, auth_headers, db, search_fixtures, autopilot_mock
):
    """Every autopilot gateway call carries run_id + stage: plan, curate
    and the semantic sweep out of the box, replan when it fires (plan 168
    S1.1) — the existing /admin/audit run_id filter starts working."""
    from app.models.ai_model import AIGeneration

    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    rows = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.run_id == UUID(result["run_id"]))
            )
        )
        .scalars()
        .all()
    )
    stages = {row.run_stage for row in rows}
    assert {"autopilot.plan", "autopilot.curate", "autopilot.semantic_sweep"} <= stages
    assert all(row.run_id == UUID(result["run_id"]) for row in rows)

    autopilot_mock(_empty_then_broad())
    replanned = await AutopilotService(db, checkpointer=InMemorySaver()).run_goal(
        UUID(created["id"]), user_id
    )
    await db.commit()
    rows = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.run_id == UUID(replanned["run_id"]))
            )
        )
        .scalars()
        .all()
    )
    assert "autopilot.replan" in {row.run_stage for row in rows}


async def test_replan_loop_is_marked_in_the_trace(
    client, auth_headers, db, search_fixtures, autopilot_mock
):
    """The broaden pass shows up once, and the re-entered search/filter
    carry iteration=2 (plan 168 S1.2/S1.5)."""
    autopilot_mock(_empty_then_broad())
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    steps = await _trace_of(db, result["run_id"])
    replans = [entry for entry in steps if entry["step"] == "replan"]
    assert len(replans) == 1
    second_pass = [entry for entry in steps if entry["iteration"] == 2]
    assert {"search", "filter"} <= {entry["step"] for entry in second_pass}
    assert replans[0]["iteration"] == 1
    searches = [entry for entry in steps if entry["step"] == "search"]
    assert len(searches) == 2, "one search per pass"
    pairs = [(entry["step"], entry["iteration"]) for entry in steps]
    assert len(pairs) == len(set(pairs)), "no duplicate (step, iteration) entries"


async def test_budget_aborted_run_persists_steps(client, auth_headers, db, search_fixtures):
    """The soft-abort path funnels through deliver: entries up to the
    guard's abort persist, curate never ran (plan 168 S1.4)."""
    created = await _goal(client, auth_headers, budget={"max_calls": 1})
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()
    assert result["status"] == "budget_aborted"

    steps = await _trace_of(db, result["run_id"])
    names = [entry["step"] for entry in steps]
    assert "curate" not in names
    guard = next(entry for entry in steps if entry["step"] == "budget_guard")
    assert guard["abort"] == "budget"
    assert steps[-1]["step"] == "deliver"
    assert steps[-1]["output"]["status"] == "budget_aborted"
    assert steps[-1]["output"]["notified"] is bool(result["findings"])


async def test_cancelled_run_persists_steps(client, auth_headers, db, search_fixtures):
    """A user cancel mid-search still persists the trace with the abort
    marker (plan 168 S1.5)."""
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)

    async def cancelled() -> bool:
        return True

    result = await service.run_goal(UUID(created["id"]), user_id, cancelled=cancelled)
    await db.commit()
    assert result["status"] == "cancelled"

    steps = await _trace_of(db, result["run_id"])
    aborted = [entry for entry in steps if entry["abort"]]
    assert aborted and all(entry["abort"] == "cancelled" for entry in aborted)
    assert steps[-1]["step"] == "deliver"
    assert steps[-1]["output"]["status"] == "cancelled"
    assert steps[-1]["output"]["notified"] is False


async def test_raised_exception_persists_partial_trace(
    client, auth_headers, db, search_fixtures, monkeypatch
):
    """A node that dies loses its own entry but the run persists the steps
    up to the last completed node, `failed` + error set (plan 168 S1.4) —
    today a raise lost the trace with the session."""
    from app.services.notification_service import NotificationService

    async def exploding(self, *args, **kwargs):
        raise RuntimeError("notification funnel exploded")

    monkeypatch.setattr(NotificationService, "emit", exploding)

    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    with pytest.raises(RuntimeError, match="notification funnel exploded"):
        await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    rows = (
        (await db.execute(select(AutopilotRun).where(AutopilotRun.goal_id == UUID(created["id"]))))
        .scalars()
        .all()
    )
    run = rows[0]
    assert run.status == "failed"
    assert "RuntimeError" in run.error
    assert run.finished_at is not None
    names = [entry["step"] for entry in run.run_steps or []]
    assert "deliver" not in names, "the raising node contributes no step"
    assert names[-1] == "curate", "steps run up to the last completed node"


async def test_resume_yields_one_step_per_node_without_duplicates(
    db, auth_headers, seeded_catalog, source, kinds
):
    """Resume-from-checkpoint records exactly one entry per executed node
    (plan 168 S1.5, the `test_graph_resume_from_checkpoint` pattern)."""
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
    graph.update_state(
        config,
        {
            **state,
            "plan": {
                "variants": [
                    {
                        "rationale": "resume sweep",
                        "query": "",
                        "filters": {"keywords": ["programming"]},
                    }
                ]
            },
        },
        as_node="plan",
    )
    final = await graph.ainvoke(None, config)
    await db.commit()

    pairs = [(entry["step"], entry["iteration"]) for entry in final.get("trace_steps") or []]
    assert pairs, "the resumed run records its trace"
    assert len(pairs) == len(set(pairs)), "no duplicates across the resume boundary"
    assert pairs[-1][0] == "deliver"


async def test_trace_summaries_stay_within_caps(
    client, auth_headers, db, seeded_catalog, source, kinds, autopilot_mock
):
    """Trace args/output are whitelisted summaries: no full serialized
    candidate (snippet/responsibilities), ids bounded by CANDIDATE_CAP
    (plan 168 S1.2, plan 158 S4.6)."""
    from app.ai.graphs.autopilot import CANDIDATE_CAP
    from tests.conftest import _make_posting

    for index in range(CANDIDATE_CAP + 5):
        await _make_posting(
            db,
            source,
            external_id=f"trace-{index}",
            title=f"Trace Bulk Role {index}",
        )
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    steps = await _trace_of(db, result["run_id"])
    assert steps
    for entry in steps:
        blob = json.dumps(entry)
        assert '"snippet"' not in blob
        assert '"responsibilities"' not in blob
        assert len(str(entry["args"].get("goal", ""))) <= 400
        assert entry["duration_ms"] >= 0


# ------------------------------------------- run detail endpoint (S2)


async def test_run_detail_endpoint_serves_owner(
    client, auth_headers, db, search_fixtures, autopilot_mock
):
    """The owner opens a run by id: steps, execution-ordered nodes, ledger
    metadata without prompt text, findings, timeline (plan 168 S2.1)."""
    from app.ai.graphs.autopilot import GraphDeps, build_autopilot_graph

    autopilot_mock(_broad_planner())
    goal_text = "Find me a junior QA or data job where I can use programming"
    created = await _goal(
        client,
        auth_headers,
        goal_text=goal_text,
        constraints={"top_n": 1},
    )
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    response = await client.get(f"/api/v1/autopilot/runs/{result['run_id']}", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["id"] == result["run_id"]
    assert body["run"]["goal_id"] == created["id"]
    assert body["trace_available"] is True
    assert [entry["step"] for entry in body["steps"]] == [
        "plan",
        "search",
        "filter",
        "evaluate",
        "graph_sweep",
        "budget_guard",
        "curate",
        "deliver",
    ]
    compiled = set(build_autopilot_graph(GraphDeps(db=None)).nodes) - {
        "__start__",
        "__end__",
    }
    assert set(body["nodes"]) == compiled
    assert body["nodes"] == [
        "plan",
        "search",
        "filter",
        "replan",
        "evaluate",
        "graph_sweep",
        "budget_guard",
        "curate",
        "deliver",
    ]
    calls = body["ai_calls"]
    assert calls, "the run's gateway calls are listed"
    for call in calls:
        assert {"id", "task_type", "run_stage", "provider", "model", "status"} <= set(call)
        assert "prompt" not in call and "output" not in call
    assert goal_text not in json.dumps(calls), "no prompt text leaks"
    assert body["timeline"], "the searches_executed timeline rides along"
    assert body["findings"], "the run's findings ride along"


async def test_run_detail_offers_no_filters_or_export(client):
    """ADR-0044 addendum, condition 3 (plan 175 S3): the owner's run
    detail is addressed by id alone — no ledger-wide filter or export
    parameters, no request body."""
    from app.main import app

    schema = app.openapi()
    operation = schema["paths"]["/api/v1/autopilot/runs/{run_id}"]["get"]
    query_params = [
        param for param in operation.get("parameters") or [] if param.get("in") == "query"
    ]
    assert query_params == [], "no filter or export parameters"
    assert "requestBody" not in operation


async def test_run_detail_is_404_for_foreign_and_missing(client, auth_headers, db, search_fixtures):
    """A foreign run and a missing run answer the SAME 404 — the explicit
    owner lookup leaks nothing (plan 168 S2.1/S2.3; the goal-keyed
    endpoints keep their 403)."""
    created = await _goal(client, auth_headers)
    service, user_id = _service(db, auth_headers)
    result = await service.run_goal(UUID(created["id"]), user_id)
    await db.commit()

    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "run-thief@example.com", "password": "supersecret1"},
    )
    assert other.status_code == 201
    other_headers = session_headers(other)

    foreign = await client.get(f"/api/v1/autopilot/runs/{result['run_id']}", headers=other_headers)
    missing = await client.get(
        f"/api/v1/autopilot/runs/{UUID(int=0xDEADBEEF)}", headers=other_headers
    )
    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert foreign.json() == missing.json()


async def test_run_detail_falls_back_without_trace(client, auth_headers, db):
    """A pre-trace (or pruned) run still resolves: timeline rides along,
    steps stay empty and trace_available is false — never an empty surface
    (plan 168 S2.1/S2.3); runs beyond the 30-row listing resolve by id."""
    created = await _goal(client, auth_headers)
    for _index in range(35):
        db.add(AutopilotRun(goal_id=UUID(created["id"]), status="completed"))
    await db.commit()
    rows = (
        (
            await db.execute(
                select(AutopilotRun)
                .where(AutopilotRun.goal_id == UUID(created["id"]))
                .order_by(AutopilotRun.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    oldest = rows[0]

    response = await client.get(f"/api/v1/autopilot/runs/{oldest.id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["trace_available"] is False
    assert body["steps"] == []
    assert body["run"]["id"] == str(oldest.id)
    listed = await client.get(f"/api/v1/autopilot/goals/{created['id']}/runs", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 30, "the list caps at 30 — the detail endpoint does not"
