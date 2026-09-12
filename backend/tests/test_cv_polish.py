"""Plan-64: the polish loop — routing gate, trace helpers, the
mock-provider e2e (trace persistence, cap, degrade, cancel), variant
keep/revert, the redesign escape hatch and the live-preview/resume
endpoints (plan §6)."""

import uuid
from uuid import UUID

import app.ai.agents.cv_build_reviewer  # noqa: F401 — registers the mock fixture at import so per-test overrides survive
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.ai.gateway import MOCK_FIXTURES
from app.ai.graphs import cv_draft
from app.ai.graphs.cv_draft import route_after_review
from app.models.ai_model import AIGeneration
from app.models.background_job_model import BackgroundJob
from app.models.cv_model import CvDocument, CvVersion
from app.models.enums import AITaskType, BackgroundJobStatus, BackgroundJobType
from app.schemas.cv_generate import CvGenerateRequest

from tests.conftest import _uid
from tests.test_cv_generate import _experience


# ------------------------------------------------------------- gate routing


def _review_state(**overrides) -> dict:
    state = {
        "polish": {"iteration": 1, "outcome": {}},
        "critique": {"issues": [], "coverage": {"missing": []}},
        "review_lint": {"checks": []},
    }
    state.update(overrides)
    return state


def test_gate_finalizes_a_clean_review():
    assert route_after_review(_review_state()) == "finalize"


def test_gate_routes_fix_on_fail_level_findings():
    state = _review_state(
        critique={
            "issues": [{"level": "fail", "area": "density", "message": "x"}],
            "coverage": {"missing": []},
        }
    )
    assert route_after_review(state) == "fix"


def test_gate_finalizes_uncovered_items_without_findings():
    """A coverage gap alone can't be acted on — the reviewer must name it."""
    state = _review_state(
        critique={"issues": [], "coverage": {"missing": [{"item_id": "skill-1"}]}}
    )
    assert route_after_review(state) == "finalize"


def test_gate_finalizes_warn_level_findings():
    state = _review_state(critique={"issues": [{"level": "warn", "area": "density"}]})
    assert route_after_review(state) == "finalize"


def test_gate_never_loops_past_the_cap():
    state = _review_state()
    state["polish"]["iteration"] = cv_draft.POLISH_MAX_ITERATIONS
    assert route_after_review(state) == "finalize"


def test_gate_ends_a_cancelled_run():
    state = _review_state()
    state["polish"]["outcome"] = cv_draft.polish_outcome("cancelled")
    assert route_after_review(state) == "end"


# ------------------------------------------------------------ trace helpers


def test_lint_summary_is_compact_and_stateful():
    lint = {
        "checks": [{"id": "a", "level": "fail", "message": "m"}],
        "metrics": {
            "empty_blocks": ["skills"],
            "pages_actual": 2,
            "pages_actual_over_budget": True,
        },
    }
    summary = cv_draft._summary_lint(lint)
    assert summary["empty_blocks"] == ["skills"]
    assert summary["pages_actual_over_budget"] is True
    assert len(summary["checks"]) == 1


def test_public_request_lifts_the_user_prompt():
    request = CvGenerateRequest(
        language="en",
        length="concise",
        notes="Lead with the internship.",
        max_pages=2,
        sections=["experience", "skills"],
        include_photo=False,
    )
    block = cv_draft._public_request(request)
    assert block["notes"] == "Lead with the internship."
    assert block["max_pages"] == 2
    assert block["sections"] == ["experience", "skills"]


# ------------------------------------------------------------------ e2e


async def _generate(db, auth_headers, run_id: uuid.UUID | None = None) -> dict:
    from app.services.cv_generate_service import CvGenerateService

    return await CvGenerateService(db).generate(
        UUID(_uid(auth_headers)),
        CvGenerateRequest(language="en", length="standard", notes="Endless curiosity."),
        run_id=run_id or uuid.uuid4(),
    )


async def _latest_final_version(db, cv) -> CvVersion:
    return (
        (
            await db.execute(
                select(CvVersion)
                .where(CvVersion.cv_document_id == cv.id)
                .order_by(CvVersion.version.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def test_polish_completes_and_carries_the_trace(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """Happy path (plan §6): review runs, the loop stops bounded and
    finalize writes the trace on the final ai_apply version."""
    await _experience(client, auth_headers)
    run_id = uuid.uuid4()
    result = await _generate(db, auth_headers, run_id=run_id)
    await db.commit()
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    versions = (
        (
            await db.execute(
                select(CvVersion)
                .where(CvVersion.cv_document_id == cv.id)
                .order_by(CvVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    assert [v.created_by for v in versions] == ["ai_apply", "ai_apply"]
    trace = versions[0].content["polish"]
    assert trace["run"]["stages"], "stage events recorded"
    assert trace["request"]["notes"] == "Endless curiosity."
    assert trace["iterations"]
    assert any(iteration["coverage"] for iteration in trace["iterations"])
    assert trace["outcome"]["status"] in ("completed", "cap")
    audited = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.run_id == run_id,
                    AIGeneration.task_type == AITaskType.CV_BUILD_REVIEW.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert audited, "the polish review call is linked to the run"
    assert all(row.run_stage == "cv_draft.review" for row in audited)
    calls = trace.get("llm_calls") or []
    assert calls, "the finalized trace carries the run's LLM-call ledger"
    assert "cv_build_review" in {call["task"] for call in calls}
    assert "cv_draft.review" in {call.get("stage") for call in calls}
    assert all(call["latency_ms"] is not None for call in calls)


async def test_polish_cap_stops_at_the_iteration_limit(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """A fixture that always fails stops the loop at the cap (plan §6)."""

    def _always_fail(schema, prompt):
        return {
            "summary": "Still failing.",
            "issues": [
                {"level": "fail", "area": "density", "message": "Layout is off."}
            ],
            "coverage": {"covered": [], "dropped_knowingly": [], "missing": []},
        }

    monkeypatch.setitem(MOCK_FIXTURES, AITaskType.CV_BUILD_REVIEW.value, _always_fail)
    await _experience(client, auth_headers)
    result = await _generate(db, auth_headers)
    await db.commit()
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    final = await _latest_final_version(db, cv)
    trace = final.content["polish"]
    assert len(trace["iterations"]) == cv_draft.POLISH_MAX_ITERATIONS
    assert trace["outcome"]["status"] == "cap"


async def test_polish_without_png_engine_degrades_to_lint_only(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """PNG engine 503 → review degrades; the run still completes."""
    monkeypatch.setattr(
        "app.services.cv_pdf_service.pdf_engine_available", lambda: False
    )
    await _experience(client, auth_headers)
    result = await _generate(db, auth_headers)
    await db.commit()
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    final = await _latest_final_version(db, cv)
    trace = final.content["polish"]
    assert trace["iterations"][0]["pages"] == 0
    assert trace["outcome"]["status"] in ("completed", "cap")


async def _cancelled() -> bool:
    return True


async def test_review_node_reports_a_cancelled_run(db):
    deps = cv_draft.GraphDeps(db=db, cancelled=_cancelled)
    node = cv_draft.make_review_node(deps)
    result = await node(
        {
            "result": {"cv_id": str(uuid.uuid4())},
            "polish": {},
            "request": {},
            "user_id": str(uuid.uuid4()),
        }
    )
    assert result["abort_reason"] == "cancelled"
    assert result["polish"]["outcome"]["status"] == "cancelled"


async def test_mirror_annotates_the_runs_llm_call_ledger(
    db, client, auth_headers, profile_ready
):
    """The mid-run mirror (65.2) carries the run's LLM-call ledger into
    `job.result.polish.llm_calls` — what the live preview + progress card
    poll — assembled from the audit rows the run opted into (65.1)."""
    from app.ai.gateway import RunRef, ainvoke_structured
    from app.ai.graphs.cv_draft import GraphDeps, _mirror_job_result
    from app.ai.schemas import ChatReply
    from app.models.ai_model import AIGeneration
    from app.models.enums import AITaskType

    run_id = uuid.uuid4()
    await ainvoke_structured(
        db,
        AITaskType.ASSIST,
        ChatReply,
        system="s",
        user="CONTEXT_JSON: {}",
        run=RunRef(id=run_id, stage="cv_draft.plan"),
    )
    db.add(
        BackgroundJob(
            id=run_id,
            user_id=UUID(_uid(auth_headers)),
            job_type=BackgroundJobType.CV_GENERATE.value,
            status=BackgroundJobStatus.RUNNING.value,
            payload={},
        )
    )
    await db.commit()

    polish = {"iteration": 0}
    await _mirror_job_result(
        GraphDeps(db=db),
        {"run_id": str(run_id), "result": {"cv_id": "x"}},
        polish,
    )
    await db.commit()
    job = await db.get(BackgroundJob, run_id)
    calls = job.result["polish"]["llm_calls"]
    assert calls == polish["llm_calls"]
    assert calls[0]["task"] == AITaskType.ASSIST.value
    assert calls[0]["stage"] == "cv_draft.plan"
    audit = await db.get(AIGeneration, calls[0]["id"])
    assert audit is not None


# --------------------------------------------------- variant keep/revert cycle


async def test_variant_is_applied_then_kept_by_the_next_review(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """Iteration 0 flags one item (fail + set_override suggestion): the
    loop grounds a CV_SYNTH variant and applies it; the next review is
    clean → the pending variant resolves as kept, its synth row stays
    DRAFT in the library, and the loop finalizes (plan 64 §3)."""
    from sqlalchemy import text as sql

    from app.ai.agents.context import parse_context

    def _critique(schema, prompt):
        ctx = parse_context(prompt)
        iteration = int(ctx.get("iteration") or 0)
        covered = (ctx.get("coverage") or {}).get("included") or []
        if not covered:
            return _clean_critique()
        ref = covered[0]
        if iteration == 0:
            return {
                "summary": "One content fix.",
                "issues": [
                    {
                        "level": "fail",
                        "area": "content",
                        "message": f"Tighten {ref['label']}.",
                        "suggested_ops": [
                            {
                                "operation": {
                                    "op": "set_override",
                                    "source_key": ref["source_key"],
                                    "item_id": ref["item_id"],
                                    "field": "description",
                                    "value": "tightened description",
                                },
                                "rationale": "variant slot",
                            }
                        ],
                    }
                ],
                "coverage": {
                    "covered": [],
                    "dropped_knowingly": [],
                    "missing": [],
                },
            }
        return _clean_critique()

    def _clean_critique():
        return {
            "summary": "Clean build.",
            "issues": [],
            "coverage": {"covered": [], "dropped_knowingly": [], "missing": []},
        }

    monkeypatch.setitem(MOCK_FIXTURES, AITaskType.CV_BUILD_REVIEW.value, _critique)
    await _experience(client, auth_headers)
    result = await _generate(db, auth_headers)
    await db.commit()
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    final = await _latest_final_version(db, cv)
    trace = final.content["polish"]
    assert trace["outcome"]["status"] == "completed"
    verdicts = [
        v["verdict"] for iteration in trace["iterations"] for v in iteration["variants"]
    ]
    assert verdicts and "kept" in verdicts
    rows = (await db.execute(sql("select status, source from cv_synth_items"))).all()
    assert all(status == "draft" and source == "ai" for status, source in rows)


async def test_structural_redesign_escape_hatch_triggers_and_keeps(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """Two persistent layout fails → one draft_template redesign →
    published as a private DRAFT template + content re-merged onto the
    new skeleton → the next (clean) review keeps it (plan 64 §3)."""
    from app.ai.agents.context import parse_context

    def _critique(schema, prompt):
        context = parse_context(prompt)
        iteration = int(context.get("iteration") or 0)
        if iteration < 2:
            return {
                "summary": "Layout keeps fighting the content.",
                "issues": [
                    {
                        "level": "fail",
                        "area": "layout",
                        "message": "The sidebar starves the main column.",
                    }
                ],
                "coverage": {"covered": [], "dropped_knowingly": [], "missing": []},
            }
        return {
            "summary": "Redesigned build looks ready.",
            "issues": [],
            "coverage": {"covered": [], "dropped_knowingly": [], "missing": []},
        }

    monkeypatch.setitem(MOCK_FIXTURES, AITaskType.CV_BUILD_REVIEW.value, _critique)
    await _experience(client, auth_headers)
    result = await _generate(db, auth_headers)
    await db.commit()
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    trace = (await _latest_final_version(db, cv)).content["polish"]
    assert trace["outcome"]["status"] == "completed"
    assert trace.get("redesign_spent") is True
    redesigns = [
        r for iteration in trace["iterations"] for r in iteration.get("redesign") or []
    ]
    assert any(r["verdict"] == "kept" for r in redesigns), redesigns
    assert trace["redesign"].get("pending") is False


# ------------------------------------------------- live preview + resume


async def test_preview_renders_the_committed_state_while_running(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """A running job's preview renders the committed draft (plan 64 §3).

    The committed working state carries the run's id, so the preview
    finds and renders the CV even before any result is written;
    unknown runs answer 404 (the builder takes over after finalize)."""
    await _experience(client, auth_headers)
    result = await _generate(db, auth_headers)
    await db.commit()
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    run_id = str(cv.working_content["run_id"])
    ghost = BackgroundJob(
        id=UUID(run_id),
        user_id=UUID(_uid(auth_headers)),
        job_type=BackgroundJobType.CV_GENERATE.value,
        status=BackgroundJobStatus.RUNNING.value,
        payload={},
    )
    db.add(ghost)
    await db.commit()
    body = (
        await client.get(f"/api/v1/cv/generate/{run_id}/preview", headers=auth_headers)
    ).json()
    assert body["html"], "the committed state renders deterministically"
    assert "<!DOCTYPE html>" in body["html"]
    foreign = await client.get(
        f"/api/v1/cv/generate/{uuid.uuid4()}/preview", headers=auth_headers
    )
    assert foreign.status_code == 404


async def test_preview_soft_answers_before_the_draft_exists(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """A running run whose CV is not committed yet (queued/collect/plan/
    draft) answers 200 with an empty snapshot — no 404 log spam for the
    progress card's polling."""
    empty_job = BackgroundJob(
        id=uuid.uuid4(),
        user_id=UUID(_uid(auth_headers)),
        job_type=BackgroundJobType.CV_GENERATE.value,
        status=BackgroundJobStatus.RUNNING.value,
        payload={"request": {"language": "en"}},
    )
    db.add(empty_job)
    await db.commit()
    body = (
        await client.get(
            f"/api/v1/cv/generate/{empty_job.id}/preview", headers=auth_headers
        )
    ).json()
    assert body["html"] == ""
    assert body["stage"] == ""


async def _drain(db) -> int:
    from app.services.job_worker import JobWorker

    worker = JobWorker(db)
    executed = 0
    while await worker.run_once():
        executed += 1
    return executed


async def test_resume_polish_endpoint_runs_the_loop_to_finalize(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """POST /cv/{id}/polish queues a polish-only run; finalize compiles
    a third ai_apply version chaining the resume link (plan 64 §3)."""
    import app.services.cv_generate_service as service_module

    async def memory_checkpointer():
        return InMemorySaver()

    monkeypatch.setattr(service_module, "get_checkpointer", memory_checkpointer)
    await _experience(client, auth_headers)
    created = await client.post(
        "/api/v1/cv/generate",
        json={"language": "en", "length": "concise", "max_pages": 1},
        headers=auth_headers,
    )
    assert created.status_code == 202, created.text
    await _drain(db)
    listing = (await client.get("/api/v1/cv", headers=auth_headers)).json()
    cv_id = listing[0]["id"]

    accepted = await client.post(
        f"/api/v1/cv/{cv_id}/polish",
        json={"resumed_from": "0189f5c0-5b2c-7a1b-9c3d-4e5f6a7b8c9d"},
        headers=auth_headers,
    )
    assert accepted.status_code == 202, accepted.text
    await _drain(db)
    await db.commit()

    cv = await db.get(CvDocument, UUID(cv_id))
    versions = (
        (
            await db.execute(
                select(CvVersion)
                .where(CvVersion.cv_document_id == cv.id)
                .order_by(CvVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    assert [v.created_by for v in versions] == ["ai_apply", "ai_apply", "ai_apply"]
    trace = versions[0].content["polish"]
    assert trace["run"]["resumed_from"]["job_id"]
    assert trace["outcome"]["status"] in ("completed", "cap")

    rejected = await client.post(
        f"/api/v1/cv/{cv_id}/polish",
        headers=await _foreign_user_headers(client),
    )
    assert rejected.status_code == 404


async def _foreign_user_headers(client) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "other.student@example.com",
            "password": "supersecret1",
            "full_name": "Other Student",
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_runs_endpoint_splits_resumed_runs(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """The runs endpoint lists the generation run plus its polish re-run
    separately, each carrying only its own audited calls (plan 65.3)."""
    import app.services.cv_generate_service as service_module

    async def memory_checkpointer():
        return InMemorySaver()

    monkeypatch.setattr(service_module, "get_checkpointer", memory_checkpointer)
    await _experience(client, auth_headers)
    created = await client.post(
        "/api/v1/cv/generate",
        json={"language": "en", "length": "concise", "max_pages": 1},
        headers=auth_headers,
    )
    assert created.status_code == 202, created.text
    await _drain(db)
    listing = (await client.get("/api/v1/cv", headers=auth_headers)).json()
    cv_id = listing[0]["id"]

    accepted = await client.post(
        f"/api/v1/cv/{cv_id}/polish",
        json={"resumed_from": "0189f5c0-5b2c-7a1b-9c3d-4e5f6a7b8c9d"},
        headers=auth_headers,
    )
    assert accepted.status_code == 202, accepted.text
    await _drain(db)
    await db.commit()

    runs = (await client.get(f"/api/v1/cv/{cv_id}/runs", headers=auth_headers)).json()
    assert len(runs) == 2, [run["job_type"] for run in runs]
    polish_run, generate_run = runs
    assert polish_run["job_type"] == "cv_polish"
    assert generate_run["job_type"] == "cv_generate"
    assert polish_run["resumed_from"], "the polish run chains its predecessor"
    polish_tasks = {call["task"] for call in polish_run["llm_calls"]}
    generate_tasks = {call["task"] for call in generate_run["llm_calls"]}
    assert "cv_build_review" in polish_tasks
    assert "cv_draft" in generate_tasks
    assert polish_run["aggregate"]["calls"] == len(polish_run["llm_calls"])
