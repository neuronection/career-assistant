"""— one-shot AI CV generation: registry wiring, the checkpointed
LangGraph run (mock provider e2e), clamping + per-section fallback,
queue flow (202 → job → builder-ready CV), sparse guard and the
503-when-unconfigured contract."""

import uuid
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.ai.agents.cv_drafter import _mock_cv_draft
from app.ai.schemas import CvDraftStructure, CvDraftTexts
from app.models.ai_model import AIGeneration
from app.models.cv_model import CvDocument, CvVersion
from app.schemas.cv_generate import CvGenerateRequest
from app.services.cv_generate_service import CvGenerateService
from app.services.job_worker import JobWorker

from tests.conftest import _uid

# ------------------------------------------------------------ registry wiring


def test_task_registered_in_registry():
    from app.ai.tasks import task_def

    definition = task_def("cv_draft")
    assert definition.tier == "strong"
    assert definition.requires == "text"


def test_prompt_version_registered():
    from app.ai.prompt_versions import prompt_version

    assert prompt_version("cv_draft") == "v1"


def test_job_type_registered_in_handlers():
    from app.services.job_worker import HANDLERS

    assert HANDLERS["cv_generate"] is not None


def test_mock_fixture_covers_both_calls():
    plan_prompt = (
        '"PLAN"\n\nCONTEXT_JSON: {"call": "plan", "enabled_kinds":'
        ' ["summary", "experience"], "available": {"summary":'
        ' [{"item_id": "summary", "label": "Objective"}], "experience":'
        ' [{"item_id": "exp-1", "label": "Intern"}]}}'
    )
    structure = CvDraftStructure.model_validate(
        _mock_cv_draft(CvDraftStructure, plan_prompt)
    )
    assert [section.kind for section in structure.sections] == [
        "summary",
        "experience",
    ]
    assert structure.sections[1].item_ids == ["exp-1"]

    write_prompt = (
        '"WRITE"\n\nCONTEXT_JSON: {"call": "write", "section":'
        ' {"kind": "experience", "item_ids": ["exp-1"]}, "items":'
        ' [{"item_id": "exp-1", "label": "Intern", "detail": "Acme",'
        ' "payload": {"description": "Shipped things.", "achievements":'
        ' [{"text": "Cut deploy time"}]}}]}'
    )
    texts = CvDraftTexts.model_validate(_mock_cv_draft(CvDraftTexts, write_prompt))
    assert texts.sections[0].items[0].item_id == "exp-1"
    assert texts.sections[0].items[0].text
    assert texts.sections[0].items[0].bullets == ["Cut deploy time"]


# ---------------------------------------------------------------- clamping


def _items_by_kind_context() -> dict:
    return {
        "items": [
            {
                "source_key": "experience",
                "item_id": "exp-1",
                "label": "Intern",
                "detail": "Acme",
                "payload": {},
            },
            {
                "source_key": "experience",
                "item_id": "exp-2",
                "label": "Volunteer",
                "detail": "Nice Org",
                "payload": {},
            },
        ]
    }


def test_clamp_plan_drops_unknown_kinds_and_ids():
    from app.ai.graphs.cv_draft import _clamp_plan, _items_by_kind

    structure = CvDraftStructure.model_validate(
        {
            "sections": [
                {"kind": "experience", "item_ids": ["exp-1", "bogus"]},
                {"kind": "basics", "item_ids": []},
                {"kind": "experience", "item_ids": ["exp-2"]},
            ]
        }
    )
    clamped = _clamp_plan(
        structure,
        ["experience", "summary"],
        _items_by_kind(_items_by_kind_context()),
    )
    assert [section["kind"] for section in clamped["sections"]] == ["experience"]
    assert clamped["sections"][0]["item_ids"] == ["exp-1"]


def test_plan_item_ids_unplanned_kind_gets_everything():
    from app.ai.graphs.cv_draft import _items_by_kind, _plan_item_ids

    context = _items_by_kind(_items_by_kind_context())
    assert _plan_item_ids({"sections": []}, "experience", context) == [
        "exp-1",
        "exp-2",
    ]


# ------------------------------------------------------------------- helpers


async def _experience(client, headers, **overrides) -> dict:
    body = {
        "title": "DevOps intern",
        "kind": "internship",
        "org_name": "Acme Cloud",
        "start": "2025-01-01",
        "end": "2025-12-31",
        "hours_per_week": 40,
        "description": "Deployed things.",
        "skills": [],
        "achievements": [{"text": "Cut deploy time 40%"}],
        **overrides,
    }
    created = await client.post("/api/v1/me/experience", json=body, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()


def _service(db) -> CvGenerateService:
    return CvGenerateService(db, checkpointer=InMemorySaver())


async def _drain(db) -> int:
    worker = JobWorker(db)
    executed = 0
    while await worker.run_once():
        executed += 1
    return executed


# ------------------------------------------------------------------ graph e2e


async def test_generate_end_to_end_mock_provider(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """collect → plan → draft → assemble: a builder-ready resume with an
    ai_apply recovery version, grounded overrides and a lint report."""
    await _experience(client, auth_headers)
    request = CvGenerateRequest(language="en", length="standard")
    result = await _service(db).generate(
        UUID(_uid(auth_headers)), request, run_id=uuid.uuid4()
    )
    await db.commit()
    assert result["status"] == "completed", result
    assert result["fallback_sections"] == []
    assert result["plan_fallback"] is False
    assert result["lint"]["checks"]

    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    assert cv is not None and cv.kind == "resume"
    assert cv.language == "en"
    blocks = cv.working_content["blocks"]
    assert blocks[0] == {"kind": "header"}
    kinds = [block["kind"] for block in blocks]
    assert "summary" in kinds and "items" in kinds
    assert cv.working_content["generated_by"] == "cv_draft"

    overrides = cv.working_content["overrides"]
    assert overrides["summary:summary"]["summary"]
    item_overrides = [
        patch
        for ref, patch in overrides.items()
        if ref.startswith("experience:") and isinstance(patch, dict)
    ]
    assert item_overrides and all(patch.get("description") for patch in item_overrides)

    versions = (
        (await db.execute(select(CvVersion).where(CvVersion.cv_document_id == cv.id)))
        .scalars()
        .all()
    )
    assert [version.created_by for version in versions] == ["ai_apply"]
    audited = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == "cv_draft")
            )
        )
        .scalars()
        .all()
    )
    assert len(audited) >= 2, "plan + per-section writes are audited"
    assert all(row.status == "ok" for row in audited)


async def test_plan_failure_falls_back_to_canonical_order(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    import app.ai.graphs.cv_draft as graph_module

    async def broken_plan(*args, **kwargs):
        raise RuntimeError("planner down")

    monkeypatch.setattr(graph_module, "plan_structure", broken_plan)
    await _experience(client, auth_headers)
    result = await _service(db).generate(
        UUID(_uid(auth_headers)), CvGenerateRequest(), run_id=uuid.uuid4()
    )
    await db.commit()
    assert result["status"] == "completed"
    assert result["plan_fallback"] is True
    assert any("standard order" in warning for warning in result["warnings"])
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    kinds = [block["kind"] for block in cv.working_content["blocks"]]
    assert kinds.index("summary") < kinds.index("items"), "canonical order kept"


async def test_section_failure_falls_back_to_profile_content(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """A section that cannot be drafted keeps its profile-derived block
    and lands in fallback_sections — never dropped, never fatal."""
    import app.ai.graphs.cv_draft as graph_module
    from app.ai.schemas import CvDraftTexts

    async def empty_draft(*args, **kwargs):
        return CvDraftTexts(sections=[])

    monkeypatch.setattr(graph_module, "draft_section", empty_draft)
    await _experience(client, auth_headers)
    result = await _service(db).generate(
        UUID(_uid(auth_headers)), CvGenerateRequest(), run_id=uuid.uuid4()
    )
    await db.commit()
    assert result["status"] == "completed"
    assert "experience" in result["fallback_sections"]
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    overrides = cv.working_content["overrides"]
    assert not any(ref.startswith("experience:") for ref in overrides), (
        "no fabricated description overrides"
    )
    item_blocks = [
        block for block in cv.working_content["blocks"] if block["kind"] == "items"
    ]
    assert item_blocks, "the experience section still renders from context"


async def test_cancelled_run_creates_no_cv(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    async def cancelled() -> bool:
        return True

    await _experience(client, auth_headers)
    result = await _service(db).generate(
        UUID(_uid(auth_headers)),
        CvGenerateRequest(),
        run_id=uuid.uuid4(),
        cancelled=cancelled,
    )
    await db.commit()
    assert result["status"] == "cancelled"
    cvs = (
        (
            await db.execute(
                select(CvDocument).where(CvDocument.user_id == UUID(_uid(auth_headers)))
            )
        )
        .scalars()
        .all()
    )
    assert cvs == []


async def test_sparse_selection_aborts(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """A selection that resolves nothing ends the run before planning."""
    request = CvGenerateRequest(
        sections=["experience"],
        context={"mode": "none", "include": [], "exclude": []},
    )
    result = await _service(db).generate(
        UUID(_uid(auth_headers)), request, run_id=uuid.uuid4()
    )
    await db.commit()
    assert result["status"] == "sparse"
    assert "No profile content" in result["error"]


async def test_run_resumes_from_checkpoint(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """A checkpoint sitting after `plan` continues (not restarts) on
    resume: the draft loop runs against the persisted plan."""
    from app.ai.graphs.cv_draft import GraphDeps, build_cv_draft_graph, initial_state

    await _experience(client, auth_headers)
    user_id = UUID(_uid(auth_headers))
    run_id = uuid.uuid4()
    deps = GraphDeps(db=db)
    graph = build_cv_draft_graph(deps, InMemorySaver())
    config = {"configurable": {"thread_id": str(run_id)}}
    state = initial_state(
        user_id=user_id,
        run_id=run_id,
        request=CvGenerateRequest(sections=["experience"]).model_dump(mode="json"),
    )
    graph.update_state(
        config,
        {
            **state,
            "plan": {
                "sections": [
                    {
                        "kind": "experience",
                        "source_key": "experience",
                        "item_ids": [],
                        "rationale": "",
                    }
                ]
            },
        },
        as_node="plan",
    )
    snapshot = graph.get_state(config)
    assert snapshot.values.get("plan"), "plan checkpointed"
    assert snapshot.next, "flow paused mid-graph"

    final = await graph.ainvoke(None, config)
    assert final.get("result", {}).get("cv_id")


# ------------------------------------------------------------------ API flow


async def test_api_generate_flow_202_to_builder(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """POST /cv/generate → 202 job → queue → CV list + status result."""
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
    job_id = created.json()["job_id"]

    await _drain(db)

    status = await client.get(f"/api/v1/cv/generate/{job_id}", headers=auth_headers)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["status"] == "succeeded"
    assert body["result"]["cv_id"]
    assert body["result"]["lint"]["checks"]
    assert body["result"]["fallback_sections"] == []

    cv_id = body["result"]["cv_id"]
    listing = await client.get("/api/v1/cv", headers=auth_headers)
    assert any(cv["id"] == cv_id for cv in listing.json())
    assert listing.json()[0]["working_content"]["generated_by"] == "cv_draft"

    versions = await client.get(f"/api/v1/cv/{cv_id}/versions", headers=auth_headers)
    assert versions.json()[0]["created_by"] == "ai_apply"

    lint = await client.get(f"/api/v1/cv/{cv_id}/lint", headers=auth_headers)
    assert lint.status_code == 200

    other = await client.get(
        f"/api/v1/cv/generate/{uuid.uuid4()}", headers=auth_headers
    )
    assert other.status_code == 404


async def test_api_generate_requires_profile_content(
    client, auth_headers, seeded_catalog
):
    """Sparse-profile guard: 422, never an empty generation."""
    response = await client.post("/api/v1/cv/generate", json={}, headers=auth_headers)
    assert response.status_code == 422, response.text
    assert "Nothing to generate" in response.json()["detail"]


async def test_api_generate_unknown_posting_404(
    client, auth_headers, profile_ready, seeded_catalog
):
    response = await client.post(
        "/api/v1/cv/generate",
        json={"target_posting_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_api_generate_validates_fields(client, auth_headers):
    bad_kind = await client.post(
        "/api/v1/cv/generate",
        json={"sections": ["basics"]},
        headers=auth_headers,
    )
    assert bad_kind.status_code == 422
    bad_pages = await client.post(
        "/api/v1/cv/generate", json={"max_pages": 9}, headers=auth_headers
    )
    assert bad_pages.status_code == 422


async def test_api_generate_unconfigured_503(
    client, auth_headers, profile_ready, seeded_catalog, monkeypatch
):
    """Production contract: nothing configured → 503 at enqueue time."""
    import app.services.cv_generate_service as service_module

    async def unconfigured(db, task, user_id=None):
        return None

    monkeypatch.setattr(service_module, "resolve_task_model", unconfigured)
    await _experience(client, auth_headers)
    response = await client.post("/api/v1/cv/generate", json={}, headers=auth_headers)
    assert response.status_code == 503, response.text
    jobs = await client.get("/api/v1/background-jobs", headers=auth_headers)
    assert jobs.json() == [], "no job was queued"


@pytest.mark.parametrize(
    "payload",
    [
        {"tone": "salty"},
        {"length": "epic"},
        {"language": "e"},
        {"notes": "x" * 2001},
    ],
)
async def test_api_generate_rejects_bad_preferences(client, auth_headers, payload):
    response = await client.post(
        "/api/v1/cv/generate", json=payload, headers=auth_headers
    )
    assert response.status_code == 422
