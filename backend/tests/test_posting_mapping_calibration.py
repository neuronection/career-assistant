"""The committed P2c.2 rerank calibration report is reproducible and honest.

The sweep itself lives in ``tests/posting_mapping_calibration.py`` (pure
in-memory, no DB/provider) and runs in milliseconds. This test pins the
committed report to the fixture, pins the live production constants to the
policy the report measures, and records the measured recommendation. Changing
the fixture or the simulation without regenerating the report fails here; the
report is regenerated with::

    cd backend && uv run python -m tests.posting_mapping_calibration --write

The recommendation is advisory only: the live constants below stay at the
shipped values until the owner ratifies a change.
"""

from __future__ import annotations

import json

from app.services.postings.mapping_candidates import DEFAULT_CANDIDATE_K
from app.services.postings.postings_service import AUTO_MAP_THRESHOLD
from app.services.postings.semantic_rerank import (
    RERANK_BLEND_DETERMINISTIC,
    RERANK_BLEND_SEMANTIC,
    RERANK_CANDIDATE_K,
    RERANK_MARGIN,
)
from tests.posting_mapping_calibration import (
    DELTA_GRID,
    PRODUCTION_POLICY,
    REPORT_PATH,
    TAU_JOB_GRID,
    K,
    load_corpus,
    render,
)


def _committed() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_the_calibration_report_is_reproducible():
    committed = _committed()
    recomputed = json.loads(json.dumps(render()))
    assert committed == recomputed, (
        "posting_mapping_calibration.json drifted from the fixture/simulation; "
        "regenerate with `uv run python -m tests.posting_mapping_calibration --write`"
    )


def test_the_golden_set_is_the_p2c2_size_and_covers_every_kind():
    corpus = load_corpus()
    assert 150 <= len(corpus.cases) <= 250
    assert len(corpus.jobs) > K, "candidate_recall@25 needs a catalog larger than K"
    assert len(corpus.jobs) >= 100
    kinds = {case["kind"] for case in corpus.cases}
    assert {
        "clear",
        "wrong",
        "lift",
        "margin",
        "threshold",
        "delta",
        "misleading",
        "draft",
        "family",
        "no_shared_skill",
        "manual",
        "terminal",
    } <= kinds
    for case in corpus.cases:
        assert case["id"]
        assert case["expected_outcome"] in {
            "job",
            "none",
            "family",
            "manual",
            "terminal",
        }
        assert isinstance(case.get("skills"), list)
        if case["expected_outcome"] == "job":
            assert case.get("expected_job") in corpus.jobs
            assert case.get("expected_family") == corpus.jobs[case["expected_job"]].family
        if case["expected_outcome"] == "manual":
            assert case.get("manual_job") in corpus.jobs
        if case["kind"] == "draft":
            assert case.get("draft_jobs")


def test_the_report_covers_the_full_policy_matrix():
    report = _committed()
    assert report["matrix"]["tau_job"] == list(TAU_JOB_GRID)
    assert report["matrix"]["delta"] == list(DELTA_GRID)
    assert report["matrix"]["k"] == K
    assert report["matrix"]["points"] == len(report["results"]) == 27
    assert report["held_fixed"]["k"] == K
    assert report["held_fixed"]["published_only_rerank"] is True
    assert report["held_fixed"]["shared_skill_gate"] is True
    assert report["held_fixed"]["rescue"].startswith("off")
    for row in report["results"]:
        for metric in (
            "precision@1",
            "family_recall@1",
            "abstention",
            "candidate_recall@25",
            "candidate_recall@200",
        ):
            assert metric in row
            assert 0.0 <= row[metric] <= 1.0
        assert isinstance(row["failures"], dict)


def test_the_shipped_policy_is_measured_and_the_recommendation_is_advisory():
    assert PRODUCTION_POLICY[:2] == (AUTO_MAP_THRESHOLD, RERANK_MARGIN)
    assert PRODUCTION_POLICY[2:] == (RERANK_BLEND_DETERMINISTIC, RERANK_BLEND_SEMANTIC)
    assert RERANK_CANDIDATE_K == K == DEFAULT_CANDIDATE_K

    report = _committed()
    shipped = next(
        row
        for row in report["results"]
        if (
            row["tau_job"],
            row["delta"],
            row["blend_deterministic"],
            row["blend_semantic"],
        )
        == PRODUCTION_POLICY
    )
    assert shipped["precision@1"] >= 0.95
    assert shipped["family_recall@1"] >= 0.95
    assert shipped["abstention"] <= 0.30
    assert shipped["candidate_recall@25"] >= 0.99
    assert shipped["candidate_recall@200"] >= 0.99
    assert shipped["intent_accuracy"] >= 0.95

    recommendation = report["recommendation"]
    assert recommendation["production_policy"] == {
        "tau_job": PRODUCTION_POLICY[0],
        "delta": PRODUCTION_POLICY[1],
        "blend_deterministic": PRODUCTION_POLICY[2],
        "blend_semantic": PRODUCTION_POLICY[3],
    }
    assert recommendation["k"] == K
    assert "owner ratifies" in recommendation["rationale"]
    assert (
        recommendation["tau_job"],
        recommendation["delta"],
        recommendation["blend_deterministic"],
        recommendation["blend_semantic"],
    ) in {
        (row["tau_job"], row["delta"], row["blend_deterministic"], row["blend_semantic"])
        for row in report["results"]
    }
