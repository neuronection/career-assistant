"""The versioned posting↔catalog golden benchmark (plan 50 P2b/P2c.2, plan 164 §4).

The fixture (``fixtures/posting_mapping_golden.json``, schema v2) is a
public/synthetic corpus: 164 cases over 123 jobs and 13 families, built by
keeping the original 17-case P2b slice and adding seven synthetic families
covering clear deterministic matches, wrong deterministic winners,
below-threshold lifts, margin/threshold abstentions, delta/blend boundary
cases, misleading semantic signals, draft-gated candidates, family-only
(S3-pending) rows, no-shared-skill rows, manual rows and terminal postings.
All names, roles and skills are synthetic; no private-integration or scraped
personal data is present. The semantic column is a **pinned oracle** for the
rerank policy — the real job↔posting match is covered by
``test_vector_retrieval_service.py`` and ``test_semantic_rerank.py``.

This test exercises the production decision path
(``catalog_candidates`` → ``decide_catalog`` → ``semantic_rerank_signal``)
twice: the deterministic baseline with both semantic switches off, then the
rerank with ``catalog.semantic_rerank`` on and the rescue still off. It also
asserts per-case parity with the in-memory calibration model so the committed
sweep report (``fixtures/posting_mapping_calibration.json``) cannot drift from
the real policy. ``candidate_recall@25`` is a real ceiling because 123 jobs
exceed K=25.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.extensions.sdk import RawPosting
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting, PostingSkill
from app.models.taxonomy_model import Skill
from app.services.postings import semantic_rerank as rerank_module
from app.services.postings import semantic_rescue as rescue_module
from app.services.postings.catalog_settings import (
    SEMANTIC_RERANK_KEY,
    SEMANTIC_RESCUE_KEY,
    set_switch,
)
from app.services.postings.mapping_candidates import score_catalog_candidates
from app.services.postings.postings_service import decide_catalog, upsert_posting
from app.services.postings.semantic_rerank import RERANK_MARGIN
from app.services.vector_retrieval_service import DocumentHit, RetrievalResult
from tests.posting_mapping_calibration import Policy, evaluate, load_corpus, simulate_case

FIXTURE = Path(__file__).parent / "fixtures" / "posting_mapping_golden.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


async def _skill(db, key: str, label: str | None = None) -> Skill:
    existing = (await db.execute(select(Skill).where(Skill.key == key))).scalars().first()
    if existing is not None:
        return existing
    row = Skill(key=key, label=label or key.replace("-", " ").title(), category="test")
    db.add(row)
    await db.flush()
    return row


async def _build_world(db, fixture: dict) -> dict[str, Job]:
    skills = {row["key"]: await _skill(db, row["key"], row["label"]) for row in fixture["skills"]}
    families = {}
    for row in fixture["families"]:
        family = JobFamily(key=row["key"], label=row["label"], path=row["path"])
        db.add(family)
        await db.flush()
        families[row["key"]] = family

    jobs: dict[str, Job] = {}
    for row in fixture["jobs"]:
        job = Job(
            code=row["code"],
            title=row["title"],
            family_id=families[row["family"]].id,
            short_description=row["description"],
            status=str(row.get("status") or "published"),
        )
        db.add(job)
        await db.flush()
        links = list(row.get("skills") or [])
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
        for link in links:
            skill = skills.get(link["key"])
            if skill is None:
                skill = await _skill(db, link["key"])
                skills[link["key"]] = skill
            db.add(
                JobSkill(
                    job_id=job.id,
                    skill_id=skill.id,
                    required_level=int(link["level"]),
                    importance=str(link["importance"]),
                )
            )
        await db.flush()
        jobs[row["code"]] = job
    return jobs


async def _posting_skill_ids(db, posting: JobPosting) -> set:
    return set(
        (
            await db.execute(
                select(PostingSkill.skill_id).where(PostingSkill.posting_id == posting.id)
            )
        )
        .scalars()
        .all()
    )


class _FakeIndexer:
    """The sanctioned ingest writer stand-in: the benchmark has no vector space."""

    space_name = "content"
    store = SimpleNamespace(
        active_space=lambda _name: SimpleNamespace(index_table=None),
        backend=SimpleNamespace(name="linear"),
    )

    async def index_document(self, **_kwargs):
        return SimpleNamespace(degraded=None)


class _FakeRetriever:
    """The pinned semantic oracle: job id → score from the fixture."""

    def __init__(self, scores: dict[str, float], job_ids: dict[str, str]) -> None:
        self.scores = scores
        self.job_ids = job_ids

    async def match_documents(self, **_kwargs) -> RetrievalResult:
        hits = tuple(
            DocumentHit(
                document_id=f"doc-{code}",
                kind="job",
                source_id=self.job_ids[code],
                score=score,
                per_view={"summary": score, "body": score},
            )
            for code, score in self.scores.items()
        )
        return RetrievalResult(
            hits=hits,
            space="content",
            space_key="golden-space",
            backend="linear",
        )


def _outcome(
    posting: JobPosting,
    case: dict,
    job_family: dict[str, str],
    job_code: dict[str, str],
    candidate_positions: dict[str, int | None],
) -> dict:
    mapped_id = str(posting.catalog_job_id) if posting.catalog_job_id else None
    mapped_job = job_code.get(mapped_id) if mapped_id else None
    return {
        "id": case["id"],
        "kind": case["kind"],
        "expected_job": case.get("expected_job"),
        "expected_family": case.get("expected_family"),
        "expected_outcome": case.get("expected_outcome"),
        "mapped_job": mapped_job,
        "mapped_family": job_family.get(mapped_id) if mapped_id else None,
        "method": posting.mapping_method,
        "candidate_rank": candidate_positions.get(case["id"]),
    }


async def test_golden_mapping_benchmark(db, source, monkeypatch):
    fixture = _fixture()
    jobs = await _build_world(db, fixture)
    job_ids = {code: str(job.id) for code, job in jobs.items()}
    job_code = {value: code for code, value in job_ids.items()}
    job_family = {str(jobs[row["code"]].id): row["family"] for row in fixture["jobs"]}

    async def _no_ai(*_args, **_kwargs):
        return {}

    monkeypatch.setattr("app.services.postings.postings_service._ai_extract_skills", _no_ai)

    await set_switch(db, SEMANTIC_RESCUE_KEY, False)
    await set_switch(db, SEMANTIC_RERANK_KEY, False)
    postings: dict[str, JobPosting] = {}
    for case in fixture["cases"]:
        posting = await upsert_posting(
            db,
            source,
            RawPosting(
                external_id=case["id"],
                title=case["title"],
                url=f"https://golden.example/{case['id']}",
                skills_raw=list(case["skills"]),
                raw={"description": case["description"]},
            ),
        )
        assert posting is not None
        if case["kind"] == "manual":
            manual_job = jobs[case["manual_job"]]
            posting.catalog_job_id = manual_job.id
            posting.mapping_method = "manual"
            posting.mapping_confidence = 1.0
            posting.mapping_reason = "manually mapped"
            posting.status = "mapped"
        elif case["kind"] == "terminal":
            posting.status = str(case["posting_status"])
        postings[case["id"]] = posting
    await db.flush()

    candidate_positions: dict[str, int | None] = {}
    for case in fixture["cases"]:
        skill_ids = await _posting_skill_ids(db, postings[case["id"]])
        candidates = await score_catalog_candidates(db, skill_ids)
        codes = [candidate.code for candidate in candidates]
        expected = case.get("expected_job")
        candidate_positions[case["id"]] = codes.index(expected) if expected in codes else None

    baseline = [
        _outcome(postings[case["id"]], case, job_family, job_code, candidate_positions)
        for case in fixture["cases"]
        if case["kind"] not in {"terminal"}
    ]
    baseline_metrics = evaluate(baseline)

    real_signal = rerank_module.semantic_rerank_signal

    async def _fake_signal(
        db_session,
        posting,
        deterministic_candidates,
        *,
        threshold,
        margin=RERANK_MARGIN,
        indexer=None,
        retriever=None,
        skip_indexing=False,
    ):
        case = next(row for row in fixture["cases"] if row["id"] == posting.external_id)
        scores = {code: float(score) for code, score in (case.get("semantic") or {}).items()}
        return await real_signal(
            db_session,
            posting,
            deterministic_candidates,
            threshold=threshold,
            margin=margin,
            indexer=_FakeIndexer(),
            retriever=_FakeRetriever(scores, job_ids),
        )

    async def _no_rescue(*_args, **_kwargs):
        return rescue_module.not_run_signal()

    monkeypatch.setattr(rerank_module, "semantic_rerank_signal", _fake_signal)
    monkeypatch.setattr(rescue_module, "semantic_catalog_signal", _no_rescue)
    await set_switch(db, SEMANTIC_RERANK_KEY, True)

    reranked: list[dict] = []
    for case in fixture["cases"]:
        if case["kind"] == "terminal":
            continue
        posting = postings[case["id"]]
        skill_ids = await _posting_skill_ids(db, posting)
        await decide_catalog(db, posting, skill_ids)
        reranked.append(_outcome(posting, case, job_family, job_code, candidate_positions))
    await db.flush()

    rerank_metrics = evaluate(reranked)
    report = {
        "fixture": fixture["scale"],
        "baseline": {key: value for key, value in baseline_metrics.items() if key != "failures"},
        "rerank": {key: value for key, value in rerank_metrics.items() if key != "failures"},
        "rerank_failures": rerank_metrics["failures"],
    }
    print(json.dumps(report, indent=2))

    # The measured floors (plan 164 §4, plan 50 §13 P2): the rerank must beat
    # the deterministic baseline on precision/intent without regressing family
    # recall or candidate recall. The deterministic baseline keeps its known
    # wrong-winner and draft failures; the rerank corrects them.
    assert baseline_metrics["precision@1"] <= 0.90, report
    assert rerank_metrics["precision@1"] >= 0.95, report
    assert rerank_metrics["precision@1"] >= baseline_metrics["precision@1"] + 0.05, report
    assert rerank_metrics["family_recall@1"] >= 0.95, report
    assert rerank_metrics["abstention"] <= 0.30, report
    assert rerank_metrics["abstention"] < baseline_metrics["abstention"], report
    assert rerank_metrics["candidate_recall@25"] >= 0.99, report
    assert rerank_metrics["candidate_recall@200"] >= 0.99, report
    assert rerank_metrics["intent_accuracy"] >= 0.95, report
    assert rerank_metrics["spurious_maps"] == 0, report

    # The in-memory sweep model must reproduce the real DB path case for case.
    corpus = load_corpus()
    policy = Policy(
        tau_job=0.34,
        delta=RERANK_MARGIN,
        blend_deterministic=0.75,
        blend_semantic=0.25,
    )
    simulated = {
        row["id"]: row
        for row in (simulate_case(corpus, case, policy) for case in corpus.cases)
        if row["expected_outcome"] != "terminal"
    }
    for row in reranked:
        if row["expected_outcome"] == "manual":
            continue
        expected = simulated[row["id"]]
        assert row["mapped_job"] == expected["mapped_job"], (row["id"], row, expected)
        assert row["method"] == expected["method"], (row["id"], row, expected)

    # Named boundary cases from the expanded corpus.
    by_id = {row["id"]: row for row in reranked}
    for case_id in (
        "wrong-operations",
        "lift-operations",
        "draft-operations",
        "delta-operations",
    ):
        assert by_id[case_id]["method"] == "semantic_rerank", (case_id, by_id[case_id])
        assert by_id[case_id]["mapped_job"] == by_id[case_id]["expected_job"], case_id
    # The misleading semantic signal is correctly rejected: the deterministic
    # winner stays in place (the margin is under delta for the pinned blend).
    assert by_id["misleading-operations"]["method"] == "skill_overlap"
    assert (
        by_id["misleading-operations"]["mapped_job"]
        == by_id["misleading-operations"]["expected_job"]
    )
    for case_id in ("margin-operations", "threshold-operations"):
        assert by_id[case_id]["mapped_job"] is None, (case_id, by_id[case_id])
    assert by_id["none-operations-1"]["mapped_job"] is None
    assert by_id["family-operations-1"]["mapped_job"] is None
    assert postings["manual-operations-a"].mapping_method == "manual"
    assert postings["manual-operations-a"].mapping_reason == "manually mapped"
    assert postings["terminal-operations-expired"].status == "expired"
    assert postings["terminal-operations-hidden"].status == "hidden"

    features = postings["wrong-operations"].mapping_features
    assert features["schema_version"] == 1
    assert features["mapping_version"] == 2
    assert features["space_key"] == "golden-space"
    assert features["policy"]["tau_job"] == 0.34
    assert features["policy"]["delta"] == RERANK_MARGIN
    assert features["policy"]["k"] == 25
    assert features["policy"]["blend_deterministic"] == 0.75
    assert features["policy"]["blend_semantic"] == 0.25
    assert features["candidates"][0]["job_code"] == "operations-wrong-expected"
    assert len(features["candidates"]) <= 5
    assert all(len(row["shared_skills"]) <= 20 for row in features["candidates"])
