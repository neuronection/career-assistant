"""The versioned posting↔catalog golden benchmark (plan 50 P2b, plan 164 §4).

The fixture pins a representative slice of the plan-164 golden set: clear
deterministic matches, cases where the deterministic winner is wrong but the
bounded rerank can correct it, below-threshold cases the rerank lifts, and
ambiguous cases that must abstain on the threshold or the margin. The
semantic column is a **pinned oracle** for the rerank policy — the real
job↔posting match is covered by ``test_vector_retrieval_service.py`` and
``test_semantic_rerank.py``. This keeps the mapping benchmark deterministic
and CI-cheap while still measuring the production decision path
(``catalog_candidates`` → ``decide_catalog`` → ``semantic_rerank_signal``).

Scale: 17 cases / 32 jobs / 6 families. ``candidate_recall@25`` is a real
ceiling here because 32 jobs exceed K=25; @200 is reported for the plan-50
§14 acceptance note. The measured floors are pinned at the end of the test;
the failing cases (the deliberately ambiguous margin/threshold rows) are
named in the assertion messages.
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
from app.services.postings.catalog_settings import SEMANTIC_RESCUE_KEY, set_switch
from app.services.postings.mapping_candidates import score_catalog_candidates
from app.services.postings.postings_service import decide_catalog, upsert_posting
from app.services.postings.semantic_rerank import RERANK_MARGIN
from app.services.vector_retrieval_service import DocumentHit, RetrievalResult

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
            status="published",
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
    posting: JobPosting, case: dict, job_family: dict[str, str], job_code: dict[str, str]
) -> dict:
    mapped_id = str(posting.catalog_job_id) if posting.catalog_job_id else None
    return {
        "id": case["id"],
        "expected_job": case.get("expected_job"),
        "expected_family": case.get("expected_family"),
        "mapped_job": job_code.get(mapped_id) if mapped_id else None,
        "mapped_family": job_family.get(mapped_id) if mapped_id else None,
        "method": posting.mapping_method,
        "reason": posting.mapping_reason,
    }


def _metrics(outcomes: list[dict], candidate_positions: dict[str, int | None]) -> dict:
    labelled = [row for row in outcomes if row["expected_job"] is not None]
    decided = [row for row in labelled if row["mapped_job"] is not None]
    correct = [row for row in decided if row["mapped_job"] == row["expected_job"]]
    family_decided = [row for row in decided if row["expected_family"] is not None]
    family_correct = [
        row for row in family_decided if row["mapped_family"] == row["expected_family"]
    ]
    abstained = [row for row in labelled if row["mapped_job"] is None]
    positions = [position for position in candidate_positions.values() if position is not None]
    return {
        "precision@1": round(len(correct) / len(decided), 4) if decided else 1.0,
        "family_recall@1": (
            round(len(family_correct) / len(family_decided), 4) if family_decided else 1.0
        ),
        "abstention": round(len(abstained) / len(labelled), 4) if labelled else 0.0,
        "candidate_recall@25": (
            round(sum(1 for position in positions if position < 25) / len(labelled), 4)
            if labelled
            else 1.0
        ),
        "candidate_recall@200": (
            round(sum(1 for position in positions if position < 200) / len(labelled), 4)
            if labelled
            else 1.0
        ),
        "decided": len(decided),
        "labelled": len(labelled),
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
        postings[case["id"]] = posting
    await db.flush()

    baseline = [
        _outcome(postings[case["id"]], case, job_family, job_code) for case in fixture["cases"]
    ]
    candidate_positions: dict[str, int | None] = {}
    for case in fixture["cases"]:
        skill_ids = await _posting_skill_ids(db, postings[case["id"]])
        candidates = await score_catalog_candidates(db, skill_ids)
        codes = [candidate.code for candidate in candidates]
        expected = case.get("expected_job")
        candidate_positions[case["id"]] = codes.index(expected) if expected in codes else None

    baseline_metrics = _metrics(baseline, candidate_positions)

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
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)

    reranked: list[dict] = []
    for case in fixture["cases"]:
        posting = postings[case["id"]]
        skill_ids = await _posting_skill_ids(db, posting)
        await decide_catalog(db, posting, skill_ids)
        reranked.append(_outcome(posting, case, job_family, job_code))
    await db.flush()

    rerank_metrics = _metrics(reranked, candidate_positions)
    report = {
        "fixture": fixture["scale"],
        "baseline": baseline_metrics,
        "rerank": rerank_metrics,
        "baseline_failures": [
            row["id"] for row in baseline if row["mapped_job"] != row["expected_job"]
        ],
        "rerank_failures": [
            row["id"] for row in reranked if row["mapped_job"] != row["expected_job"]
        ],
    }
    print(json.dumps(report, indent=2))

    # The measured floors (plan 164 §4): the rerank must beat the
    # deterministic baseline on precision and abstention without regressing
    # candidate recall. The baseline's wrong-deterministic cases are named in
    # ``baseline_failures``; the rerank's remaining abstentions are the
    # deliberately ambiguous margin/threshold rows.
    assert baseline_metrics["precision@1"] >= 0.60, report
    assert rerank_metrics["precision@1"] >= 0.95, report
    assert rerank_metrics["precision@1"] >= baseline_metrics["precision@1"] + 0.05, report
    assert rerank_metrics["family_recall@1"] >= 0.95, report
    assert rerank_metrics["abstention"] <= 0.30, report
    assert rerank_metrics["abstention"] < baseline_metrics["abstention"], report
    assert baseline_metrics["candidate_recall@25"] >= 0.99, report
    assert rerank_metrics["candidate_recall@200"] >= 0.99, report

    wrong_case = next(row for row in reranked if row["id"] == "wrong-1")
    assert wrong_case["method"] == "semantic_rerank", report
    assert wrong_case["mapped_job"] == "wrong-expected-1", report
    lift_case = next(row for row in reranked if row["id"] == "lift-1")
    assert lift_case["method"] == "semantic_rerank", report
    margin_case = next(row for row in reranked if row["id"] == "margin-1")
    assert margin_case["mapped_job"] is None, "the margin floor abstains"
    threshold_case = next(row for row in reranked if row["id"] == "threshold-1")
    assert threshold_case["mapped_job"] is None, "the job floor abstains"

    features = postings["wrong-1"].mapping_features
    assert features["schema_version"] == 1
    assert features["mapping_version"] == 2
    assert features["space_key"] == "golden-space"
    assert features["policy"]["tau_job"] == 0.34
    assert features["policy"]["delta"] == RERANK_MARGIN
    assert features["policy"]["k"] == 25
    assert features["policy"]["blend_deterministic"] == 0.75
    assert features["policy"]["blend_semantic"] == 0.25
    assert features["candidates"][0]["job_code"] == "wrong-expected-1"
    assert len(features["candidates"]) <= 5
    assert all(len(row["shared_skills"]) <= 20 for row in features["candidates"])
