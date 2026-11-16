"""The pure mapping score core and the inverted candidate loader (plan 210 S1)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions.sdk import RawPosting
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting, PostingSkill
from app.models.taxonomy_model import Skill
from app.services.postings.mapping_candidates import score_catalog_candidates
from app.services.postings.mapping_features import MappingFeatures
from app.services.postings.mapping_outcome import MappingOutcomeReason
from app.services.postings.mapping_score import (
    SCORE_MODEL,
    SkillScore,
    candidate_order,
    job_skill_weight,
    job_skill_weights,
    posting_skill_weight,
    posting_skill_weights,
    score_breakdown,
    title_signal,
)
from app.services.postings.postings_service import decide_catalog, upsert_posting


async def _skill(db, key: str) -> Skill:
    existing = (await db.execute(select(Skill).where(Skill.key == key))).scalars().first()
    if existing is not None:
        return existing
    row = Skill(key=key, label=key.replace("-", " ").title(), category="test")
    db.add(row)
    await db.flush()
    return row


async def _family(db, key: str = "score-family") -> JobFamily:
    family = JobFamily(key=key, label=key.title(), path=key)
    db.add(family)
    await db.flush()
    return family


async def _job(
    db,
    code: str,
    family: JobFamily,
    links: list[tuple[Skill, int, str]],
    *,
    title: str | None = None,
    status: str = "published",
) -> Job:
    job = Job(
        code=code,
        title=title or code.replace("-", " ").title(),
        family_id=family.id,
        status=status,
    )
    db.add(job)
    await db.flush()
    for skill, level, importance in links:
        db.add(
            JobSkill(job_id=job.id, skill_id=skill.id, required_level=level, importance=importance)
        )
    await db.flush()
    return job


async def _make_posting(
    db, source, external_id: str, skills: list[str], title: str | None = None
) -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=external_id,
            title=title or f"Role {external_id}",
            url=f"https://syn.example/{external_id}",
            skills_raw=skills,
            raw={"description": "Synthetic mapping score case."},
        ),
    )
    await db.flush()
    return posting


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


async def _posting_weights(db, posting: JobPosting) -> dict:
    return posting_skill_weights(
        (
            await db.execute(
                select(
                    PostingSkill.skill_id,
                    PostingSkill.priority,
                    PostingSkill.required_level,
                ).where(PostingSkill.posting_id == posting.id)
            )
        ).all()
    )


async def _job_weights(db, job: Job) -> dict:
    return job_skill_weights(
        (await db.execute(select(JobSkill).where(JobSkill.job_id == job.id))).scalars().all()
    )


def test_pure_weights_and_harmonic_bounds():
    assert job_skill_weight("core", 10) == 3.0
    assert job_skill_weight("bonus", 5) == 0.5
    assert posting_skill_weight(None, None) == 1.0
    assert posting_skill_weight("unknown", None) == 1.0
    assert posting_skill_weight("must_have", None) == 3.0
    assert posting_skill_weight("nice_to_have", 5) == 1.0
    assert posting_skill_weight(None, 5) == 0.5

    perfect = score_breakdown({"a": 3.0, "b": 3.0}, {"a": 0.1, "b": 0.1})
    assert perfect == SkillScore(precision=1.0, recall=1.0, skill=1.0)
    no_intersection = score_breakdown({"a": 3.0}, {"b": 1.0})
    assert no_intersection.skill == 0.0
    partial = score_breakdown({"a": 3.0, "b": 3.0, "c": 3.0}, {"a": 1.0, "b": 1.0})
    assert partial.precision == pytest.approx(1.0)
    assert partial.recall == pytest.approx(2.0 / 3.0)
    assert partial.skill == pytest.approx(0.8)

    assert score_breakdown({}, {}) == SkillScore(precision=0.0, recall=0.0, skill=0.0)


def test_title_signal_exact_containment_trigram_and_boost():
    assert title_signal("Data Pipeline Engineer", "Data Pipeline Engineer") == 1.0
    assert title_signal("Data Engineer", "Senior Data Engineer") == 0.8
    assert 0.0 < title_signal("Data Engineer", "Data Enginer") <= 0.6
    assert title_signal("Data Engineer", "Marketing Manager") == 0.0
    assert candidate_order(0.34, 1.0, 0.1) == pytest.approx(0.44)
    assert candidate_order(1.0, 1.0, 0.2) == 1.0


async def test_inverted_loader_matches_a_full_scan_under_the_same_score(db):
    sql = await _skill(db, "score-sql")
    python = await _skill(db, "score-python")
    other = await _skill(db, "score-other")
    family = await _family(db)
    await _job(db, "score-a", family, [(sql, 10, "core"), (other, 10, "core")])
    await _job(db, "score-b", family, [(sql, 10, "core")])
    await _job(db, "score-c", family, [(other, 10, "core")])
    await _job(db, "score-d", family, [(python, 10, "core")])

    posting_weights = {sql.id: 1.0}
    rows = await db.execute(
        select(Job, JobSkill)
        .join(JobSkill, JobSkill.job_id == Job.id)
        .where(Job.status != "retired")
    )
    reference: list[tuple[str, float]] = []
    links: dict[str, list[JobSkill]] = {}
    jobs: dict[str, Job] = {}
    for job, link in rows:
        jobs[str(job.code)] = job
        links.setdefault(str(job.code), []).append(link)
    for code, job_links in links.items():
        breakdown = score_breakdown(job_skill_weights(job_links), posting_weights)
        if breakdown.skill <= 0:
            continue
        reference.append((code, breakdown.skill))
    reference.sort(key=lambda row: (-row[1], row[0]))

    loaded = await score_catalog_candidates(db, posting_weights)
    assert [(candidate.code, candidate.skill) for candidate in loaded] == reference
    assert {candidate.code for candidate in loaded} == {"score-a", "score-b"}


async def test_a_zero_intersection_posting_gets_no_candidate_not_below_threshold(db, source):
    orphan = await _skill(db, "score-orphan")
    family = await _family(db)
    await _job(db, "score-shared", family, [(orphan, 10, "core")])
    unknown = await _skill(db, "score-unknown")

    posting = await _make_posting(db, source, "score-zero-intersection", [unknown.key])
    skill_ids = await _posting_skill_ids(db, posting)
    assert skill_ids == {unknown.id}

    assert await score_catalog_candidates(db, await _posting_weights(db, posting)) == []

    await decide_catalog(db, posting, skill_ids, defer_semantic=False)
    await db.flush()
    assert posting.mapping_outcome_reason == MappingOutcomeReason.NO_CANDIDATE.value
    assert posting.mapping_margin is None


async def test_a_shared_skill_still_reports_below_threshold(db, source, monkeypatch):
    async def rescue_off(_db):
        return False

    monkeypatch.setattr(
        "app.services.postings.catalog_settings.semantic_rescue_enabled", rescue_off
    )
    sql = await _skill(db, "score-weak-sql")
    filler_a = await _skill(db, "score-weak-a")
    filler_b = await _skill(db, "score-weak-b")
    family = await _family(db, "score-weak-family")
    await _job(
        db,
        "score-weak-role",
        family,
        [(sql, 1, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
    )

    posting = await _make_posting(db, source, "score-weak", [sql.key])
    await decide_catalog(db, posting, await _posting_skill_ids(db, posting), defer_semantic=False)
    await db.flush()
    assert posting.mapping_outcome_reason == MappingOutcomeReason.BELOW_THRESHOLD.value
    assert posting.mapping_margin is None


async def test_the_title_orders_gated_candidates_but_skill_sets_confidence_and_margin(db, source):
    a = await _skill(db, "score-gate-a")
    b = await _skill(db, "score-gate-b")
    c = await _skill(db, "score-gate-c")
    filler = await _skill(db, "score-gate-filler")
    family = await _family(db, "score-gate-family")
    # A: covers a+b of the posting's a+b+c and carries a low-weight extra.
    # B: covers a+b only. A's exact title orders it above B; B is the
    # skill-ranked top, so the margin stays in skill units.
    title_winner = await _job(
        db,
        "score-title-winner",
        family,
        [(a, 10, "core"), (b, 10, "core"), (filler, 4, "core")],
        title="Data Engineer",
    )
    await _job(
        db,
        "score-skill-top",
        family,
        [(a, 10, "core"), (b, 10, "core")],
        title="Other Role",
    )

    posting = await _make_posting(
        db, source, "score-gate", [a.key, b.key, c.key], title="Data Engineer"
    )
    await decide_catalog(db, posting, await _posting_skill_ids(db, posting), defer_semantic=False)
    await db.flush()

    assert posting.mapping_method == "skill_overlap"
    assert posting.catalog_job_id == title_winner.id
    posting_weights = await _posting_weights(db, posting)
    skill_winner = score_breakdown(await _job_weights(db, title_winner), posting_weights).skill
    skill_top = score_breakdown(
        await _job_weights(
            db,
            (await db.execute(select(Job).where(Job.code == "score-skill-top"))).scalars().one(),
        ),
        posting_weights,
    ).skill
    assert posting.mapping_confidence == pytest.approx(skill_winner, abs=1e-3)
    signals = posting.posting_facts["mapping_signals"]
    assert signals["overlap"]["score"] == pytest.approx(skill_top, abs=1e-4)
    assert signals["overlap"]["runner_up"] == pytest.approx(skill_winner, abs=1e-4)
    assert posting.mapping_margin == pytest.approx(skill_top - skill_winner, abs=1e-3)
    features = posting.mapping_features
    assert features["schema_version"] == 2
    assert features["mapping_version"] == 3
    assert features["score_model"] == SCORE_MODEL
    assert features["gate"] == "skill"
    assert features["policy"]["title_lambda"] == pytest.approx(0.1)
    assert features["candidates"][0]["job_code"] == "score-title-winner"
    assert features["candidates"][0]["skill"] == pytest.approx(
        features["candidates"][0]["deterministic"], abs=1e-4
    )
    assert features["candidates"][0]["title"] == 1.0


async def test_the_ambiguity_margin_is_skill_ranked_not_order_ranked(db, source, monkeypatch):
    async def rerank_on(_db):
        return True

    monkeypatch.setattr("app.services.postings.catalog_settings.semantic_rerank_enabled", rerank_on)
    x = await _skill(db, "score-margin-x")
    y = await _skill(db, "score-margin-y")
    filler_a = await _skill(db, "score-margin-a")
    filler_b = await _skill(db, "score-margin-b")
    filler_c = await _skill(db, "score-margin-c")
    family = await _family(db, "score-margin-family")
    # The title winner has a slightly lower skill: order gap = 0.10 - 0.0157
    # = 0.0843 (>= delta), while the skill gap is 0.0157 (< delta). A bug that
    # ranked the ambiguity by order would not queue the rerank.
    skill_top = await _job(
        db,
        "score-margin-skill-top",
        family,
        [(x, 10, "core"), (y, 10, "core"), (filler_a, 10, "core")],
        title="Other Role",
    )
    title_winner = await _job(
        db,
        "score-margin-title-winner",
        family,
        [
            (x, 10, "core"),
            (y, 10, "core"),
            (filler_b, 10, "core"),
            (filler_c, 1, "core"),
        ],
        title="Data Engineer",
    )

    posting = await _make_posting(db, source, "score-margin", [x.key, y.key], title="Data Engineer")
    await decide_catalog(
        db,
        posting,
        await _posting_skill_ids(db, posting),
        defer_semantic=True,
    )
    await db.flush()

    signals = posting.posting_facts["mapping_signals"]
    assert signals["semantic_pending"] is True
    assert signals["semantic_pending_reason"] == "ambiguous deterministic outcome"
    assert posting.catalog_job_id == title_winner.id
    posting_weights = await _posting_weights(db, posting)
    skill_top_score = score_breakdown(await _job_weights(db, skill_top), posting_weights).skill
    title_winner_score = score_breakdown(
        await _job_weights(db, title_winner), posting_weights
    ).skill
    assert title_winner_score < skill_top_score
    assert skill_top_score - title_winner_score < 0.08
    assert candidate_order(title_winner_score, 1.0) - candidate_order(skill_top_score, 0.0) >= 0.08
    assert signals["overlap"]["score"] == pytest.approx(skill_top_score, abs=1e-4)
    assert signals["overlap"]["runner_up"] == pytest.approx(title_winner_score, abs=1e-4)
    assert posting.mapping_confidence == pytest.approx(title_winner_score, abs=1e-3)


async def test_a_title_boost_never_admits_an_ungated_candidate(db, source, monkeypatch):
    async def rescue_off(_db):
        return False

    monkeypatch.setattr(
        "app.services.postings.catalog_settings.semantic_rescue_enabled", rescue_off
    )
    a = await _skill(db, "score-gate2-a")
    c = await _skill(db, "score-gate2-c")
    filler_a = await _skill(db, "score-gate2-filler-a")
    filler_b = await _skill(db, "score-gate2-filler-b")
    family = await _family(db, "score-gate2-family")
    # Exact title, but the only shared skill is a level-1 core link against
    # two heavy fillers: skill is far below tau, so the title cannot admit it.
    await _job(
        db,
        "score-ungated",
        family,
        [(a, 1, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
        title="Exact Title",
    )

    posting = await _make_posting(db, source, "score-gate2", [a.key, c.key], title="Exact Title")
    await decide_catalog(db, posting, await _posting_skill_ids(db, posting), defer_semantic=False)
    await db.flush()
    assert posting.status != "mapped"


def test_a_v1_feature_row_still_validates():
    v1 = {
        "schema_version": 1,
        "mapping_version": 2,
        "space_key": None,
        "degraded": None,
        "policy": {
            "tau_job": 0.34,
            "delta": 0.08,
            "k": 25,
            "blend_deterministic": 0.75,
            "blend_semantic": 0.25,
            "semantic_threshold": 0.6,
            "semantic_min_shared_skills": 1,
        },
        "candidates": [
            {
                "job_code": "legacy-role",
                "job_id": "00000000-0000-0000-0000-000000000001",
                "deterministic": 0.5,
                "shared_skills": ["sql"],
            }
        ],
    }
    parsed = MappingFeatures.model_validate(v1)
    assert parsed.schema_version == 1
    assert parsed.policy.score_model is None
    assert parsed.candidates[0].title is None
