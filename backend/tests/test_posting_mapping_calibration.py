"""The committed P2c.2/210 calibration report is reproducible and honest.

The sweep itself lives in ``tests/posting_mapping_calibration.py`` (pure
in-memory, no DB/provider) and runs in milliseconds. This test pins the
committed report to the fixture, pins the live production constants to the
policy the report measures, and records the measured recommendation. Changing
the fixture or the simulation without regenerating the report fails here; the
report is regenerated with::

    cd backend && uv run python -m tests.posting_mapping_calibration --write

The recommendation is advisory only: the live thresholds stay at the shipped
point until the owner ratifies a change. The rerank OFF/ON pair is a separate
measured section, not a policy point; the runtime default stays OFF while the
matrix measures the ON counterfactual.
"""

from __future__ import annotations

import hashlib
import json

from app.services.postings.mapping_candidates import DEFAULT_CANDIDATE_K
from app.services.postings.mapping_score import TITLE_LAMBDA
from app.services.postings.postings_service import AUTO_MAP_THRESHOLD
from app.services.postings.semantic_rerank import (
    RERANK_BLEND_DETERMINISTIC,
    RERANK_BLEND_SEMANTIC,
    RERANK_CANDIDATE_K,
    RERANK_MARGIN,
)
from tests.posting_mapping_calibration import (
    BLEND_GRID,
    DELTA_GRID,
    FIXTURE_DELTA_PATH,
    MATRIX_RERANK,
    PRODUCTION_POLICY,
    REPORT_PATH,
    RUNTIME_RERANK_DEFAULT,
    TAU_JOB_GRID,
    TAU_LAMBDA_GRID,
    K,
    Policy,
    deterministic_candidates,
    load_corpus,
    render,
    simulate_case,
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


def test_the_golden_set_is_the_plan_210_size_and_covers_every_kind():
    corpus = load_corpus()
    assert len(corpus.cases) == 169
    assert len(corpus.jobs) == 131 > K, "candidate_recall@25 needs a catalog larger than K"
    assert len(corpus.skill_keys) == 146
    from collections import Counter

    assert dict(sorted(Counter(case["kind"] for case in corpus.cases).items())) == {
        "clear": 34,
        "coverage": 1,
        "delta": 7,
        "draft": 7,
        "family": 21,
        "lift": 10,
        "manual": 14,
        "margin": 9,
        "misleading": 7,
        "neutral_title": 1,
        "no_shared_skill": 22,
        "priority": 1,
        "terminal": 14,
        "threshold": 9,
        "title": 2,
        "wrong": 10,
    }
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
        "coverage",
        "title",
        "neutral_title",
        "priority",
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
        assert isinstance(case.get("skill_meta", {}), dict)
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
    assert report["matrix"]["blend"] == [list(pair) for pair in BLEND_GRID]
    assert report["matrix"]["title_lambda"] == list(TAU_LAMBDA_GRID)
    assert report["matrix"]["k"] == K
    expected_points = len(TAU_JOB_GRID) * len(DELTA_GRID) * len(BLEND_GRID) * len(TAU_LAMBDA_GRID)
    assert expected_points == 180
    assert report["matrix"]["points"] == len(report["results"]) == expected_points
    assert report["runtime_default"] == RUNTIME_RERANK_DEFAULT == "off"
    assert report["held_fixed"]["k"] == K
    assert report["held_fixed"]["published_only_rerank"] is True
    assert report["held_fixed"]["shared_skill_gate"] is True
    assert report["held_fixed"]["rerank"] == MATRIX_RERANK == "on"
    assert report["held_fixed"]["rescue"].startswith("off")
    for row in report["results"]:
        assert row["title_lambda"] in TAU_LAMBDA_GRID
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

    comparison = report["rerank_comparison"]
    assert comparison["policy"]["title_lambda"] == TITLE_LAMBDA
    assert comparison["runtime_default"] == RUNTIME_RERANK_DEFAULT == "off"
    assert comparison["held_fixed"]["rerank"] == MATRIX_RERANK == "on"
    rows = {row["rerank"]: row for row in comparison["rows"]}
    assert set(rows) == {"off", "on"}
    for row in rows.values():
        assert row["candidate_recall@25"] >= 0.99
        assert 0.0 <= row["precision@1"] <= 1.0
        assert 0.0 <= row["abstention"] <= 1.0


def test_the_fixture_retuning_delta_is_recorded_and_hashed():
    report = _committed()
    retuning = report["fixture_retuning"]
    assert retuning["changed_jobs"] == 39
    assert retuning["delta_path"] == "backend/tests/fixtures/posting_mapping_fixture_delta.json"
    assert retuning["delta_sha256"] == hashlib.sha256(FIXTURE_DELTA_PATH.read_bytes()).hexdigest()
    delta = json.loads(FIXTURE_DELTA_PATH.read_text(encoding="utf-8"))
    assert delta["summary"]["existing_case_objects_changed"] == 0
    assert delta["summary"]["changed_jobs_only_fillers"] is True
    assert delta["summary"]["cases"] == {"before": 164, "after": 169, "additive": 5}
    assert delta["summary"]["jobs"] == {"before": 123, "after": 131, "changed": 39}
    assert len(delta["changed_jobs"]) == 39
    untouched = {
        (row["corpus"], row["formula"], row["rerank"]): (
            row["precision@1"],
            row["intent_accuracy"],
            row["abstention"],
        )
        for row in delta["untouched_corpus"]["rows"]
    }
    assert untouched[("base", "old hit/total", "on")] == (1.0, 1.0, 0.1935)
    assert untouched[("base", "old hit/total", "off")] == (0.6724, 0.6129, 0.3763)
    assert untouched[("base", "two-way coverage v3", "on")] == (0.9032, 0.7312, 0.0)
    assert untouched[("base", "two-way coverage v3", "off")] == (0.7033, 0.5591, 0.0215)
    assert untouched[("retuned", "two-way coverage v3", "on")] == (1.0, 1.0, 0.1837)
    assert untouched[("retuned", "two-way coverage v3", "off")] == (0.6429, 0.6429, 0.2857)


def test_lambda_is_empirically_discriminated():
    report = _committed()
    base = (PRODUCTION_POLICY[0], PRODUCTION_POLICY[1], PRODUCTION_POLICY[2], PRODUCTION_POLICY[3])
    rows = {
        row["title_lambda"]: row
        for row in report["results"]
        if (row["tau_job"], row["delta"], row["blend_deterministic"], row["blend_semantic"]) == base
    }
    assert rows[0.10]["precision@1"] > rows[0.05]["precision@1"]
    assert rows[0.10]["intent_accuracy"] > rows[0.05]["intent_accuracy"]


def test_the_in_memory_model_drops_the_zero_overlap_tail():
    corpus = load_corpus()
    case = next(row for row in corpus.cases if row["id"] == "no-shared-skill")
    assert deterministic_candidates(corpus, case, 0.20) == []


def test_the_golden_coverage_and_title_cases_pass_at_the_shipped_policy():
    corpus = load_corpus()
    policy = Policy(
        tau_job=PRODUCTION_POLICY[0],
        delta=PRODUCTION_POLICY[1],
        blend_deterministic=PRODUCTION_POLICY[2],
        blend_semantic=PRODUCTION_POLICY[3],
        title_lambda=PRODUCTION_POLICY[4],
    )
    outcomes = {case["id"]: simulate_case(corpus, case, policy) for case in corpus.cases}
    for case in corpus.cases:
        if case["kind"] not in {"coverage", "title", "neutral_title"}:
            continue
        assert outcomes[case["id"]]["mapped_job"] == case["expected_job"], case["id"]


def test_the_runtime_default_off_and_the_matrix_policy_are_measured():
    assert PRODUCTION_POLICY[:2] == (AUTO_MAP_THRESHOLD, RERANK_MARGIN)
    assert PRODUCTION_POLICY[2:] == (
        RERANK_BLEND_DETERMINISTIC,
        RERANK_BLEND_SEMANTIC,
        TITLE_LAMBDA,
    )
    assert RERANK_CANDIDATE_K == K == DEFAULT_CANDIDATE_K

    report = _committed()
    assert report["runtime_default"] == "off"
    assert report["held_fixed"]["rerank"] == "on"
    assert report["rerank_comparison"]["runtime_default"] == "off"
    matrix_point = next(
        row
        for row in report["results"]
        if (
            row["tau_job"],
            row["delta"],
            row["blend_deterministic"],
            row["blend_semantic"],
            row["title_lambda"],
        )
        == PRODUCTION_POLICY
    )
    assert matrix_point["precision@1"] >= 0.95
    assert matrix_point["family_recall@1"] >= 0.95
    assert matrix_point["abstention"] <= 0.30
    assert matrix_point["candidate_recall@25"] >= 0.99
    assert matrix_point["candidate_recall@200"] >= 0.99
    assert matrix_point["intent_accuracy"] >= 0.95

    recommendation = report["recommendation"]
    assert recommendation["production_policy"] == {
        "tau_job": PRODUCTION_POLICY[0],
        "delta": PRODUCTION_POLICY[1],
        "blend_deterministic": PRODUCTION_POLICY[2],
        "blend_semantic": PRODUCTION_POLICY[3],
        "title_lambda": PRODUCTION_POLICY[4],
    }
    assert recommendation["k"] == K
    assert "owner ratifies" in recommendation["rationale"]
    assert (
        recommendation["tau_job"],
        recommendation["delta"],
        recommendation["blend_deterministic"],
        recommendation["blend_semantic"],
        recommendation["title_lambda"],
    ) in {
        (
            row["tau_job"],
            row["delta"],
            row["blend_deterministic"],
            row["blend_semantic"],
            row["title_lambda"],
        )
        for row in report["results"]
    }
