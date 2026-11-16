"""The plan-210 weak-mapping review overlay (AD3)."""

from __future__ import annotations

import pytest

from app.models.posting_model import JobPosting
from app.services.postings.mapping_console_service import unmapped_list
from app.services.postings.mapping_outcome import is_weak_mapping
from app.services.postings.mapping_quality import create_samples, metrics
from app.services.postings.mapping_score import WEAK_SEMANTIC_CONFIDENCE
from tests.conftest import _make_posting


async def _review_posting(
    db,
    source,
    external_id: str,
    *,
    method: str,
    margin: float | None = None,
    confidence: float | None = None,
) -> JobPosting:
    posting = await _make_posting(
        db,
        source,
        external_id=external_id,
        title=external_id,
        skills_raw=[],
        raw={"description": "Synthetic weak-review case."},
    )
    posting.mapping_method = method
    posting.mapping_margin = margin
    posting.mapping_confidence = confidence
    posting.status = "mapped"
    await db.flush()
    return posting


def test_the_weak_predicate_covers_both_method_families():
    assert is_weak_mapping(method="skill_overlap", margin=0.05, confidence=None, delta=0.08)
    assert not is_weak_mapping(method="skill_overlap", margin=0.08, confidence=None, delta=0.08)
    assert not is_weak_mapping(method="skill_overlap", margin=None, confidence=None, delta=0.08)
    assert is_weak_mapping(
        method="semantic", margin=None, confidence=WEAK_SEMANTIC_CONFIDENCE - 0.01, delta=0.08
    )
    assert is_weak_mapping(
        method="semantic_rerank",
        margin=None,
        confidence=WEAK_SEMANTIC_CONFIDENCE - 0.01,
        delta=0.08,
    )
    assert not is_weak_mapping(
        method="semantic", margin=None, confidence=WEAK_SEMANTIC_CONFIDENCE, delta=0.08
    )
    assert not is_weak_mapping(method="manual", margin=0.01, confidence=0.1, delta=0.08)


async def test_the_queue_filters_and_reports_weak_rows(db, source):
    weak = await _review_posting(db, source, "weak-skill", method="skill_overlap", margin=0.02)
    strong = await _review_posting(db, source, "strong-skill", method="skill_overlap", margin=0.30)
    semantic = await _review_posting(
        db, source, "weak-semantic", method="semantic", confidence=0.60
    )

    only_weak = await unmapped_list(db, weak=True)
    weak_ids = {item["id"] for item in only_weak["items"]}
    assert weak_ids == {str(weak.id), str(semantic.id)}
    by_id = {item["id"]: item for item in only_weak["items"]}
    assert by_id[str(weak.id)]["weak"] is True
    assert by_id[str(weak.id)]["mapping_margin"] == pytest.approx(0.02)
    assert by_id[str(semantic.id)]["weak"] is True
    assert by_id[str(semantic.id)]["mapping_margin"] is None

    only_strong = await unmapped_list(db, weak=False)
    assert {item["id"] for item in only_strong["items"]} == {str(strong.id)}
    assert only_strong["items"][0]["weak"] is False
    assert only_strong["items"][0]["mapping_margin"] == pytest.approx(0.30)


async def test_samples_allocate_half_the_batch_to_weak_rows(db, source):
    weak_ids = set()
    for index in range(4):
        posting = await _review_posting(
            db, source, f"weak-{index}", method="skill_overlap", margin=0.01
        )
        weak_ids.add(posting.id)
    for index in range(4):
        await _review_posting(db, source, f"strong-{index}", method="skill_overlap", margin=0.5)

    reviews = await create_samples(db, count=4)
    assert len(reviews) == 4
    chosen_weak = [row for row in reviews if row.posting_id in weak_ids]
    assert len(chosen_weak) == 2, "half the batch is weak-first"


async def test_quality_metrics_report_the_weak_bucket(db, source):
    for index in range(3):
        await _review_posting(
            db, source, f"metric-weak-{index}", method="skill_overlap", margin=0.01
        )
    await _review_posting(db, source, "metric-strong", method="skill_overlap", margin=0.5)

    payload = await metrics(db)
    assert payload["weak"]["count"] == 3
    assert payload["weak"]["margin_floor"] == 0.08
    assert payload["weak"]["semantic_floor"] == WEAK_SEMANTIC_CONFIDENCE
    assert payload["weak"]["empty_until_sweep"] is False


async def test_quality_reports_the_empty_until_sweep_state(db):
    payload = await metrics(db)
    assert payload["weak"]["count"] == 0
    assert payload["weak"]["empty_until_sweep"] is True
