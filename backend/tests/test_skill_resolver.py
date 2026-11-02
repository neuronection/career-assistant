"""Plan 153 slice 2 — the pass-2 skill resolver: per-verdict validation,
the candidate-set trust boundary, mock determinism, and the audited call."""

from pydantic import ValidationError
from pytest import raises
from sqlalchemy import select

from app.ai.agents.skill_resolver import (
    MAX_LABELS_PER_CALL,
    SkillLabelVerdict,
    SkillResolution,
    _mock_skill_resolution,
    apply_label_verdicts,
    build_labels_prompt,
    resolve_skills,
)
from app.ai.gateway import StructuredAIError
from app.core.errors import AINotConfiguredError
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType


def _labels() -> list[dict]:
    return [
        {
            "label_ref": "l1",
            "raw_label": "typescript",
            "candidates": [
                {
                    "key": "typescript",
                    "label": "TypeScript",
                    "aliases": ["ts"],
                    "score": 1.0,
                    "signal": "exact",
                },
                {
                    "key": "javascript",
                    "label": "JavaScript",
                    "aliases": ["js"],
                    "score": 0.4,
                    "signal": "trigram",
                },
            ],
        },
        {
            "label_ref": "l2",
            "raw_label": "clojure",
            "candidates": [
                {
                    "key": "javascript",
                    "label": "JavaScript",
                    "aliases": [],
                    "score": 0.21,
                    "signal": "trigram",
                }
            ],
        },
    ]


def _reply(*verdicts: SkillLabelVerdict, bounded: bool = False) -> SkillResolution:
    return SkillResolution(verdicts=list(verdicts), bounded=bounded)


def _verdict(ref: str, match_key: str = "", confidence: float = 0.8) -> SkillLabelVerdict:
    return SkillLabelVerdict(
        label_ref=ref,
        match_key=match_key,
        new=not match_key,
        confidence=confidence,
        rationale="test verdict",
    )


def test_invented_key_degrades_to_new():
    """A match_key outside the label's own candidates — including a key
    offered under ANOTHER label — is never trusted: the label answers new."""
    result = apply_label_verdicts(
        _labels(),
        _reply(_verdict("l1", "python"), _verdict("l2", "typescript")),
    )
    by_ref = {v.label_ref: v for v in result.verdicts}
    assert by_ref["l1"].match_key == "" and by_ref["l1"].new
    assert by_ref["l2"].match_key == "" and by_ref["l2"].new
    assert not result.bounded


def test_offered_key_survives():
    result = apply_label_verdicts(
        _labels(),
        _reply(_verdict("l1", "typescript", 0.9), _verdict("l2", "", 0.7)),
    )
    by_ref = {v.label_ref: v for v in result.verdicts}
    assert by_ref["l1"].match_key == "typescript" and not by_ref["l1"].new
    assert by_ref["l1"].confidence == 0.9
    assert by_ref["l2"].new


def test_missing_or_unknown_answers_degrade_but_answer_every_label():
    """An unanswered label and a verdict for an unknown ref both resolve:
    every offered label is answered exactly once, unusable ones as new."""
    result = apply_label_verdicts(
        _labels(),
        _reply(_verdict("l1", "typescript"), _verdict("l9", "ghost")),
    )
    assert {v.label_ref for v in result.verdicts} == {"l1", "l2"}
    by_ref = {v.label_ref: v for v in result.verdicts}
    assert by_ref["l2"].new and by_ref["l2"].confidence == 0.0
    assert result.bounded


def test_duplicate_ref_keeps_first_answer():
    result = apply_label_verdicts(
        _labels(),
        _reply(_verdict("l1", "typescript"), _verdict("l1", "javascript")),
    )
    by_ref = {v.label_ref: v for v in result.verdicts}
    assert by_ref["l1"].match_key == "typescript"


def test_confidence_out_of_bounds_is_unusable():
    result = apply_label_verdicts(
        _labels(),
        _reply(_verdict("l1", "typescript", 1.5), _verdict("l2", "", 0.7)),
    )
    by_ref = {v.label_ref: v for v in result.verdicts}
    assert by_ref["l1"].new and by_ref["l1"].confidence == 0.0
    assert result.bounded
    assert not by_ref["l2"].new or by_ref["l2"].confidence == 0.7


def test_verdict_list_is_bounded():
    verdicts = [_verdict(f"l{i}") for i in range(MAX_LABELS_PER_CALL + 1)]
    try:
        SkillResolution(verdicts=verdicts)
    except ValidationError:
        return
    raise AssertionError("verdict list over the batch bound must not validate")


def test_mock_fixture_exact_top_and_new():
    """Deterministic mock: exact alias/key hit wins, else the top-scored
    candidate above its bar, else new — no provider involved."""
    labels = [
        {
            "label_ref": "a",
            "raw_label": "ts",
            "candidates": [
                {
                    "key": "typescript",
                    "label": "TypeScript",
                    "aliases": ["ts"],
                    "score": 0.3,
                    "signal": "trigram",
                }
            ],
        },
        {
            "label_ref": "b",
            "raw_label": "reactjs",
            "candidates": [
                {
                    "key": "react",
                    "label": "React",
                    "aliases": [],
                    "score": 0.8,
                    "signal": "trigram",
                }
            ],
        },
        {
            "label_ref": "c",
            "raw_label": "clojure",
            "candidates": [
                {
                    "key": "javascript",
                    "label": "JavaScript",
                    "aliases": [],
                    "score": 0.2,
                    "signal": "trigram",
                }
            ],
        },
    ]
    reply = SkillResolution.model_validate(
        _mock_skill_resolution(None, build_labels_prompt(labels))
    )
    by_ref = {v.label_ref: v for v in reply.verdicts}
    assert by_ref["a"].match_key == "typescript"
    assert by_ref["b"].match_key == "react"
    assert by_ref["c"].new and by_ref["c"].match_key == ""


async def test_resolve_skills_mock_end_to_end(db):
    """One audited gateway call on the mock provider; the reply is
    adjudicated, so every label answers within its own candidates."""
    result = await resolve_skills(db, _labels())
    assert result is not None
    by_ref = {v.label_ref: v for v in result.verdicts}
    assert by_ref["l1"].match_key == "typescript" and not by_ref["l1"].new
    assert by_ref["l2"].new
    assert not result.bounded
    rows = await db.execute(
        select(AIGeneration).where(AIGeneration.task_type == AITaskType.POSTING_SKILL_RESOLVE.value)
    )
    assert rows.scalars().first() is not None


async def test_resolve_skills_empty_batch_short_circuits(db):
    result = await resolve_skills(db, [])
    assert result is not None
    assert result.verdicts == []
    assert not result.bounded


async def test_resolve_skills_is_deterministic_under_the_mock(db):
    """Two identical batches produce byte-identical resolutions (the
    mock fixture, not a provider, answers — mock determinism law)."""
    first = await resolve_skills(db, _labels())
    second = await resolve_skills(db, _labels())
    assert first is not None and second is not None
    assert first == second


async def test_resolve_skills_pins_the_run_ref_on_the_audit_row(db):
    """Slice 3 pins the background-job id: run_id/run_stage ride the
    audit row through the gateway's RunRef opt-in."""
    from uuid import uuid4

    from app.ai.gateway import RunRef

    run_id = uuid4()
    await resolve_skills(db, _labels(), run=RunRef(id=run_id, stage="posting_extract.resolve"))
    row = (
        (
            await db.execute(
                select(AIGeneration)
                .where(AIGeneration.task_type == AITaskType.POSTING_SKILL_RESOLVE.value)
                .order_by(AIGeneration.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert str(row.run_id) == str(run_id)
    assert row.run_stage == "posting_extract.resolve"


async def test_resolve_skills_returns_none_when_the_provider_fails(db, monkeypatch):
    """A failed batch is a None, never an exception — the caller falls
    back to deterministic new proposals without re-billing."""

    async def _failing(*args, **kwargs):
        raise StructuredAIError("provider down")

    monkeypatch.setattr("app.ai.agents.skill_resolver.ainvoke_structured", _failing)
    assert await resolve_skills(db, _labels()) is None


async def test_resolve_skills_raises_when_unconfigured(db, monkeypatch):
    """Unconfigured AI is a loud AINotConfiguredError, never a silent
    None — the caller decides the deterministic fallback."""

    async def _unconfigured(*args, **kwargs):
        raise AINotConfiguredError("AI is not configured yet")

    monkeypatch.setattr("app.ai.agents.skill_resolver.ainvoke_structured", _unconfigured)
    with raises(AINotConfiguredError):
        await resolve_skills(db, _labels())
