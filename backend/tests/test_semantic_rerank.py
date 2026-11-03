"""The bounded semantic rerank (plan 50 P2b, plan 164 S4.4).

Two layers, tested separately:

* the **policy** — ``decide_catalog`` reranks only an ambiguous deterministic
  outcome, over the stage-2 candidates, accepts only a threshold+margin
  winner, never overwrites ``manual`` and degrades to the deterministic
  verdict on any embedding/index failure;
* the **signal** — ``semantic_rerank_signal`` scores the deterministic
  candidate set with the stored-vector job↔posting match, applies the pinned
  ``0.75/0.25`` blend and records the embedding ``space_key``.

The policy tests inject a controlled signal; the integration test uses a
deterministic token embedder on the real vector store.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions.sdk import RawPosting
from app.models.enums import MappingMethod
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting
from app.models.taxonomy_model import Skill
from app.services.postings import semantic_rerank as rerank_module
from app.services.postings import semantic_rescue as rescue_module
from app.services.postings.catalog_settings import (
    SEMANTIC_RERANK_KEY,
    SEMANTIC_RESCUE_KEY,
    set_switch,
)
from app.services.postings.mapping_candidates import (
    CatalogCandidate,
    catalog_candidates,
)
from app.services.postings.mapping_features import (
    MAX_FEATURE_CANDIDATES,
    MAX_SHARED_SKILLS,
    build_mapping_features,
)
from app.services.postings.postings_service import (
    AUTO_MAP_THRESHOLD,
    MAPPING_VERSION,
    decide_catalog,
    upsert_posting,
)
from app.services.postings.semantic_rerank import (
    RERANK_CANDIDATE_K,
    RERANK_MARGIN,
    RerankCandidate,
    RerankSignal,
    semantic_rerank_signal,
)
from app.services.vector_index_service import VectorIndexService

DIM = 64


# ------------------------------------------------------------------ world


def _token_vector(text: str) -> list[float]:
    vector = [0.0] * DIM
    for token in str(text).lower().replace("-", " ").split():
        vector[sum(ord(char) for char in token) % DIM] += 1.0
    norm = sum(value * value for value in vector) ** 0.5 or 1.0
    return [value / norm for value in vector]


class TokenEmbedder:
    async def __call__(self, texts):
        return [_token_vector(text) for text in texts]


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
    db,
    source,
    external_id: str,
    skills: list[str],
    *,
    title: str = "",
    description: str = "",
    rerank: bool = True,
) -> JobPosting:
    await set_switch(db, SEMANTIC_RERANK_KEY, rerank)
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


async def _weak_job(db, family: JobFamily, sql: Skill) -> Job:
    filler_a = await _skill(db, "rerank-filler-a")
    filler_b = await _skill(db, "rerank-filler-b")
    return await _job(
        db,
        "weak-overlap-role",
        family,
        [(sql, 1, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
    )


def _candidate(job: Job, score: float = 0.5) -> RerankCandidate:
    return RerankCandidate(
        job_id=str(job.id),
        code=job.code,
        deterministic=0.05,
        semantic=0.9,
        blend=score,
        shared_skill_ids=(),
        per_view={"summary": 0.9},
    )


@pytest.fixture
def stub_rerank(monkeypatch) -> dict:
    """Replace the rerank signal with a controllable result and count calls."""
    state: dict = {"signal": RerankSignal(), "calls": 0}

    async def _builder(*_args, **_kwargs):
        state["calls"] += 1
        return state["signal"]

    async def _no_rescue(*_args, **_kwargs):
        return rescue_module.not_run_signal()

    monkeypatch.setattr(rerank_module, "semantic_rerank_signal", _builder)
    monkeypatch.setattr(rescue_module, "semantic_catalog_signal", _no_rescue)
    return state


# ----------------------------------------------------------- policy


async def test_a_cleared_unambiguous_overlap_never_reranks(db, source, stub_rerank):
    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = JobFamily(key="rerank-clear", label="Clear", path="rerank-clear")
    db.add(family)
    await db.flush()
    job = await _job(db, "clear-role", family, [(sql, 8, "core"), (python, 6, "core")])

    posting = await _posting(db, source, "rerank-clear", ["sql", "python"])

    assert posting.mapping_method == "skill_overlap"
    assert posting.catalog_job_id == job.id
    assert stub_rerank["calls"] == 0
    assert posting.posting_facts["mapping_signals"]["rerank"]["ran"] is False


async def test_an_ambiguous_overlap_reranks_and_maps_semantic_rerank(db, source, stub_rerank):
    sql = await _skill(db, "sql")
    family = JobFamily(key="rerank-accept", label="Accept", path="rerank-accept")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)
    stub_rerank["signal"] = RerankSignal(
        candidates=(_candidate(job, 0.52),),
        threshold=AUTO_MAP_THRESHOLD,
        margin=RERANK_MARGIN,
        space_key="space-key",
        ran=True,
        accepted=True,
        top_changed=True,
    )

    posting = await _posting(db, source, "rerank-accept", ["sql"])

    assert stub_rerank["calls"] == 1
    assert posting.mapping_method == MappingMethod.SEMANTIC_RERANK.value
    assert posting.status == "mapped"
    assert posting.catalog_job_id == job.id
    assert posting.mapping_confidence == pytest.approx(0.52)
    assert "semantic rerank 0.52" in posting.mapping_reason
    assert posting.mapping_version == MAPPING_VERSION
    features = posting.mapping_features
    assert features["schema_version"] == 1
    assert features["space_key"] == "space-key"
    assert features["policy"]["tau_job"] == AUTO_MAP_THRESHOLD
    assert features["policy"]["delta"] == RERANK_MARGIN
    assert features["policy"]["k"] == RERANK_CANDIDATE_K
    assert features["candidates"][0]["job_code"] == "weak-overlap-role"
    assert features["candidates"][0]["blend"] == pytest.approx(0.52)


async def test_a_cleared_but_narrow_overlap_can_change_top_1(db, source, stub_rerank):
    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = JobFamily(key="rerank-margin", label="Margin", path="rerank-margin")
    db.add(family)
    await db.flush()
    first = await _job(db, "margin-a", family, [(sql, 10, "core"), (python, 10, "core")])
    second = await _job(db, "margin-b", family, [(sql, 10, "core"), (python, 10, "core")])
    stub_rerank["signal"] = RerankSignal(
        candidates=(_candidate(second, 0.55), _candidate(first, 0.45)),
        threshold=AUTO_MAP_THRESHOLD,
        margin=RERANK_MARGIN,
        space_key="space-key",
        ran=True,
        accepted=True,
        top_changed=True,
    )

    posting = await _posting(db, source, "rerank-margin", ["sql", "python"])

    assert posting.mapping_method == MappingMethod.SEMANTIC_RERANK.value
    assert posting.catalog_job_id == second.id
    assert stub_rerank["calls"] == 1, "the narrow deterministic margin is ambiguous"


async def test_a_rejected_rerank_keeps_the_cleared_deterministic_verdict(db, source, stub_rerank):
    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = JobFamily(key="rerank-reject-margin", label="Reject", path="rerank-reject-margin")
    db.add(family)
    await db.flush()
    job = await _job(db, "reject-margin-role", family, [(sql, 10, "core"), (python, 10, "core")])
    stub_rerank["signal"] = RerankSignal(
        candidates=(_candidate(job, 0.40),),
        threshold=AUTO_MAP_THRESHOLD,
        margin=RERANK_MARGIN,
        ran=True,
        accepted=False,
    )

    posting = await _posting(db, source, "rerank-reject-margin", ["sql", "python"])

    assert posting.mapping_method == "skill_overlap"
    assert posting.catalog_job_id == job.id
    assert posting.posting_facts["mapping_signals"]["rerank"]["accepted"] is False


async def test_a_rejected_below_threshold_rerank_stays_in_moderation(db, source, stub_rerank):
    sql = await _skill(db, "sql")
    family = JobFamily(
        key="rerank-reject-threshold", label="RejectT", path="rerank-reject-threshold"
    )
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)
    stub_rerank["signal"] = RerankSignal(
        candidates=(_candidate(job, 0.30),),
        threshold=AUTO_MAP_THRESHOLD,
        margin=RERANK_MARGIN,
        ran=True,
        accepted=False,
    )

    posting = await _posting(db, source, "rerank-reject-threshold", ["sql"])

    assert posting.mapping_method is None
    assert posting.status == "new"
    assert posting.catalog_job_id is None


async def test_no_shared_skill_never_builds_a_candidate_set(db, source, stub_rerank):
    family = JobFamily(key="rerank-none", label="None", path="rerank-none")
    db.add(family)
    await db.flush()
    python = await _skill(db, "python")
    await _job(db, "unrelated-role", family, [(python, 10, "core")])

    posting = await _posting(db, source, "rerank-none", ["unmatched-skill"])

    assert posting.mapping_method is None
    assert stub_rerank["calls"] == 0, "no deterministic candidate ⇒ no rerank"
    assert posting.mapping_features["candidates"] == []
    assert posting.mapping_features["degraded"] is None


async def test_manual_is_never_overwritten_by_the_rerank(db, source, stub_rerank):
    sql = await _skill(db, "sql")
    family = JobFamily(key="rerank-manual", label="Manual", path="rerank-manual")
    db.add(family)
    await db.flush()
    job = await _job(db, "manual-rerank-role", family, [(sql, 8, "core")])
    posting = await _posting(db, source, "rerank-manual", ["sql"])
    posting.catalog_job_id = job.id
    posting.mapping_method = MappingMethod.MANUAL.value
    posting.mapping_confidence = 1.0
    posting.mapping_reason = "manually mapped"
    posting.status = "mapped"
    await db.flush()

    assert await decide_catalog(db, posting, {sql.id}) is None

    assert posting.mapping_method == MappingMethod.MANUAL.value
    assert posting.catalog_job_id == job.id
    assert posting.mapping_reason == "manually mapped"
    assert stub_rerank["calls"] == 0


async def test_the_rerank_switch_defaults_off_and_applies_to_the_next_decision(
    db, source, stub_rerank
):
    """The kill switch is OFF for an unconfigured deployment: the ambiguous
    posting keeps the pre-rerank deterministic verdict (abstain here), no
    rerank call and no rerank candidates. Flipping it is effective on the
    very next decision, with no restart."""
    sql = await _skill(db, "rerank-switch-sql")
    family = JobFamily(key="rerank-switch", label="Switch", path="rerank-switch")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)

    posting = await _posting(db, source, "rerank-switch-off", ["rerank-switch-sql"], rerank=False)

    assert stub_rerank["calls"] == 0, "rerank off ⇒ no rerank call"
    assert posting.mapping_method is None
    assert posting.catalog_job_id is None
    assert posting.posting_facts["mapping_signals"]["rerank"]["ran"] is False
    assert posting.posting_facts["mapping_signals"]["rerank"]["candidates"] == []
    assert posting.mapping_features["candidates"][0]["semantic"] is None

    stub_rerank["signal"] = RerankSignal(
        candidates=(_candidate(job, 0.52),),
        threshold=AUTO_MAP_THRESHOLD,
        margin=RERANK_MARGIN,
        space_key="space-key",
        ran=True,
        accepted=True,
        top_changed=True,
    )
    await set_switch(db, SEMANTIC_RERANK_KEY, True)
    await decide_catalog(db, posting, {sql.id})

    assert stub_rerank["calls"] == 1
    assert posting.mapping_method == MappingMethod.SEMANTIC_RERANK.value
    assert posting.catalog_job_id == job.id


async def test_the_rerank_and_rescue_switches_are_independent(db, source, monkeypatch):
    """Rescue off never disables the rerank, and rerank off never disables
    the rescue: each stage has its own per-decision switch."""
    from app.services.postings.semantic_rescue import SemanticCandidate, SemanticSignal

    sql = await _skill(db, "rerank-independence-sql")
    family = JobFamily(key="rerank-independence", label="Independent", path="rerank-independence")
    db.add(family)
    await db.flush()
    job = await _weak_job(db, family, sql)

    state = {"rerank": 0, "rescue": 0}

    async def _rerank(*_args, **_kwargs):
        state["rerank"] += 1
        return RerankSignal(
            candidates=(_candidate(job, 0.52),),
            threshold=AUTO_MAP_THRESHOLD,
            margin=RERANK_MARGIN,
            ran=True,
            accepted=True,
            top_changed=True,
        )

    async def _rescue(*_args, **_kwargs):
        state["rescue"] += 1
        return SemanticSignal(
            candidates=(
                SemanticCandidate(
                    job_id=str(job.id),
                    code=job.code,
                    score=0.90,
                    shared_skills=1,
                ),
            ),
            threshold=0.6,
        )

    monkeypatch.setattr(rerank_module, "semantic_rerank_signal", _rerank)
    monkeypatch.setattr(rescue_module, "semantic_catalog_signal", _rescue)

    # Rerank ON, rescue OFF ⇒ only the rerank runs.
    await set_switch(db, SEMANTIC_RERANK_KEY, True)
    await set_switch(db, SEMANTIC_RESCUE_KEY, False)
    posting = await _posting(db, source, "rerank-independent-on", ["rerank-independence-sql"])
    assert state == {"rerank": 1, "rescue": 0}
    assert posting.mapping_method == MappingMethod.SEMANTIC_RERANK.value

    # Rerank OFF, rescue ON ⇒ only the rescue runs.
    await set_switch(db, SEMANTIC_RERANK_KEY, False)
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)
    posting = await _posting(
        db, source, "rerank-independent-off", ["rerank-independence-sql"], rerank=False
    )
    assert state == {"rerank": 1, "rescue": 1}
    assert posting.mapping_method == MappingMethod.SEMANTIC.value
    assert posting.posting_facts["mapping_signals"]["rerank"]["ran"] is False


async def test_manual_rows_are_untouched_in_both_switch_states(db, source, stub_rerank):
    sql = await _skill(db, "rerank-manual-switch-sql")
    family = JobFamily(key="rerank-manual-switch", label="ManualS", path="rerank-manual-switch")
    db.add(family)
    await db.flush()
    job = await _job(db, "manual-switch-role", family, [(sql, 8, "core")])
    posting = await _posting(db, source, "rerank-manual-switch", ["rerank-manual-switch-sql"])
    posting.catalog_job_id = job.id
    posting.mapping_method = MappingMethod.MANUAL.value
    posting.mapping_confidence = 1.0
    posting.mapping_reason = "manually mapped"
    posting.status = "mapped"
    await db.flush()

    for enabled in (False, True):
        await set_switch(db, SEMANTIC_RERANK_KEY, enabled)
        assert await decide_catalog(db, posting, {sql.id}) is None
        assert posting.mapping_method == MappingMethod.MANUAL.value
        assert posting.catalog_job_id == job.id
        assert posting.mapping_reason == "manually mapped"

    assert stub_rerank["calls"] == 0


async def test_a_missing_index_degrades_to_the_deterministic_verdict(db, source):
    """No content space: the rerank reports ``index_missing`` and the posting
    keeps the deterministic verdict — no request-time provisioning."""
    sql = await _skill(db, "sql")
    family = JobFamily(key="rerank-degrade", label="Degrade", path="rerank-degrade")
    db.add(family)
    await db.flush()
    await _weak_job(db, family, sql)

    posting = await _posting(db, source, "rerank-degrade", ["sql"])

    assert posting.mapping_method is None
    assert posting.status == "new"
    rerank = posting.posting_facts["mapping_signals"]["rerank"]
    assert rerank["ran"] is True
    assert rerank["degraded"] == "index_missing"
    assert rerank["accepted"] is False
    assert posting.mapping_features["degraded"] == "index_missing"


async def test_a_draft_candidate_can_never_win_the_rerank(db, source, monkeypatch):
    """The deterministic list may contain drafts; the rerank filters them."""
    import uuid as uuid_module
    from types import SimpleNamespace

    async def indexed(_db, _posting, *, indexer=None):
        return None

    monkeypatch.setattr(rescue_module, "_ensure_posting_indexed", indexed)
    posting = await _posting(db, source, "rerank-draft-gate", ["python"])
    draft_id = uuid_module.uuid4()
    published_id = uuid_module.uuid4()
    draft = CatalogCandidate(
        job=SimpleNamespace(id=draft_id, code="draft-role", status="draft"),
        score=0.90,
        shared_skill_ids=(uuid_module.uuid4(),),
    )
    published = CatalogCandidate(
        job=SimpleNamespace(id=published_id, code="published-role", status="published"),
        score=0.30,
        shared_skill_ids=(uuid_module.uuid4(),),
    )

    class Retriever:
        async def match_documents(self, **_kwargs):
            return SimpleNamespace(
                hits=(
                    SimpleNamespace(
                        source_id=str(draft_id), score=0.99, per_view={"summary": 0.99}
                    ),
                    SimpleNamespace(
                        source_id=str(published_id), score=0.55, per_view={"summary": 0.55}
                    ),
                ),
                space_key="space-key",
                degraded=None,
            )

    signal = await semantic_rerank_signal(
        db, posting, [draft, published], threshold=AUTO_MAP_THRESHOLD, retriever=Retriever()
    )

    assert [candidate.code for candidate in signal.candidates] == ["published-role"]
    assert signal.accepted is True


async def test_the_candidate_set_is_bounded_and_published_only(db):
    sql = await _skill(db, "sql")
    family = JobFamily(key="rerank-candidates", label="Candidates", path="rerank-candidates")
    db.add(family)
    await db.flush()
    published = []
    for index in range(30):
        job = await _job(
            db,
            f"candidate-{index:02d}",
            family,
            [(sql, 10, "core")],
            status="published" if index < 28 else "draft",
        )
        published.append(job)

    all_candidates = await catalog_candidates(db, {sql.id}, k=100)
    assert len(all_candidates) == 30
    bounded = await catalog_candidates(db, {sql.id}, k=RERANK_CANDIDATE_K)
    assert len(bounded) == RERANK_CANDIDATE_K
    published_only = await catalog_candidates(db, {sql.id}, k=100, published_only=True)
    assert len(published_only) == 28
    assert all(candidate.job.status == "published" for candidate in published_only)
    assert [candidate.code for candidate in published_only] == sorted(
        candidate.code for candidate in published_only
    ), "equal scores break on job.code"


async def test_mapping_features_are_bounded(db):
    sql = await _skill(db, "sql")
    family = JobFamily(key="rerank-features", label="Features", path="rerank-features")
    db.add(family)
    await db.flush()
    job = await _job(db, "features-role", family, [(sql, 10, "core")])
    for index in range(30):
        await _skill(db, f"shared-{index:02d}")
    shared_ids = tuple(
        skill.id
        for skill in (await db.execute(select(Skill).where(Skill.key.like("shared-%"))))
        .scalars()
        .all()
    )
    candidates = [
        CatalogCandidate(job=job, score=1.0 - index * 0.01, shared_skill_ids=shared_ids)
        for index in range(8)
    ]

    features = await build_mapping_features(
        db,
        candidates=candidates,
        rerank=None,
        mapping_version=MAPPING_VERSION,
        tau_job=AUTO_MAP_THRESHOLD,
        delta=RERANK_MARGIN,
        k=RERANK_CANDIDATE_K,
        blend_deterministic=0.75,
        blend_semantic=0.25,
        semantic_threshold=0.6,
        semantic_min_shared_skills=1,
    )

    assert len(features["candidates"]) == MAX_FEATURE_CANDIDATES
    assert all(len(row["shared_skills"]) <= MAX_SHARED_SKILLS for row in features["candidates"])
    assert all(
        row["deterministic"] == round(row["deterministic"], 4) for row in features["candidates"]
    )


# ------------------------------------------------------- real signal


async def test_the_real_match_records_the_space_key_and_per_view_scores(db, source, monkeypatch):
    """The integration path: a real vector space, a real MaxSim match and the
    recorded ``space_key``. The token embedder makes the semantic score
    deterministic without a provider call."""
    from app.services import vector_index_service

    monkeypatch.setattr(
        vector_index_service,
        "gateway_embedder",
        lambda _db, user_id=None, run=None: TokenEmbedder(),
    )
    sql = await _skill(db, "python")
    family = JobFamily(key="rerank-real", label="Real", path="rerank-real")
    db.add(family)
    await db.flush()
    filler_a = await _skill(db, "real-filler-a")
    filler_b = await _skill(db, "real-filler-b")
    job = await _job(
        db,
        "quantum-pipeline-engineer",
        family,
        [(sql, 10, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
        title="Quantum Pipeline Engineer",
        description="Builds quantum pipelines for the fleet.",
    )
    await VectorIndexService(db).index_document(kind="job", source_id=str(job.id))

    posting = await _posting(
        db,
        source,
        "rerank-real",
        ["python"],
        title="Quantum Pipeline Engineer",
        description="Builds quantum pipelines for the fleet.",
    )

    rerank = posting.posting_facts["mapping_signals"]["rerank"]
    assert rerank["ran"] is True
    assert rerank["degraded"] is None
    assert rerank["space_key"]
    assert rerank["candidates"], "the deterministic candidate is scored"
    assert rerank["candidates"][0]["semantic"] > 0
    assert rerank["candidates"][0]["per_view"], "per-view scores ride the trace"
    assert posting.mapping_features["space_key"] == rerank["space_key"]
    assert posting.mapping_method == MappingMethod.SEMANTIC_RERANK.value
    assert posting.catalog_job_id == job.id
