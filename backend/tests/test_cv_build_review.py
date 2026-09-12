"""Plan-64 slice 1: build-review task, state-aware mock fixture, coverage matrix."""

import json
from datetime import datetime, timezone

import app.ai.agents.cv_build_reviewer  # noqa: F401 — registers the mock fixture
from app.ai.gateway import ainvoke_structured
from app.ai.schemas import CvBuildCritique
from app.models.enums import AITaskType
from app.services.cv_context_service import CvContextItem, build_coverage_matrix

UPDATED_AT = datetime.now(timezone.utc)

BLOCKS = [
    {"kind": "items", "props": {"title": "Skills", "source_key": "skills"}},
    {"kind": "languages", "props": {"title": "Languages"}},
]

CLEAN_LINT = {"checks": [], "empty_blocks": [], "pages_actual_over_budget": False}

REVIEW_SYSTEM = "You review a generated CV for a final professional pass."


def _context(**overrides) -> dict:
    """The reviewer's host-side input: lint facts + coverage matrix + blocks."""
    context = {
        "lint": CLEAN_LINT,
        "coverage": {"covered": [], "missing": [], "dropped": []},
        "blocks": BLOCKS,
        "page_count": 1,
        "max_pages": 1,
        "iteration": 0,
    }
    context.update(overrides)
    return context


async def _review(db, context: dict) -> CvBuildCritique:
    prompt = (
        json.dumps(context, default=str)
        + "\n\nCONTEXT_JSON: "
        + json.dumps(context, default=str)
    )
    return await ainvoke_structured(
        db,
        AITaskType.CV_BUILD_REVIEW,
        CvBuildCritique,
        system=REVIEW_SYSTEM,
        user=prompt,
    )


async def test_clean_state_in_clean_out(db):
    critique = await _review(db, _context())
    assert critique.issues == []
    assert critique.summary == "Build looks ready."
    assert critique.coverage.missing == []


async def test_fail_lint_check_raises_fail_issue(db):
    lint = {
        "checks": [{"id": "contact_email", "level": "fail", "message": "No email."}],
        "empty_blocks": [],
        "pages_actual_over_budget": False,
    }
    critique = await _review(db, _context(lint=lint))
    assert len(critique.issues) == 1
    issue = critique.issues[0]
    assert issue.level == "fail"
    assert issue.area == "content"
    assert critique.coverage.missing == []


async def test_empty_block_triggers_one_move_op(db):
    lint = {
        "checks": [],
        "empty_blocks": ["languages"],
        "pages_actual_over_budget": False,
    }
    critique = await _review(db, _context(lint=lint))
    assert critique.issues[0].level == "warn"
    op = critique.issues[0].suggested_ops[0]
    assert op.operation.op == "move_block"
    assert op.operation.block_index == 1


async def test_page_budget_overrun_raises_fail_and_doc_option(db):
    lint = {
        "checks": [],
        "empty_blocks": [],
        "pages_actual_over_budget": True,
        "pages_actual": 2,
        "max_pages": 1,
    }
    critique = await _review(db, _context(lint=lint))
    issue = next(
        i for i in critique.issues if i.level == "fail" and i.area == "page_budget"
    )
    op = issue.suggested_ops[0]
    assert op.operation.op == "set_doc_options"
    assert op.operation.max_pages == 2


async def test_coverage_missing_suggests_include_selection_and_echo(db):
    """Per-round include/omit assessment: the coverage gap suggests a
    `set_context` op carrying the current selection + the missing item,
    not a generic max_items nudge."""
    coverage = {
        "included": [
            {"source_key": "skills", "item_id": "skill-2", "label": "Python"},
            {"source_key": "experience", "item_id": "exp-1", "label": "Intern"},
        ],
        "missing": [{"source_key": "skills", "item_id": "skill-1", "label": "SQL"}],
        "dropped": [],
    }
    critique = await _review(db, _context(coverage=coverage))
    issue = next(
        i for i in critique.issues if i.area == "coverage" and i.level == "warn"
    )
    op = issue.suggested_ops[0]
    assert op.operation.op == "set_context"
    assert op.operation.mode == "none"
    included_pairs = {(ref.source_key, ref.item_id) for ref in op.operation.include}
    assert ("skills", "skill-2") in included_pairs and (
        "experience",
        "exp-1",
    ) in included_pairs
    assert ("skills", "skill-1") in included_pairs
    assert critique.coverage.missing == ["skill-1"]
    assert critique.coverage.covered == ["skill-2", "exp-1"]


async def test_fixing_triggers_quiets_the_critique(db):
    dirty = {
        "checks": [],
        "empty_blocks": ["languages"],
        "pages_actual_over_budget": True,
        "pages_actual": 2,
        "max_pages": 1,
    }
    first = await _review(db, _context(lint=dirty))
    assert first.issues, "stateful: the critique reports a dirty build"
    fixed = {
        "checks": [],
        "empty_blocks": [],
        "pages_actual_over_budget": False,
    }
    second = await _review(db, _context(lint=fixed))
    assert second.issues == []


async def test_suggested_ops_round_trip_through_the_builder_union(db):
    lint = {
        "checks": [],
        "empty_blocks": ["languages"],
        "pages_actual_over_budget": True,
        "pages_actual": 2,
        "max_pages": 1,
    }
    critique = await _review(db, _context(lint=lint))
    ops = [s.operation for i in critique.issues for s in i.suggested_ops]
    kinds = {op.op for op in ops}
    assert {"move_block", "set_doc_options"} <= kinds


def test_coverage_matrix_buckets_by_inclusion_and_drops():
    items = {
        "skills": [
            CvContextItem(
                item_id="skill-1", label="SQL", payload={}, updated_at=UPDATED_AT
            ),
            CvContextItem(
                item_id="skill-2", label="Python", payload={}, updated_at=UPDATED_AT
            ),
        ],
        "education": [
            CvContextItem(
                item_id="edu-1", label="BSc", payload={}, updated_at=UPDATED_AT
            ),
        ],
    }
    matrix = build_coverage_matrix(
        items, included_ids={"skill-2"}, dropped={"edu-1": "user asked to drop"}
    )
    assert [ref.item_id for ref in matrix.included] == ["skill-2"]
    assert [ref.item_id for ref in matrix.dropped] == ["edu-1"]
    assert [ref.item_id for ref in matrix.missing] == ["skill-1"]
    assert matrix.model_dump()["missing"][0]["source_key"] == "skills"
