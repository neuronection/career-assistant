"""The catalog join (plan 185): ``decide_catalog`` evaluates TWO signals —
the deterministic weighted skill overlap (bit-identical when it clears)
and, only where that missed, the semantic cosine rescue under a
deterministic shared-evidence gate (≥1 resolved skill linked to both
posting and job). Every embedding failure degrades to the overlap-only
decision; runner-ups and raw scores land in
``posting_facts["mapping_signals"]``.

Vectors are crafted fixtures (``CAREER_MOCK_AI=1`` hash vectors are
unpredictable across texts) — the thresholds are asserted at their
boundaries, never tuned against a live model."""

import math

import pytest
from sqlalchemy import select

from app.extensions.sdk import RawPosting
from app.models.embedding_model import AIEmbedding
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting, PostingChange, PostingSkill
from app.models.taxonomy_model import Skill
from app.services.embedding_service import KIND_JOB, EmbeddingService
from app.services.postings.postings_service import (
    AUTO_MAP_THRESHOLD,
    decide_catalog,
    upsert_posting,
)

#: The posting's vector under the monkeypatched gateway embed — [1, 0].
A = [1.0, 0.0]


def _cos_vector(x: float) -> list[float]:
    """A 2-d unit vector with cosine ``x`` against A — boundary fixtures."""
    return [x, math.sqrt(max(0.0, 1.0 - x * x))]


async def _skill(db, key: str) -> Skill:
    row = Skill(key=key, label=key.upper(), category="test")
    db.add(row)
    await db.flush()
    return row


async def _job(
    db,
    code: str,
    family: JobFamily,
    links: list[tuple[Skill, int, str]],
    status: str = "published",
) -> Job:
    job = Job(
        code=code,
        title=code.replace("-", " ").title(),
        family_id=family.id,
        status=status,
    )
    db.add(job)
    await db.flush()
    for skill, level, importance in links:
        db.add(
            JobSkill(
                job_id=job.id,
                skill_id=skill.id,
                required_level=level,
                importance=importance,
            )
        )
    await db.flush()
    return job


async def _weak_job(db, family: JobFamily, sql: Skill, **extra) -> Job:
    """One weak hit: the posting's sql link carries almost no weight
    against two heavy level-10 links — overlap ≈ 0.05 < AUTO_MAP_THRESHOLD."""
    filler_a = await _skill(db, "filler-a")
    filler_b = await _skill(db, "filler-b")
    return await _job(
        db,
        "weak-overlap-role",
        family,
        [(sql, 1, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
        **extra,
    )


async def _embed_job(db, job: Job, vector: list[float]) -> None:
    await EmbeddingService(db).upsert_embedding(
        KIND_JOB, job.id, "job vector fixture", vector=vector, commit=False
    )


@pytest.fixture
def posting_vector(monkeypatch):
    """Pin the posting's gateway embed to the crafted fixture vector."""

    async def fake_embed_texts(_db, texts, **_kw):
        return [list(A) for _ in texts]

    monkeypatch.setattr("app.ai.gateway.embed_texts", fake_embed_texts)


async def _make_posting(db, source, external_id: str, skills: list[str]) -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=external_id,
            title=f"Role {external_id}",
            url=f"https://syn.example/{external_id}",
            skills_raw=skills,
            raw={},
        ),
    )
    await db.flush()
    return posting


async def test_keyword_strong_maps_exactly_as_today(db, source, posting_vector):
    """Overlap 1.0 ≥ AUTO_MAP_THRESHOLD → SKILL_OVERLAP, untouched fields
    (the semantic signal never runs) + the join trace in posting_facts."""
    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = JobFamily(key="join-family", label="Join", path="join-family")
    db.add(family)
    await db.flush()
    job = await _job(db, "strong-role", family, [(sql, 7, "core"), (python, 5, "core")])

    posting = await _make_posting(db, source, "join-strong", ["sql", "python"])

    assert posting.status == "mapped"
    assert posting.mapping_method == "skill_overlap"
    assert posting.catalog_job_id == job.id
    assert posting.mapping_confidence == 1.0
    assert "2 skills intersect" in posting.mapping_reason
    signals = posting.posting_facts["mapping_signals"]
    assert signals["overlap"]["score"] == 1.0
    assert signals["semantic"]["top"] is None, "the rescue never runs when overlap clears"

    rows = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == posting.id,
                    PostingChange.actor_kind == "retag",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2, "the skill rewrite and the decision journal separately"
    [decision] = [row for row in rows if "mapping_method" in (row.diff or {})]
    assert decision.operation["auto_map_threshold"] == AUTO_MAP_THRESHOLD
    assert decision.diff["mapping_method"]["to"] == "skill_overlap"
    [rewrite] = [row for row in rows if "mapping_method" not in (row.diff or {})]
    assert "skills" in (rewrite.diff or {}), "the rewrite row carries the skill set-diff"


async def test_keyword_weak_semantic_strong_maps_semantic(db, source, posting_vector):
    """The rescue: overlap missed, cosine ≥ threshold, ≥1 shared resolved
    skill → SEMANTIC maps onto the top candidate."""
    sql = await _skill(db, "sql")
    family = JobFamily(key="join-family2", label="Join2", path="join-family2")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)
    await _embed_job(db, job, _cos_vector(0.9))

    posting = await _make_posting(db, source, "join-semantic", ["sql"])

    assert posting.mapping_method == "semantic"
    assert posting.catalog_job_id == job.id
    assert posting.status == "mapped"
    signals = posting.posting_facts["mapping_signals"]
    assert signals["semantic"]["top"] == 0.9
    assert signals["overlap"]["score"] == pytest.approx(0.0476, abs=1e-3)
    [cand] = signals["semantic"]["candidates"]
    assert cand["code"] == "weak-overlap-role"


async def test_both_weak_stays_new_with_both_signals_in_the_reason(db, source, posting_vector):
    sql = await _skill(db, "sql")
    family = JobFamily(key="join-family3", label="Join3", path="join-family3")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)
    await _embed_job(db, job, _cos_vector(0.1))

    posting = await _make_posting(db, source, "join-weak", ["sql"])

    assert posting.status == "new"
    assert posting.mapping_method is None
    assert posting.catalog_job_id is None
    assert (
        f"best overlap {posting.posting_facts['mapping_signals']['overlap']['score']:.2f} "
        f"below 0.34; semantic top 0.10 below 0.6 — moderation"
    ) == posting.mapping_reason


async def test_zero_shared_skills_never_maps_semantically(db, source, posting_vector):
    """Cosine 1.0 but the top candidate shares NO resolved skill with the
    posting — the deterministic evidence gate keeps it unmapped (fit
    scoring would run blind on zero links)."""
    await _skill(db, "sql")  # the posting resolves it; the job never links it
    unrelated = await _skill(db, "filler-c")
    family = JobFamily(key="join-family4", label="Join4", path="join-family4")
    db.add(family)
    await db.flush()
    job = await _job(
        db,
        "no-shared-role",
        family,
        [(unrelated, 10, "core")],
    )
    await _embed_job(db, job, _cos_vector(1.0))

    posting = await _make_posting(db, source, "join-noshared", ["sql"])

    assert posting.mapping_method is None
    assert posting.catalog_job_id is None
    assert posting.status == "new"
    signals = posting.posting_facts["mapping_signals"]
    assert signals["semantic"]["top"] == 1.0, "the candidate ranked but never mapped"


async def test_draft_jobs_never_surface_as_semantic_candidates(db, source, posting_vector):
    sql = await _skill(db, "sql")
    family = JobFamily(key="join-family5", label="Join5", path="join-family5")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql, status="draft")
    await _embed_job(db, job, _cos_vector(1.0))

    posting = await _make_posting(db, source, "join-draft", ["sql"])

    assert posting.mapping_method is None
    assert posting.posting_facts["mapping_signals"]["semantic"]["candidates"] == []
    assert posting.status == "new"


@pytest.mark.parametrize(
    ("cosine_value", "maps"),
    [
        (0.6, True),  # the boundary is inclusive
        (0.59, False),
    ],
    ids=("at-threshold", "below-threshold"),
)
async def test_semantic_threshold_boundary(
    db, source, posting_vector, cosine_value: float, maps: bool
):
    sql = await _skill(db, "sql")
    family = JobFamily(key="join-family6", label="Join6", path="join-family6")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)
    await _embed_job(db, job, _cos_vector(cosine_value))

    posting = await _make_posting(db, source, f"join-boundary-{maps}", ["sql"])

    assert (posting.mapping_method == "semantic") is maps
    if maps:
        assert posting.mapping_confidence == cosine_value


async def test_unconfigured_embeddings_degrade_overlap_only(db, source, monkeypatch):
    """Any embedding failure → [] candidates, the overlap-only decision,
    the exact pre-plan reason and NO audit row (the gateway is never
    reached)."""

    async def broken_embed_texts(_db, texts, **_kw):
        raise RuntimeError("embeddings provider unconfigured")

    monkeypatch.setattr("app.ai.gateway.embed_texts", broken_embed_texts)

    sql = await _skill(db, "sql")
    family = JobFamily(key="join-family7", label="Join7", path="join-family7")
    db.add(family)
    await db.flush()
    await _weak_job(db, family, sql)

    posting = await _make_posting(db, source, "join-degrade", ["sql"])

    assert posting.mapping_method is None
    assert posting.status == "new"
    assert posting.mapping_reason == "best overlap 0.05 below 0.34 — moderation"
    signals = posting.posting_facts["mapping_signals"]
    assert signals["semantic"]["top"] is None
    assert signals["semantic"]["candidates"] == []
    rows = (
        (
            await db.execute(
                select(AIEmbedding).where(
                    AIEmbedding.entity_kind == "posting",
                    AIEmbedding.entity_id == posting.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == [], "the failed embed never lands a vector row"


async def test_mapping_signals_merge_preserves_other_facts(db, source, posting_vector):
    """``mapping_signals`` merges into posting_facts — apply_extract owns
    other keys in the same dict and must never be clobbered."""
    from sqlalchemy.orm.attributes import flag_modified

    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = JobFamily(key="join-family8", label="Join8", path="join-family8")
    db.add(family)
    await db.flush()
    await _job(db, "strong-role-2", family, [(sql, 7, "core"), (python, 5, "core")])

    posting = await _make_posting(db, source, "join-merge", ["sql", "python"])
    posting.posting_facts = {**(posting.posting_facts or {}), "languages": [{"code": "el"}]}
    flag_modified(posting, "posting_facts")
    await db.flush()

    from app.services.postings.postings_service import map_posting

    await map_posting(db, posting)

    facts = posting.posting_facts
    assert facts["languages"] == [{"code": "el"}]
    assert facts["mapping_signals"]["overlap"]["score"] == 1.0


async def test_manual_mapping_survives_resync(db, source):
    """MANUAL is a human decision — the mapping guard at the upsert
    callers keeps it, whatever the signals say."""
    from app.models.enums import MappingMethod

    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = JobFamily(key="join-family9", label="Join9", path="join-family9")
    db.add(family)
    await db.flush()
    job = await _job(db, "manual-role", family, [(sql, 8, "core"), (python, 6, "core")])

    posting = await _make_posting(db, source, "join-manual", [])
    posting.catalog_job_id = job.id
    posting.mapping_method = MappingMethod.MANUAL.value
    posting.mapping_confidence = 1.0
    posting.mapping_reason = "manually mapped by a moderator"
    posting.status = "mapped"
    await db.flush()

    resynced = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="join-manual",
            title="Role join-manual v2",
            url="https://syn.example/join-manual",
            skills_raw=["sql"],
            raw={},
        ),
    )
    await db.flush()

    assert resynced.id == posting.id
    assert resynced.mapping_method == MappingMethod.MANUAL.value
    assert resynced.catalog_job_id == job.id


async def test_decide_catalog_never_touches_skill_rows(db, source, posting_vector):
    """The seam decides; only map_posting's skill-writing path rewrites
    PostingSkill rows — levels/priority set by hand survive a re-decision."""
    sql = await _skill(db, "sql")
    family = JobFamily(key="join-family10", label="Join10", path="join-family10")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)
    await _embed_job(db, job, _cos_vector(0.95))

    posting = await _make_posting(db, source, "join-rows", ["sql"])
    assert posting.mapping_method == "semantic"
    row = (
        (await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id)))
        .scalars()
        .first()
    )
    row.required_level = 9
    row.priority = "must_have"
    await db.flush()

    await decide_catalog(db, posting, {sql.id})

    assert row.required_level == 9
    assert row.priority == "must_have"
