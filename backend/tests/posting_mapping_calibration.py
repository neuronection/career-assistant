"""Deterministic offline calibration sweep for the plan-164 rerank policy.

This module is the P2c.2 sweep runner: it reads the committed golden corpus
(``tests/fixtures/posting_mapping_golden.json``), rebuilds the catalog and the
posting skill sets in memory using exactly the production candidate formula
(importance weight x required-level factor, ``hit / total``), and walks the
requested policy matrix through the same decision branches as
``decide_catalog``. It never touches the database or a provider, so the full
27-point matrix runs in well under a second and is safe as a PR gate. The
fixture is a synthetic/public corpus (no private-integration data).

Held fixed: ``K = 25``, the published-only rerank candidate filter, the
shared-skill gate and the manual/terminal rules. The plan-185 rescue is held
OFF so the matrix isolates the rerank policy; the golden benchmark test
proves the in-memory model against the real DB path for the shipped policy.

Regenerate the committed report with::

    cd backend && uv run python -m tests.posting_mapping_calibration --write

The report is committed at ``tests/fixtures/posting_mapping_calibration.json``
and ``test_posting_mapping_calibration.py`` fails when it drifts from the
fixture. The live constants stay at 0.34 / 0.08 / 0.75-0.25 until the owner
ratifies the recommendation; this module only measures.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.postings.fit.dimensions import IMPORTANCE_WEIGHT

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "posting_mapping_golden.json"
REPORT_PATH = Path(__file__).parent / "fixtures" / "posting_mapping_calibration.json"

TAU_JOB_GRID = (0.34, 0.40, 0.45)
DELTA_GRID = (0.05, 0.08, 0.10)
BLEND_GRID = ((0.75, 0.25), (0.70, 0.30), (0.80, 0.20))
K = 25
CANDIDATE_RECALL_FLOOR = 0.99
#: The shipped policy; the sweep must never change it, only measure it.
PRODUCTION_POLICY = (0.34, 0.08, 0.75, 0.25)


@dataclass(frozen=True)
class Policy:
    tau_job: float
    delta: float
    blend_deterministic: float
    blend_semantic: float
    k: int = K


@dataclass(frozen=True)
class Candidate:
    code: str
    family: str
    status: str
    score: float


@dataclass(frozen=True)
class JobDef:
    code: str
    family: str
    status: str
    weights: dict[str, float]


@dataclass(frozen=True)
class Corpus:
    jobs: dict[str, JobDef]
    cases: list[dict[str, Any]]
    family_count: int
    skill_count: int


def _link_weight(level: Any, importance: Any) -> float:
    weight = IMPORTANCE_WEIGHT.get(str(importance or "core"), 1.0)
    return weight * (min(int(level or 0), 10) / 10.0)


def _job_weights(row: dict[str, Any]) -> dict[str, float]:
    """Mirror the golden fixture's filler materialisation exactly."""
    links: list[dict[str, Any]] = list(row.get("skills") or [])
    fillers = row.get("fillers") or {}
    for index in range(int(fillers.get("count") or 0)):
        links.append(
            {
                "key": f"filler-{row['code']}-{index}",
                "level": int(fillers.get("level") or 10),
                "importance": str(fillers.get("importance") or "core"),
            }
        )
    for extra in fillers.get("extra") or []:
        links.append(
            {
                "key": f"filler-{row['code']}-extra-{len(links)}",
                "level": int(extra.get("level") or 10),
                "importance": str(extra.get("importance") or "core"),
            }
        )
    weights: dict[str, float] = {}
    for link in links:
        key = str(link["key"])
        weights[key] = weights.get(key, 0.0) + _link_weight(
            link.get("level"), link.get("importance")
        )
    return weights


def load_corpus(path: Path = FIXTURE_PATH) -> Corpus:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    jobs = {
        str(row["code"]): JobDef(
            code=str(row["code"]),
            family=str(row["family"]),
            status=str(row.get("status") or "published"),
            weights=_job_weights(row),
        )
        for row in fixture["jobs"]
    }
    return Corpus(
        jobs=jobs,
        cases=list(fixture["cases"]),
        family_count=len(fixture["families"]),
        skill_count=len(fixture["skills"]),
    )


def deterministic_candidates(corpus: Corpus, skill_keys: Iterable[str]) -> list[Candidate]:
    posting = {str(key) for key in skill_keys}
    candidates: list[Candidate] = []
    for job in corpus.jobs.values():
        total = sum(job.weights.values())
        if total <= 0:
            continue
        hit = sum(weight for key, weight in job.weights.items() if key in posting)
        candidates.append(
            Candidate(
                code=job.code,
                family=job.family,
                status=job.status,
                score=hit / total,
            )
        )
    candidates.sort(key=lambda item: (-item.score, item.code))
    return candidates


def _blend(deterministic: float, semantic: float, policy: Policy) -> float:
    return round(
        policy.blend_deterministic * deterministic + policy.blend_semantic * semantic,
        4,
    )


def _rerank(
    candidates: list[Candidate],
    case: dict[str, Any],
    policy: Policy,
) -> dict[str, Any] | None:
    """The published-only rerank over the deterministic set (production parity)."""
    published = [candidate for candidate in candidates if candidate.status == "published"]
    if not published:
        return None
    semantic = {str(code): float(score) for code, score in (case.get("semantic") or {}).items()}
    scored = [
        {
            "code": candidate.code,
            "family": candidate.family,
            "deterministic": round(candidate.score, 4),
            "semantic": round(semantic.get(candidate.code, 0.0), 4),
            "blend": _blend(candidate.score, semantic.get(candidate.code, 0.0), policy),
        }
        for candidate in published
    ]
    scored.sort(key=lambda row: (-row["blend"], -row["deterministic"], row["code"]))
    deterministic_top = published[0].code
    deterministic_cleared = published[0].score >= policy.tau_job
    top = scored[0]
    runner_up = scored[1]["blend"] if len(scored) > 1 else 0.0
    accepted = (
        top["blend"] >= policy.tau_job
        and (top["blend"] - runner_up) >= policy.delta
        and ((not deterministic_cleared) or top["code"] != deterministic_top)
    )
    return {
        "candidates": scored,
        "top": top["code"],
        "top_blend": top["blend"],
        "accepted": accepted,
        "deterministic_top": deterministic_top,
        "deterministic_cleared": deterministic_cleared,
    }


def simulate_case(corpus: Corpus, case: dict[str, Any], policy: Policy) -> dict[str, Any]:
    """One case through the production decision branches (rescue OFF)."""
    if case.get("expected_outcome") == "manual":
        return {
            "id": case["id"],
            "kind": case["kind"],
            "expected_job": case.get("expected_job"),
            "expected_family": case.get("expected_family"),
            "expected_outcome": "manual",
            "mapped_job": case.get("manual_job"),
            "mapped_family": (
                corpus.jobs[case["manual_job"]].family if case.get("manual_job") else None
            ),
            "method": "manual",
            "deterministic_top": None,
            "candidate_rank": None,
            "rerank_ran": False,
            "rerank_accepted": False,
        }

    candidates = deterministic_candidates(corpus, case.get("skills") or [])
    overlap_job = candidates[0] if candidates else None
    overlap_score = overlap_job.score if overlap_job is not None else None
    runner_up = candidates[1].score if len(candidates) > 1 else None
    overlap_cleared = overlap_score is not None and overlap_score >= policy.tau_job
    ambiguous = (
        bool(candidates)
        and overlap_score is not None
        and (overlap_score < policy.tau_job or (overlap_score - (runner_up or 0.0)) < policy.delta)
    )
    rerank = _rerank(candidates, case, policy) if ambiguous else None
    rerank_accepted = bool(rerank and rerank["accepted"])

    mapped_job: str | None = None
    method: str | None = None
    if case.get("expected_outcome") == "terminal":
        pass
    elif overlap_cleared and overlap_job is not None:
        if rerank_accepted and rerank is not None and rerank["top"] != overlap_job.code:
            mapped_job = rerank["top"]
            method = "semantic_rerank"
        else:
            mapped_job = overlap_job.code
            method = "skill_overlap"
    elif rerank_accepted and rerank is not None:
        mapped_job = rerank["top"]
        method = "semantic_rerank"

    expected = case.get("expected_job")
    rank = None
    if expected is not None:
        codes = [candidate.code for candidate in candidates]
        rank = codes.index(expected) if expected in codes else None

    return {
        "id": case["id"],
        "kind": case["kind"],
        "expected_job": expected,
        "expected_family": case.get("expected_family"),
        "expected_outcome": case.get("expected_outcome"),
        "mapped_job": mapped_job,
        "mapped_family": corpus.jobs[mapped_job].family if mapped_job in corpus.jobs else None,
        "method": method,
        "deterministic_top": overlap_job.code if overlap_job is not None else None,
        "candidate_rank": rank,
        "rerank_ran": rerank is not None,
        "rerank_accepted": rerank_accepted,
    }


def _rate(numerator: int, denominator: int, default: float = 1.0) -> float:
    return round(numerator / denominator, 4) if denominator else default


def evaluate(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    labelled = [
        row
        for row in outcomes
        if row["expected_outcome"] in {"job", "none"} and row["expected_job"] is not None
    ]
    decided = [row for row in labelled if row["mapped_job"] is not None]
    correct = [row for row in decided if row["mapped_job"] == row["expected_job"]]
    family_decided = [row for row in decided if row["expected_family"] is not None]
    family_correct = [
        row for row in family_decided if row["mapped_family"] == row["expected_family"]
    ]
    abstained = [row for row in labelled if row["mapped_job"] is None]
    intent_correct = [
        row
        for row in labelled
        if (row["expected_outcome"] == "job" and row["mapped_job"] == row["expected_job"])
        or (row["expected_outcome"] == "none" and row["mapped_job"] is None)
    ]
    spurious = [
        row
        for row in outcomes
        if row["expected_outcome"] == "none"
        and row["expected_job"] is None
        and row["mapped_job"] is not None
    ]
    family_cases = [row for row in outcomes if row["expected_outcome"] == "family"]
    family_fallback = [row for row in family_cases if row["mapped_family"] is not None]
    ranks = [row["candidate_rank"] for row in labelled if row["candidate_rank"] is not None]

    failures: dict[str, list[str]] = {}
    for row in labelled:
        ok = (row["expected_outcome"] == "job" and row["mapped_job"] == row["expected_job"]) or (
            row["expected_outcome"] == "none" and row["mapped_job"] is None
        )
        if not ok:
            failures.setdefault(str(row["kind"]), []).append(str(row["id"]))

    return {
        "precision@1": _rate(len(correct), len(decided)),
        "family_recall@1": _rate(len(family_correct), len(family_decided)),
        "abstention": _rate(len(abstained), len(labelled), default=0.0),
        "candidate_recall@25": _rate(sum(1 for rank in ranks if rank < 25), len(labelled)),
        "candidate_recall@200": _rate(sum(1 for rank in ranks if rank < 200), len(labelled)),
        "intent_accuracy": _rate(len(intent_correct), len(labelled), default=0.0),
        "family_fallback_rate": _rate(len(family_fallback), len(family_cases), default=0.0),
        "decided": len(decided),
        "correct": len(correct),
        "labelled": len(labelled),
        "spurious_maps": len(spurious),
        "family_only_cases": len(family_cases),
        "failures": {kind: ids[:8] for kind, ids in sorted(failures.items())},
    }


def _recommend(results: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in results if row["candidate_recall@25"] >= CANDIDATE_RECALL_FLOOR]
    if not eligible:  # pragma: no cover - the corpus always clears the floor
        eligible = results
    best = max(
        eligible,
        key=lambda row: (
            row["intent_accuracy"],
            row["precision@1"],
            -row["abstention"],
            -abs(row["tau_job"] - PRODUCTION_POLICY[0]),
            -abs(row["delta"] - PRODUCTION_POLICY[1]),
            -abs(row["blend_deterministic"] - PRODUCTION_POLICY[2]),
        ),
    )
    same_as_production = (
        best["tau_job"],
        best["delta"],
        best["blend_deterministic"],
        best["blend_semantic"],
    ) == PRODUCTION_POLICY
    return {
        "tau_job": best["tau_job"],
        "delta": best["delta"],
        "blend_deterministic": best["blend_deterministic"],
        "blend_semantic": best["blend_semantic"],
        "k": K,
        "matches_production": same_as_production,
        "production_policy": {
            "tau_job": PRODUCTION_POLICY[0],
            "delta": PRODUCTION_POLICY[1],
            "blend_deterministic": PRODUCTION_POLICY[2],
            "blend_semantic": PRODUCTION_POLICY[3],
        },
        "rationale": (
            "Highest intent accuracy, then precision@1, then the lowest abstention, "
            "among policies that keep candidate_recall@25 at or above the 0.99 floor; "
            "exact ties prefer the shipped tau/delta/blend point. The owner ratifies or "
            "rejects this recommendation; the live constants are unchanged in this slice."
        ),
    }


def run_matrix(
    corpus: Corpus,
    *,
    tau_grid: Iterable[float] = TAU_JOB_GRID,
    delta_grid: Iterable[float] = DELTA_GRID,
    blend_grid: Iterable[tuple[float, float]] = BLEND_GRID,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for tau in tau_grid:
        for delta in delta_grid:
            for blend_deterministic, blend_semantic in blend_grid:
                policy = Policy(
                    tau_job=float(tau),
                    delta=float(delta),
                    blend_deterministic=float(blend_deterministic),
                    blend_semantic=float(blend_semantic),
                )
                outcomes = [simulate_case(corpus, case, policy) for case in corpus.cases]
                metrics = evaluate(outcomes)
                results.append(
                    {
                        "tau_job": policy.tau_job,
                        "delta": policy.delta,
                        "blend_deterministic": policy.blend_deterministic,
                        "blend_semantic": policy.blend_semantic,
                        **metrics,
                    }
                )
    return {
        "schema_version": 1,
        "generated": "2026-11-03",
        "fixture": {
            "path": "backend/tests/fixtures/posting_mapping_golden.json",
            "cases": len(corpus.cases),
            "jobs": len(corpus.jobs),
            "families": corpus.family_count,
            "skills": corpus.skill_count,
        },
        "matrix": {
            "tau_job": list(TAU_JOB_GRID),
            "delta": list(DELTA_GRID),
            "blend": [list(pair) for pair in BLEND_GRID],
            "k": K,
            "points": len(results),
        },
        "held_fixed": {
            "k": K,
            "published_only_rerank": True,
            "shared_skill_gate": True,
            "rescue": "off (isolates the rerank policy)",
            "manual_rules": "manual rows are never overwritten",
            "terminal_rules": "terminal rows stay outside the remap domain",
        },
        "results": results,
        "recommendation": _recommend(results),
    }


def render(*, fixture_path: Path = FIXTURE_PATH) -> dict[str, Any]:
    return run_matrix(load_corpus(fixture_path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="rewrite the committed report")
    args = parser.parse_args()
    report = render()
    rendered = json.dumps(report, indent=2) + "\n"
    if args.write:
        REPORT_PATH.write_text(rendered, encoding="utf-8")
        print(f"wrote {REPORT_PATH} ({report['matrix']['points']} points)")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())


__all__ = [
    "BLEND_GRID",
    "DELTA_GRID",
    "PRODUCTION_POLICY",
    "TAU_JOB_GRID",
    "Candidate",
    "Corpus",
    "K",
    "Policy",
    "deterministic_candidates",
    "evaluate",
    "load_corpus",
    "main",
    "render",
    "run_matrix",
    "simulate_case",
]
