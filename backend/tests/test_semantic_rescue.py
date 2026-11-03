"""The semantic catalog rescue on the family vector store (plan 50 §7.2, P2a).

Two layers, tested separately so neither hides the other:

* the **signal** — ``semantic_catalog_signal`` indexes the posting through the
  sanctioned writer (once; an unchanged posting costs zero embeds), matches it
  view-pair to view-pair against the ``job`` documents and gates every
  candidate on the shared-skill evidence and the published status;
* the **decision** — ``decide_catalog`` is rescue-only: a cleared overlap
  decides bit-identically, the rescue may map only a candidate that clears the
  threshold *and* the shared-skill gate, and any embedding/index failure keeps
  the overlap-only verdict with the reason recorded in the trace.

Determinism comes from crafted vectors, not mock-model tuning: the signal
tests inject a deterministic embedder, the decision tests inject a signal.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.errors import AINotConfiguredError
from app.extensions.sdk import RawPosting
from app.models.ai_model import AIGeneration
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting
from app.models.taxonomy_model import Skill
from app.services.postings import semantic_rescue as rescue
from app.services.postings.catalog_settings import (
    SEMANTIC_RESCUE_KEY,
    set_switch,
)
from app.services.postings.postings_service import (
    AUTO_MAP_THRESHOLD,
    decide_catalog,
    upsert_posting,
)
from app.services.postings.semantic_rescue import (
    SEMANTIC_MAP_THRESHOLD,
    SemanticCandidate,
    SemanticSignal,
    semantic_catalog_signal,
)
from app.services.vector_index_service import VectorIndexService
from app.storage.vector_store import VectorStoreService

DIM = 8


# ------------------------------------------------------------------ world


def _token_vector(text: str, dim: int = DIM) -> list[float]:
    """A deterministic bag-of-tokens vector: shared words dominate cosine."""
    vector = [0.0] * dim
    for token in str(text).lower().replace("-", " ").split():
        vector[sum(ord(char) for char in token) % dim] += 1.0
    norm = sum(value * value for value in vector) ** 0.5 or 1.0
    return [value / norm for value in vector]


class TokenEmbedder:
    """Deterministic embeddings from the composed text (no provider/audit)."""

    def __init__(self) -> None:
        self.calls = 0
        self.texts: list[str] = []

    async def __call__(self, texts):
        self.calls += 1
        self.texts.extend(texts)
        return [_token_vector(text) for text in texts]


class BrokenEmbedder:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def __call__(self, texts):
        raise self.error


async def _skill(db, key: str) -> Skill:
    existing = (await db.execute(select(Skill).where(Skill.key == key))).scalars().first()
    if existing is not None:
        return existing
    row = Skill(key=key, label=key.upper(), category="test")
    db.add(row)
    await db.flush()
    return row


async def _job(
    db,
    code: str,
    family: JobFamily,
    links: list[tuple[Skill, int, str]],
    *,
    title: str | None = None,
    description: str = "",
    status: str = "published",
) -> Job:
    job = Job(
        code=code,
        title=title or code.replace("-", " ").title(),
        family_id=family.id,
        short_description=description,
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


async def _posting(
    db, source, external_id: str, skills: list[str], *, title: str = "", description: str = ""
) -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=external_id,
            title=title or f"Role {external_id}",
            url=f"https://syn.example/{external_id}",
            skills_raw=skills,
            raw={"description": description} if description else {},
        ),
    )
    assert posting is not None
    await db.flush()
    return posting


async def _weak_job(db, family: JobFamily, sql: Skill, *, status: str = "published") -> Job:
    """One weak hit against two heavy level-10 links (overlap ≈ 0.05)."""
    filler_a = await _skill(db, "filler-a")
    filler_b = await _skill(db, "filler-b")
    return await _job(
        db,
        "weak-overlap-role",
        family,
        [(sql, 1, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
        status=status,
    )


# ----------------------------------------------------- signal: real store


async def _indexed_world(db, _engine, source):
    """A posting (quantum pipelines) and three catalog jobs sharing ``python``."""
    family = JobFamily(key="rescue-family", label="Rescue", path="rescue-family")
    db.add(family)
    await db.flush()
    python = await _skill(db, "python")
    right = await _job(
        db,
        "quantum-pipeline-engineer",
        family,
        [(python, 8, "core")],
        title="Quantum Pipeline Engineer",
        description="Builds quantum pipelines for the fleet.",
    )
    wrong = await _job(
        db,
        "garden-caretaker",
        family,
        [(python, 8, "core")],
        title="Garden Caretaker",
        description="Tends the gardens.",
    )
    draft = await _job(
        db,
        "draft-quantum-pipeline-engineer",
        family,
        [(python, 8, "core")],
        title="Quantum Pipeline Engineer",
        description="Builds quantum pipelines for the fleet.",
        status="draft",
    )
    posting = await _posting(
        db,
        source,
        "rescue-quantum",
        ["python"],
        title="Quantum Pipeline Engineer",
        description="Builds quantum pipelines for the fleet.",
    )
    embedder = TokenEmbedder()

    def _indexer() -> VectorIndexService:
        return VectorIndexService(db, embedder=embedder)

    for job in (right, wrong, draft):
        await VectorIndexService(db, embedder=embedder).index_document(
            kind="job", source_id=str(job.id)
        )
    return right, wrong, draft, posting, embedder, _indexer


async def test_the_signal_ranks_a_published_gated_job_above_the_rest(db, source):
    right, _wrong, draft, posting, _embedder, indexer = await _indexed_world(db, None, source)
    posting_skills = {
        row.skill_id
        for row in (await db.execute(select(JobSkill).where(JobSkill.job_id == right.id))).scalars()
    }

    signal = await semantic_catalog_signal(
        db, posting, posting_skills, indexer=indexer(), retriever=None
    )

    assert signal.degraded is None
    assert signal.threshold == SEMANTIC_MAP_THRESHOLD
    assert signal.space_key
    codes = [candidate.code for candidate in signal.candidates]
    assert codes[0] == "quantum-pipeline-engineer", "the shared title/description wins"
    assert "garden-caretaker" in codes
    assert draft.code not in codes, "a draft job is never a rescue candidate"
    assert all(candidate.shared_skills >= 1 for candidate in signal.candidates)
    assert signal.candidates[0].per_view, "per-view scores ride the trace"
    assert signal.top == pytest.approx(signal.candidates[0].score)


async def test_the_ingest_path_never_provisions_a_space(db, source):
    """No request-time DDL: with no content space the rescue reports
    ``index_missing`` and embeds nothing — provisioning belongs to the
    migration/CLI/job, never the posting write."""
    family = JobFamily(key="no-space-family", label="NoSpace", path="no-space-family")
    db.add(family)
    await db.flush()
    python = await _skill(db, "python")
    await _job(db, "no-space-role", family, [(python, 8, "core")])
    posting = await _posting(db, source, "rescue-no-space", ["python"])
    embedder = TokenEmbedder()

    signal = await semantic_catalog_signal(
        db, posting, {python.id}, indexer=VectorIndexService(db, embedder=embedder)
    )

    assert signal.degraded == "index_missing"
    assert signal.candidates == ()
    assert embedder.calls == 0, "no space ⇒ no embedding, no DDL"
    from app.core.database import sync_engine
    from app.storage.vector_backends import VectorSpaceNotFound

    try:
        VectorStoreService(sync_engine).active_space("content")
    except VectorSpaceNotFound:
        pass
    else:  # pragma: no cover - the assertion is the absence
        pytest.fail("the ingest path must not create a vector space")


async def test_the_signal_indexes_the_posting_before_the_match(db, source):
    _right, _wrong, _draft, posting, embedder, indexer = await _indexed_world(db, None, source)
    calls_before = embedder.calls
    posting_skills = {row.skill_id for row in (await db.execute(select(JobSkill))).scalars()}

    await semantic_catalog_signal(db, posting, posting_skills, indexer=indexer())
    from app.core.database import sync_engine

    store = VectorStoreService(sync_engine)
    space = store.active_space("content")
    assert store.find_document(space, kind="posting", source_id=str(posting.id)) is not None
    assert embedder.calls > calls_before, "the ingest decision embeds through the writer"

    calls_after_index = embedder.calls
    await semantic_catalog_signal(db, posting, posting_skills, indexer=indexer())
    assert embedder.calls == calls_after_index, "an unchanged posting costs zero embeds"


async def test_a_zero_shared_skill_posting_never_reaches_the_ann(db, source):
    _right, _wrong, _draft, posting, embedder, indexer = await _indexed_world(db, None, source)
    calls_before = embedder.calls

    signal = await semantic_catalog_signal(db, posting, set(), indexer=indexer())

    assert signal == SemanticSignal()
    assert embedder.calls == calls_before, "no skills ⇒ the gate cannot be passed; no work"


async def test_an_unconfigured_provider_degrades_without_failing_the_decision(db, source):
    _right, _wrong, _draft, posting, _embedder, _indexer = await _indexed_world(db, None, source)
    posting_skills = {row.skill_id for row in (await db.execute(select(JobSkill))).scalars()}

    signal = await semantic_catalog_signal(
        db,
        posting,
        posting_skills,
        indexer=VectorIndexService(db, embedder=BrokenEmbedder(AINotConfiguredError("none"))),
    )

    assert signal.degraded == "provider_unassigned"
    assert signal.candidates == ()
    assert signal.top is None


async def test_an_embed_error_degrades_to_the_overlap_only_verdict(db, source):
    _right, _wrong, _draft, posting, _embedder, _indexer = await _indexed_world(db, None, source)
    posting_skills = {row.skill_id for row in (await db.execute(select(JobSkill))).scalars()}

    signal = await semantic_catalog_signal(
        db,
        posting,
        posting_skills,
        indexer=VectorIndexService(db, embedder=BrokenEmbedder(RuntimeError("gateway down"))),
    )

    assert signal.degraded == "embed_failed"
    assert signal.candidates == ()


# ------------------------------------------------------ decision: policy


@pytest.fixture
def stub_signal(monkeypatch) -> dict:
    """Replace the signal builder with a controllable result."""
    state: dict = {"signal": SemanticSignal()}

    async def _builder(*_args, **_kwargs):
        return state["signal"]

    monkeypatch.setattr(rescue, "semantic_catalog_signal", _builder)
    return state


def _candidate(job: Job, score: float, shared: int = 1) -> SemanticCandidate:
    return SemanticCandidate(
        job_id=str(job.id),
        code=job.code,
        score=score,
        shared_skills=shared,
        per_view={"requirements": score},
    )


async def test_a_semantic_clearing_candidate_maps_as_semantic(db, source, stub_signal):
    sql = await _skill(db, "sql")
    family = JobFamily(key="policy-family", label="Policy", path="policy-family")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)
    stub_signal["signal"] = SemanticSignal(
        candidates=(_candidate(job, 0.72),),
        threshold=SEMANTIC_MAP_THRESHOLD,
        space_key="space-key",
    )

    posting = await _posting(db, source, "rescue-map", ["sql"])

    assert posting.mapping_method == "semantic"
    assert posting.status == "mapped"
    assert posting.catalog_job_id == job.id
    assert posting.mapping_confidence == pytest.approx(0.72)
    assert f"above {SEMANTIC_MAP_THRESHOLD}" in posting.mapping_reason
    signals = posting.posting_facts["mapping_signals"]
    assert signals["semantic"]["top"] == pytest.approx(0.72)
    assert signals["semantic"]["threshold"] == SEMANTIC_MAP_THRESHOLD
    assert signals["semantic"]["space_key"] == "space-key"
    assert signals["semantic"]["candidates"][0]["code"] == "weak-overlap-role"
    assert signals["overlap"]["score"] < AUTO_MAP_THRESHOLD


async def test_the_threshold_is_the_boundary(db, source, stub_signal):
    sql = await _skill(db, "sql")
    family = JobFamily(key="boundary-family", label="Boundary", path="boundary-family")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)
    stub_signal["signal"] = SemanticSignal(
        candidates=(_candidate(job, SEMANTIC_MAP_THRESHOLD - 0.001),),
        threshold=SEMANTIC_MAP_THRESHOLD,
        space_key="space-key",
    )

    posting = await _posting(db, source, "rescue-below", ["sql"])

    assert posting.mapping_method is None
    assert posting.status == "new"
    assert "semantic top" in posting.mapping_reason
    assert "— moderation" in posting.mapping_reason
    assert posting.posting_facts["mapping_signals"]["semantic"]["top"] is not None


async def test_a_zero_shared_candidate_is_never_mapped(db, source, stub_signal):
    """Defence in depth: even a signal that leaks an ungated candidate cannot
    write a map — the decision re-checks the shared-skill floor."""
    sql = await _skill(db, "sql")
    family = JobFamily(key="gate-family", label="Gate", path="gate-family")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)
    stub_signal["signal"] = SemanticSignal(
        candidates=(_candidate(job, 0.99, shared=0),),
        threshold=SEMANTIC_MAP_THRESHOLD,
        space_key="space-key",
    )

    posting = await _posting(db, source, "rescue-zero-shared", ["sql"])

    assert posting.catalog_job_id is None
    assert posting.mapping_method is None
    assert posting.status == "new"


async def test_a_degraded_signal_keeps_the_overlap_only_verdict(db, source, stub_signal):
    sql = await _skill(db, "sql")
    family = JobFamily(key="degrade-family", label="Degrade", path="degrade-family")
    db.add(family)
    await db.flush()
    await _weak_job(db, family, sql)
    stub_signal["signal"] = SemanticSignal(
        threshold=SEMANTIC_MAP_THRESHOLD, degraded="provider_unassigned"
    )

    posting = await _posting(db, source, "rescue-degraded", ["sql"])

    assert posting.mapping_method is None
    assert posting.status == "new"
    assert posting.mapping_reason == "best overlap 0.05 below 0.34 — moderation"
    semantic = posting.posting_facts["mapping_signals"]["semantic"]
    assert semantic["degraded"] == "provider_unassigned"
    assert semantic["candidates"] == []
    assert semantic["top"] is None


async def test_the_rescue_switch_is_effective_on_the_next_decision(db, source, stub_signal):
    """Off: the semantic builder is never called and the trace stays empty.
    On: the next decision runs it — no restart, no dead switch."""
    sql = await _skill(db, "sql")
    family = JobFamily(key="switch-family-rescue", label="Switch", path="switch-family-rescue")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)
    await set_switch(db, SEMANTIC_RESCUE_KEY, False)
    stub_signal["signal"] = SemanticSignal(
        candidates=(_candidate(job, 0.9),), threshold=SEMANTIC_MAP_THRESHOLD
    )

    posting = await _posting(db, source, "rescue-switch", ["sql"])
    assert posting.mapping_method is None
    assert posting.posting_facts["mapping_signals"]["semantic"]["threshold"] is None

    await set_switch(db, SEMANTIC_RESCUE_KEY, True)
    mapped = await decide_catalog(db, posting, {sql.id})

    assert mapped is not None
    assert posting.mapping_method == "semantic"
    assert posting.posting_facts["mapping_signals"]["semantic"]["threshold"] == (
        SEMANTIC_MAP_THRESHOLD
    )


async def test_a_keyword_strong_posting_never_runs_the_rescue(db, source, stub_signal):
    """Plan-185 golden case 1: overlap ≥ threshold keeps today's verdict
    bit-identical — the semantic builder is not even consulted."""
    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = JobFamily(key="golden-family-1", label="Golden1", path="golden-family-1")
    db.add(family)
    await db.flush()
    job = await _job(db, "golden-strong", family, [(sql, 7, "core"), (python, 5, "core")])
    stub_signal["signal"] = SemanticSignal(
        candidates=(_candidate(job, 0.99),), threshold=SEMANTIC_MAP_THRESHOLD
    )

    posting = await _posting(db, source, "golden-strong", ["sql", "python"])

    assert posting.mapping_method == "skill_overlap"
    assert posting.mapping_confidence == pytest.approx(1.0)
    assert posting.posting_facts["mapping_signals"]["semantic"]["threshold"] is None


async def test_both_signals_weak_stays_in_moderation(db, source, stub_signal):
    """Plan-185 golden case 2/3: weak overlap + weak semantic → moderation
    with BOTH scores in the reason and the trace."""
    sql = await _skill(db, "sql")
    family = JobFamily(key="golden-family-2", label="Golden2", path="golden-family-2")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)
    stub_signal["signal"] = SemanticSignal(
        candidates=(_candidate(job, 0.31),),
        threshold=SEMANTIC_MAP_THRESHOLD,
        space_key="space-key",
    )

    posting = await _posting(db, source, "golden-weak", ["sql"])

    assert posting.mapping_method is None
    assert posting.status == "new"
    assert "best overlap 0.05 below 0.34" in posting.mapping_reason
    assert "semantic top 0.31 below 0.6" in posting.mapping_reason
    assert posting.posting_facts["mapping_signals"]["semantic"]["candidates"]


async def test_the_rescue_costs_at_most_one_embed_batch(db, source):
    """The sanctioned ingest-time exception, measured: a weak-overlap posting
    embeds through the writer once and spends no other AI (no structured
    call), so the mapping path stays embedding-only."""
    sql = await _skill(db, "sql")
    family = JobFamily(key="ai-family", label="AI", path="ai-family")
    db.add(family)
    await db.flush()
    await _weak_job(db, family, sql)
    job = (await db.execute(select(Job).where(Job.code == "weak-overlap-role"))).scalars().one()
    # A real deployment's reconcile/backfill created the content space.
    indexed = await VectorIndexService(db).index_document(kind="job", source_id=str(job.id))
    assert indexed.degraded is None
    before = (
        (await db.execute(select(AIGeneration).where(AIGeneration.task_type == "embed")))
        .scalars()
        .all()
    )

    posting = await _posting(db, source, "rescue-ai", ["sql"])

    rows = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == "embed",
                    AIGeneration.id.not_in([row.id for row in before]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert posting.mapping_method is None
    assert len(rows) == 1, "one embed batch for the posting's changed views"
    assert (rows[0].output or {}).get("count", 0) >= 1
    assert rows[0].status == "ok"
