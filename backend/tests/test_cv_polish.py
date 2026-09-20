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
from app.services.cv_generate_service import CvGenerateService

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

    async def _unavailable(*_args, **_kwargs):
        from app.services.cv_pdf_service import PDFEngineUnavailable

        raise PDFEngineUnavailable("Server PDF engine not installed")

    monkeypatch.setattr("app.services.cv_pdf_service.measure_pages", _unavailable)
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
    clean → the pending variant resolves as kept, its synth row turns
    ACTIVE (a review-kept variant is eligible), and the loop finalizes
    (plan 64 §3)."""
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
    assert rows, "the kept variant lives in the library"
    assert all(status == "active" for status, _source in rows), (
        "a review-kept variant is auto-activated"
    )
    record = next(v for iteration in trace["iterations"] for v in iteration["variants"])
    assert record["activated"] is True
    pins = cv.context.get("synth_pins") or {}
    assert set(pins.values()) == {
        record["synth_item_id"],
    }, "the kept variant is starred as its item's default"


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
    assert trace.get("redesign_stage") == "modified"
    redesigns = [
        r for iteration in trace["iterations"] for r in iteration.get("redesign") or []
    ]
    assert any(r["verdict"] == "kept" for r in redesigns), redesigns
    assert any(r.get("mode") == "modified" for r in redesigns), redesigns
    assert trace["redesign"].get("pending") is False


async def test_style_brief_redesign_escalates_once_and_keeps(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """A persistent fail-level `style` finding (an explicitly requested
    design language the render ignores) escalates the brief to the
    template designer — once, on the modified rung — and the clean
    review keeps it. The structural ladder stays independent."""
    from app.ai.agents.context import parse_context

    def _critique(schema, prompt):
        context = parse_context(prompt)
        iteration = int(context.get("iteration") or 0)
        if iteration < 2:
            return {
                "summary": "The render misses the requested look.",
                "issues": [
                    {
                        "level": "fail",
                        "area": "style",
                        "message": (
                            "The pages do not reflect the requested "
                            "Material 3 expressive style."
                        ),
                    }
                ],
                "coverage": {"covered": [], "dropped_knowingly": [], "missing": []},
            }
        return {
            "summary": "Restyled build looks ready.",
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
    assert trace.get("style_redesign_done") is True
    redesigns = [
        r for iteration in trace["iterations"] for r in iteration.get("redesign") or []
    ]
    assert any(r.get("mode") == "modified" for r in redesigns), redesigns
    assert any(r["verdict"] == "kept" for r in redesigns), redesigns
    assert trace.get("redesign_stage", "") == "", (
        "the structural ladder stays untouched by the style escalation"
    )


async def test_redesign_ladder_escapes_to_fresh_when_modified_reverts(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """The escalating ladder: the modified copy reverts (the critique
    keeps failing), the NEXT persistent fail drafts a from-scratch
    template — the stage advances modified → fresh and the run caps
    with the fresh redesign pending (plan 64 §3 ladder)."""

    def _critique(schema, prompt):
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

    monkeypatch.setitem(MOCK_FIXTURES, AITaskType.CV_BUILD_REVIEW.value, _critique)
    await _experience(client, auth_headers)
    result = await _generate(db, auth_headers)
    await db.commit()
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    trace = (await _latest_final_version(db, cv)).content["polish"]
    assert trace.get("redesign_stage") == "fresh"
    redesigns = [
        r for iteration in trace["iterations"] for r in iteration.get("redesign") or []
    ]
    assert any(
        r.get("verdict") == "reverted" and r.get("mode") == "modified"
        for r in redesigns
    ), redesigns
    fresh_verdicts = [r for r in redesigns if r.get("mode") == "fresh"]
    assert fresh_verdicts, "the ladder drafted the from-scratch template"
    assert (
        any(r.get("verdict") == "reverted" for r in fresh_verdicts)
        or (trace.get("redesign") or {}).get("pending") is True
    ), (fresh_verdicts, trace.get("redesign"))
    assert trace["outcome"]["status"] == "cap"


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


# --------------------------------------------------- budget cap + reviewer brief


def test_mock_over_budget_suggests_trim_not_widening():
    """The bank mock never widens the budget: an over-budget lint yields
    a content-trim op (skills max_items), never set_doc_options."""
    from app.ai.agents.cv_build_reviewer import _mock_build_critique
    from app.ai.schemas import CvBuildCritique

    from app.ai.agents.context import context_json

    prompt = "note\n" + context_json(
        {
            "lint": {
                "checks": [],
                "pages_actual": 2,
                "max_pages": 1,
                "pages_actual_over_budget": True,
                "empty_blocks": [],
            },
            "coverage": {"included": [], "dropped": [], "missing": []},
            "blocks": [
                {"index": 0, "kind": "header", "area": "main", "title": "Header"},
                {"index": 1, "kind": "skills", "area": "main", "title": "Skills"},
            ],
        }
    )
    critique = _mock_build_critique(CvBuildCritique, prompt)
    ops = [
        op for issue in critique["issues"] for op in (issue.get("suggested_ops") or [])
    ]
    assert ops, "the over-budget fail suggests densify + trim"
    assert ops[0]["operation"]["op"] == "update_design", (
        "densification rides first — tighter type and spacing"
    )
    assert ops[0]["operation"]["design"] == {
        "base_size_pt": 9,
        "spacing_scale": 0.9,
    }
    assert ops[1]["operation"]["op"] == "update_block_props"
    assert ops[1]["operation"]["props"]["max_items"] == 8
    assert not any(op["operation"]["op"] == "set_doc_options" for op in ops)


async def test_page_budget_is_a_hard_cap_and_notes_reach_the_review(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """The reviewer judges against the user's brief (user_notes) and can
    never raise the page budget: the fix applier rejects a suggested
    set_doc_options raise — the budget stays 1 while safe trims ride."""
    import app.services.cv_generate_service as service_module
    from app.ai.agents.context import parse_context

    async def memory_checkpointer():
        return InMemorySaver()

    monkeypatch.setattr(service_module, "get_checkpointer", memory_checkpointer)

    seen_notes: list[str] = []

    def _critique(schema, prompt):
        ctx = parse_context(prompt)
        seen_notes.append(str(ctx.get("user_notes") or ""))
        iteration = int(ctx.get("iteration") or 0)
        blocks = ctx.get("blocks") or []
        if iteration == 0:
            skills_index = next(
                (entry["index"] for entry in blocks if entry.get("kind") == "skills"),
                0,
            )
            return {
                "summary": "Over budget.",
                "issues": [
                    {
                        "level": "fail",
                        "area": "page_budget",
                        "message": "Two pages against a one-page budget.",
                        "suggested_ops": [
                            {
                                "operation": {
                                    "op": "set_doc_options",
                                    "max_pages": 3,
                                },
                                "rationale": "widen the budget",
                            },
                            {
                                "operation": {
                                    "op": "update_block_props",
                                    "block_index": skills_index,
                                    "props": {"max_items": 4},
                                },
                                "rationale": "trim the skills list",
                            },
                        ],
                    }
                ],
                "coverage": {"covered": [], "dropped_knowingly": [], "missing": []},
            }
        return {
            "summary": "Clean build.",
            "issues": [],
            "coverage": {"covered": [], "dropped_knowingly": [], "missing": []},
        }

    monkeypatch.setitem(MOCK_FIXTURES, AITaskType.CV_BUILD_REVIEW.value, _critique)
    await _experience(client, auth_headers)
    result = await CvGenerateService(db).generate(
        UUID(_uid(auth_headers)),
        CvGenerateRequest(
            language="en",
            length="concise",
            notes="Make it very modern with a side panel.",
            max_pages=1,
        ),
        run_id=uuid.uuid4(),
    )
    assert result["status"] == "completed"
    assert any(
        "Make it very modern with a side panel." == notes for notes in seen_notes
    ), "the reviewer prompt carried the user's brief"

    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    assert cv.max_pages == 1, "the page budget never grows"

    final = await _latest_final_version(db, cv)
    ops = [
        entry
        for iteration in final.content["polish"]["iterations"]
        for entry in iteration["ops"]
    ]
    widen = [entry for entry in ops if entry["op"] == "set_doc_options"]
    assert widen and widen[0]["ok"] is False, "the widening op was rejected"
    assert "budget stays 1" in widen[0]["detail"]
    trim = [entry for entry in ops if entry["op"] == "update_block_props"]
    assert trim and trim[0]["ok"] is True, "the safe trim still applied"


async def test_variant_grounding_failure_never_fails_the_run(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """A grounding error inside the fix node (e.g. stale refs the
    reviewer invented) degrades to a run warning — the loop finalizes."""
    from app.ai.agents.context import parse_context

    def _critique(schema, prompt):
        ctx = parse_context(prompt)
        iteration = int(ctx.get("iteration") or 0)
        if iteration == 0:
            return {
                "summary": "One content fix.",
                "issues": [
                    {
                        "level": "fail",
                        "area": "content",
                        "message": "Tighten the internship.",
                        "suggested_ops": [
                            {
                                "operation": {
                                    "op": "set_override",
                                    "source_key": "ghost-source",
                                    "item_id": "00000000-0000-0000-0000-000000000000",
                                    "field": "description",
                                    "value": "tightened",
                                },
                                "rationale": "bogus variant slot",
                            }
                        ],
                    }
                ],
                "coverage": {"covered": [], "dropped_knowingly": [], "missing": []},
            }
        return {
            "summary": "Clean build.",
            "issues": [],
            "coverage": {"covered": [], "dropped_knowingly": [], "missing": []},
        }

    monkeypatch.setitem(MOCK_FIXTURES, AITaskType.CV_BUILD_REVIEW.value, _critique)
    await _experience(client, auth_headers)
    result = await CvGenerateService(db).generate(
        UUID(_uid(auth_headers)),
        CvGenerateRequest(language="en", length="concise", max_pages=1),
        run_id=uuid.uuid4(),
    )
    assert result["status"] == "completed", "the run never crashes on grounding"


async def test_lint_measures_live_pages_when_engine_present(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """The estimate lies for dense two-column layouts — with the PDF
    engine present, lint measures the REAL page count and the budget
    fail stands (a 1.5-page CV is never 'fits in 1')."""
    from app.services.cv_export_service import CvExportService
    import app.services.cv_pdf_service as pdf_service

    await _experience(client, auth_headers)
    result = await CvGenerateService(db).generate(
        UUID(_uid(auth_headers)),
        CvGenerateRequest(language="en", length="standard", max_pages=1),
        run_id=uuid.uuid4(),
    )
    await db.commit()
    cv = await db.get(CvDocument, UUID(result["cv_id"]))

    async def _two_pages(html: str, page_size: str = "a4", max_images: int = 4):
        return pdf_service.PageMeasure(
            pages=2, source="pdf", images=[("image/png", b"a"), ("image/png", b"b")]
        )

    monkeypatch.setattr("app.services.cv_export_service.measure_pages", _two_pages)

    report = await CvExportService(db).lint_report(cv)
    metrics = report["metrics"]
    assert metrics["pages_actual"] == 2
    assert metrics["pages_actual_over_budget"] is True
    assert report["checks"], "lint still completes around the live measure"
    budget_fail = next(
        (check for check in report["checks"] if check.get("id") == "page_budget"),
        None,
    )
    assert budget_fail is not None and budget_fail["level"] == "fail", (
        "an over-budget build is a blocking lint fail for the gate, "
        "not a warn the reviewer can shrug off"
    )


async def test_lint_prefers_the_live_measure_over_a_stale_export_stamp(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """The last export's stamp ages with every edit — a live print of the
    CURRENT state always wins when the engine is present (plan 76)."""
    import app.services.cv_pdf_service as pdf_service
    from app.services.cv_export_service import CvExportService

    await _experience(client, auth_headers)
    result = await CvGenerateService(db).generate(
        UUID(_uid(auth_headers)),
        CvGenerateRequest(language="en", length="standard", max_pages=1),
        run_id=uuid.uuid4(),
    )
    await db.commit()
    cv = await db.get(CvDocument, UUID(result["cv_id"]))

    async def _live(html: str, page_size: str = "a4", max_images: int = 0):
        return pdf_service.PageMeasure(pages=2, source="pdf")

    async def _stale(self, cv):
        return 1

    monkeypatch.setattr("app.services.cv_export_service.measure_pages", _live)
    monkeypatch.setattr(CvExportService, "_measured_pages", _stale)
    metrics = (await CvExportService(db).lint_report(cv))["metrics"]
    assert metrics["pages_actual"] == 2, "the live measure beats the stale stamp"
    assert metrics["page_count_source"] == "pdf"


async def test_lint_falls_back_to_the_export_stamp_without_an_engine(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """Engine absent → the last export's real measurement still speaks
    (flagged as aging), never a silent guess."""
    from app.services.cv_export_service import CvExportService

    await _experience(client, auth_headers)
    result = await CvGenerateService(db).generate(
        UUID(_uid(auth_headers)),
        CvGenerateRequest(language="en", length="standard", max_pages=1),
        run_id=uuid.uuid4(),
    )
    await db.commit()
    cv = await db.get(CvDocument, UUID(result["cv_id"]))

    async def _unavailable(*_args, **_kwargs):
        from app.services.cv_pdf_service import PDFEngineUnavailable

        raise PDFEngineUnavailable("Server PDF engine not installed")

    async def _stale(self, cv):
        return 1

    monkeypatch.setattr("app.services.cv_export_service.measure_pages", _unavailable)
    monkeypatch.setattr(CvExportService, "_measured_pages", _stale)
    metrics = (await CvExportService(db).lint_report(cv))["metrics"]
    assert metrics["pages_actual"] == 1
    assert metrics["page_count_source"] == "last_export"


def test_gate_blocks_on_pages_actual_over_budget():
    """A measured/estimated over-budget metric blocks — the reviewer's
    opinion cannot clear a page overflow (plan 64 §3)."""
    state = _review_state(review_lint={"checks": [], "pages_actual_over_budget": True})
    assert route_after_review(state) == "fix"


def test_gate_finalizes_a_clean_budget():
    state = _review_state(review_lint={"checks": [], "pages_actual_over_budget": False})
    assert route_after_review(state) == "finalize"


def test_review_pages_truth_uses_the_worst_count():
    """The review's own PNG count overrides the lint story; when the two
    disagree the WORSE number stands — a tiny spillover always fails."""
    summary = {"checks": [], "pages_actual": 1, "pages_actual_over_budget": False}
    cv_draft._review_pages_truth(summary, 2, 1)
    assert summary["pages_actual"] == 2
    assert summary["pages_actual_over_budget"] is True

    flipped = {"checks": [], "pages_actual": 2, "pages_actual_over_budget": True}
    cv_draft._review_pages_truth(flipped, 1, 1)
    assert flipped["pages_actual"] == 2, "the flaked measure never downgrades"

    untouched = {"checks": [], "pages_actual": 1, "pages_actual_over_budget": False}
    cv_draft._review_pages_truth(untouched, 0, 1)
    assert untouched["pages_actual"] == 1, "no engine capture → lint stays"
