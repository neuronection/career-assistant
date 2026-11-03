"""P2c.3 — the posting semantic stages move off the request path.

The request seam (``map_posting`` / the extract post-processing / the admin
remap) calls ``decide_catalog(defer_semantic=True)``: it computes the
deterministic verdict exactly as the switch-off path, records
``posting_facts["mapping_signals"]["semantic_pending"]`` and queues ONE
single-posting ``POSTING_REMAP`` job **in the caller's transaction**. The
worker re-decides that posting with ``defer_semantic=False`` and overwrites
``mapping_signals`` with the final trace — no second job, no loop.

Local benchmark (serial, PostgreSQL 16.15 dev-db on loopback, Python
3.12.12, Linux 6.17 x86_64, ``N = 40`` decisions after 3 warm-ups, measured
by ``test_the_request_path_latency_and_call_counts``):

* switches off (rerank off, rescue off): p50 = 2.21 ms, p95 = 2.46 ms,
  0 index / 0 match calls, 0 jobs.
* switches on/needed (rerank on, rescue on): p50 = 2.66 ms, p95 = 3.56 ms,
  0 index / 0 match calls in the request path, exactly 1 deduped job.

These are local deterministic timings over a tiny fixture, not production
provider latency; the real network/embedding cost lives in the worker.
The worker side is measured by its call counters: one rescue pass spends
exactly 1 index + 1 match, applies the forged hit as ``semantic`` and a repeat
decision is idempotent (the same fields, 1 index + 1 match, no new job).
Real-embedding calibration: NOT RUN — this environment has the mock provider
only, so no provider-latency number is claimed.
"""

from __future__ import annotations

import statistics
import time
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine
from app.extensions.sdk import RawPosting
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobType, MappingMethod
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting
from app.models.taxonomy_model import Skill
from app.services.job_worker import enqueue
from app.services.postings import semantic_rerank as rerank_module
from app.services.postings import semantic_rescue as rescue_module
from app.services.postings.catalog_settings import (
    SEMANTIC_RERANK_KEY,
    SEMANTIC_RESCUE_KEY,
    set_switch,
)
from app.services.postings.mapping_remap import (
    SEMANTIC_POSTING_KEY,
    enqueue_semantic_redecision,
    run_posting_remap,
)
from app.services.postings.postings_service import (
    decide_catalog,
    upsert_posting,
)
from app.services.postings.semantic_rerank import RerankSignal
from app.services.postings.semantic_rescue import SemanticSignal
from app.services.vector_retrieval_service import VectorRetrievalService

#: This module's request-path decisions; keep the benchmark CI-sized.
BENCHMARK_DECISIONS = 40


# ------------------------------------------------------------------ world


async def _skill(db, key: str) -> Skill:
    existing = (await db.execute(select(Skill).where(Skill.key == key))).scalars().first()
    if existing is not None:
        return existing
    row = Skill(key=key, label=key.upper(), category="test")
    db.add(row)
    await db.flush()
    return row


async def _job(db, family: JobFamily, links: list[tuple[Skill, int, str]]) -> Job:
    job = Job(
        code="weak-overlap-role",
        title="Weak Overlap Role",
        family_id=family.id,
        status="published",
    )
    db.add(job)
    await db.flush()
    for skill, level, importance in links:
        db.add(
            JobSkill(job_id=job.id, skill_id=skill.id, required_level=level, importance=importance)
        )
    await db.flush()
    return job


async def _world(db) -> tuple[Skill, JobFamily, Job]:
    sql = await _skill(db, "sql")
    filler_a = await _skill(db, "deferral-filler-a")
    filler_b = await _skill(db, "deferral-filler-b")
    family = JobFamily(key="deferral-family", label="Deferral", path="deferral-family")
    db.add(family)
    await db.flush()
    job = await _job(
        db,
        family,
        [(sql, 1, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
    )
    return sql, family, job


async def _posting(db, source, external_id: str, skills: list[str]) -> JobPosting:
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
    assert posting is not None
    await db.flush()
    return posting


async def _semantic_jobs(db) -> list[BackgroundJob]:
    rows = await db.execute(
        select(BackgroundJob).where(
            BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value,
            BackgroundJob.payload[SEMANTIC_POSTING_KEY].as_string().is_not(None),
        )
    )
    return list(rows.scalars().all())


async def _posting_skills(db, posting: JobPosting) -> set[uuid.UUID]:
    from app.models.posting_model import PostingSkill

    rows = await db.execute(
        select(PostingSkill.skill_id).where(PostingSkill.posting_id == posting.id)
    )
    return set(rows.scalars().all())


@pytest.fixture
def vector_guard(monkeypatch) -> dict:
    """The vector layer must never be reached from the request path."""
    calls = {"index": 0, "match": 0}

    async def _index(*_args, **_kwargs):
        calls["index"] += 1
        raise AssertionError("request path must not index a posting")

    async def _match(*_args, **_kwargs):
        calls["match"] += 1
        raise AssertionError("request path must not run a document match")

    monkeypatch.setattr(rescue_module, "_ensure_posting_indexed", _index)
    monkeypatch.setattr(VectorRetrievalService, "match_documents", _match)
    return calls


@pytest.fixture
def counting_vector(monkeypatch) -> dict:
    """Count the worker's index/match calls and return one job hit.

    The hit is enough for the rescue and the rerank to score the weak
    deterministic candidate without a real space or embedding provider.
    """
    calls = {"index": 0, "match": 0, "job_id": None}

    async def _index(_db, _posting, *, indexer=None):
        calls["index"] += 1
        return None

    async def _match(_self, **_kwargs):
        calls["match"] += 1
        return SimpleNamespace(
            hits=(
                SimpleNamespace(
                    source_id=str(calls["job_id"]),
                    score=0.95,
                    per_view={"requirements": 0.95},
                ),
            ),
            space_key="deferral-space",
            degraded=None,
        )

    monkeypatch.setattr(rescue_module, "_ensure_posting_indexed", _index)
    monkeypatch.setattr(VectorRetrievalService, "match_documents", _match)
    return calls


# ------------------------------------------------- request-path deferral


async def test_the_request_path_defers_and_never_touches_the_vector_layer(db, source, vector_guard):
    sql, _family, _job_row = await _world(db)
    await set_switch(db, SEMANTIC_RERANK_KEY, True)
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)

    posting = await _posting(db, source, "defer-request", ["sql"])

    signals = posting.posting_facts["mapping_signals"]
    assert signals["semantic_pending"] is True
    assert "ambiguous deterministic outcome" in signals["semantic_pending_reason"]
    assert "overlap below threshold" in signals["semantic_pending_reason"]
    assert signals["semantic"]["threshold"] is None
    assert signals["rerank"]["ran"] is False
    assert signals["rerank"]["candidates"] == []
    assert posting.mapping_method is None
    assert posting.status == "new"
    assert vector_guard == {"index": 0, "match": 0}

    [job] = await _semantic_jobs(db)
    assert job.status == "queued"
    assert job.payload["posting_id"] == str(posting.id)
    assert job.payload["auto_continue"] is False
    assert job.payload["continuation_key"] == f"posting|{posting.id}"
    assert sql.id in await _posting_skills(db, posting)

    await set_switch(db, SEMANTIC_RERANK_KEY, False)
    await set_switch(db, SEMANTIC_RESCUE_KEY, False)
    baseline = await _posting(db, source, "defer-request-baseline", ["sql"])
    for field in (
        "mapping_method",
        "catalog_job_id",
        "mapping_confidence",
        "mapping_reason",
        "mapping_version",
        "status",
    ):
        assert getattr(posting, field) == getattr(baseline, field)
    assert posting.mapping_features == baseline.mapping_features
    assert "semantic_pending" not in baseline.posting_facts["mapping_signals"]


async def test_the_switch_off_path_is_zero_cost_and_bit_identical(db, source, vector_guard):
    _sql, _family, _job_row = await _world(db)
    await set_switch(db, SEMANTIC_RERANK_KEY, False)
    await set_switch(db, SEMANTIC_RESCUE_KEY, False)

    deferred = await _posting(db, source, "defer-off", ["sql"])

    assert vector_guard == {"index": 0, "match": 0}
    assert await _semantic_jobs(db) == []
    signals = deferred.posting_facts["mapping_signals"]
    assert "semantic_pending" not in signals
    assert signals["semantic"]["threshold"] is None
    assert signals["rerank"]["ran"] is False

    immediate = await _posting(db, source, "defer-off-direct", ["sql"])
    await decide_catalog(
        db,
        immediate,
        await _posting_skills(db, immediate),
        defer_semantic=False,
    )

    assert vector_guard == {"index": 0, "match": 0}
    for field in (
        "mapping_method",
        "catalog_job_id",
        "mapping_confidence",
        "mapping_reason",
        "mapping_version",
        "status",
    ):
        assert getattr(deferred, field) == getattr(immediate, field)
    assert deferred.mapping_features == immediate.mapping_features


async def test_rescue_on_rerank_off_queues_only_the_rescue(db, source, vector_guard, monkeypatch):
    sql, _family, job = await _world(db)
    await set_switch(db, SEMANTIC_RERANK_KEY, False)
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)

    posting = await _posting(db, source, "defer-rescue-only", ["sql"])

    signals = posting.posting_facts["mapping_signals"]
    assert signals["semantic_pending"] is True
    assert signals["semantic_pending_reason"] == "overlap below threshold"
    assert vector_guard == {"index": 0, "match": 0}
    assert len(await _semantic_jobs(db)) == 1

    async def _no_rerank(*_args, **_kwargs):
        raise AssertionError("rerank is off and must not run")

    async def _rescue(*_args, **_kwargs):
        from app.services.postings.semantic_rescue import SemanticCandidate

        return SemanticSignal(
            candidates=(
                SemanticCandidate(job_id=str(job.id), code=job.code, score=0.75, shared_skills=1),
            ),
            threshold=0.6,
            space_key="deferral-space",
        )

    import app.services.postings.semantic_rescue as rescue

    monkeypatch.setattr(rerank_module, "semantic_rerank_signal", _no_rerank)
    monkeypatch.setattr(rescue, "semantic_catalog_signal", _rescue)
    result = await run_posting_remap(db, {"posting_id": str(posting.id), "auto_continue": False})

    assert result["remapped"] == 1
    assert posting.mapping_method == MappingMethod.SEMANTIC.value
    assert posting.catalog_job_id == job.id
    final = posting.posting_facts["mapping_signals"]
    assert "semantic_pending" not in final
    assert final["semantic"]["top"] == pytest.approx(0.75)
    assert sql.id in await _posting_skills(db, posting)


async def test_the_admin_remap_endpoint_defers_the_semantic_pass(
    db, client, auth_headers, source, vector_guard
):
    _sql, _family, _job_row = await _world(db)
    await set_switch(db, SEMANTIC_RERANK_KEY, False)
    await set_switch(db, SEMANTIC_RESCUE_KEY, False)
    posting = await _posting(db, source, "defer-admin-remap", ["sql"])
    assert await _semantic_jobs(db) == []

    await set_switch(db, SEMANTIC_RERANK_KEY, True)
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)

    response = await client.post(f"/api/v1/admin/postings/{posting.id}/remap", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mapping_method"] is None
    assert body["semantic_pending"] is True
    assert body["semantic_pending_reason"]
    assert vector_guard == {"index": 0, "match": 0}
    [job] = await _semantic_jobs(db)
    assert job.payload["posting_id"] == str(posting.id)
    await db.refresh(posting)
    assert posting.posting_facts["mapping_signals"]["semantic_pending"] is True


async def test_rerank_on_rescue_off_queues_only_the_rerank(db, source, vector_guard, monkeypatch):
    sql, _family, job = await _world(db)
    await set_switch(db, SEMANTIC_RERANK_KEY, True)
    await set_switch(db, SEMANTIC_RESCUE_KEY, False)

    posting = await _posting(db, source, "defer-rerank-only", ["sql"])

    signals = posting.posting_facts["mapping_signals"]
    assert signals["semantic_pending"] is True
    assert signals["semantic_pending_reason"] == "ambiguous deterministic outcome"
    assert vector_guard == {"index": 0, "match": 0}
    assert len(await _semantic_jobs(db)) == 1

    async def _rerank(_db, _posting, candidates, *, threshold, margin, **_kwargs):
        top = candidates[0]
        return RerankSignal(
            candidates=(
                rerank_module.RerankCandidate(
                    job_id=top.job_id,
                    code=top.code,
                    deterministic=top.score,
                    semantic=1.0,
                    blend=0.52,
                    shared_skill_ids=top.shared_skill_ids,
                ),
            ),
            threshold=threshold,
            margin=margin,
            space_key="deferral-space",
            ran=True,
            accepted=True,
            top_changed=False,
        )

    async def _no_rescue(*_args, **_kwargs):
        raise AssertionError("rescue is off and must not run")

    monkeypatch.setattr(rerank_module, "semantic_rerank_signal", _rerank)
    monkeypatch.setattr(rescue_module, "semantic_catalog_signal", _no_rescue)
    result = await run_posting_remap(db, {"posting_id": str(posting.id), "auto_continue": False})

    assert result["remapped"] == 1
    assert posting.mapping_method == MappingMethod.SEMANTIC_RERANK.value
    assert posting.catalog_job_id == job.id
    final = posting.posting_facts["mapping_signals"]
    assert "semantic_pending" not in final
    assert final["rerank"]["accepted"] is True
    assert sql.id in await _posting_skills(db, posting)


async def test_the_worker_applies_the_rescue_once_and_is_idempotent(db, source, counting_vector):
    _sql, _family, job = await _world(db)
    counting_vector["job_id"] = job.id
    await set_switch(db, SEMANTIC_RERANK_KEY, False)
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)

    posting = await _posting(db, source, "defer-idempotent", ["sql"])
    assert len(await _semantic_jobs(db)) == 1

    first = await run_posting_remap(db, {"posting_id": str(posting.id), "auto_continue": False})
    first_decision = (
        posting.mapping_method,
        posting.catalog_job_id,
        posting.mapping_confidence,
        posting.mapping_reason,
        posting.mapping_features["space_key"],
    )
    assert first["remapped"] == 1
    assert counting_vector["index"] == 1
    assert counting_vector["match"] == 1
    assert posting.mapping_method == MappingMethod.SEMANTIC.value
    assert posting.catalog_job_id == job.id
    assert posting.posting_facts["mapping_signals"]["semantic"]["top"] == pytest.approx(0.95)

    second = await run_posting_remap(db, {"posting_id": str(posting.id), "auto_continue": False})
    second_decision = (
        posting.mapping_method,
        posting.catalog_job_id,
        posting.mapping_confidence,
        posting.mapping_reason,
        posting.mapping_features["space_key"],
    )

    assert second["remapped"] == 1
    assert second_decision == first_decision
    assert counting_vector["index"] == 2, "one index attempt per deferred pass"
    assert counting_vector["match"] == 2, "one match per deferred pass"
    assert len(await _semantic_jobs(db)) == 1, "the worker never queues another pass"


async def test_a_manual_mapping_is_never_queued_or_changed(db, source, vector_guard):
    _sql, _family, job = await _world(db)
    await set_switch(db, SEMANTIC_RERANK_KEY, True)
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)
    posting = await _posting(db, source, "defer-manual", ["sql"])
    posting.catalog_job_id = job.id
    posting.mapping_method = MappingMethod.MANUAL.value
    posting.mapping_confidence = 1.0
    posting.mapping_reason = "manually mapped"
    posting.status = "mapped"
    await db.flush()
    before = (posting.mapping_method, posting.catalog_job_id, posting.mapping_reason)
    jobs_before = len(await _semantic_jobs(db))

    assert await decide_catalog(db, posting, {_sql.id}, defer_semantic=True) is None
    assert (await run_posting_remap(db, {"posting_id": str(posting.id), "auto_continue": False}))[
        "skipped"
    ] == 1

    assert (posting.mapping_method, posting.catalog_job_id, posting.mapping_reason) == before
    assert len(await _semantic_jobs(db)) == jobs_before
    assert vector_guard == {"index": 0, "match": 0}


async def test_a_terminal_posting_is_never_queued_or_changed(db, source, vector_guard):
    _sql, _family, _job_row = await _world(db)
    await set_switch(db, SEMANTIC_RERANK_KEY, True)
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)

    for index, status in enumerate(("expired", "hidden")):
        posting = await _posting(db, source, f"defer-terminal-{index}", ["sql"])
        posting.status = status
        await db.flush()
        before = (
            posting.mapping_method,
            posting.catalog_job_id,
            posting.mapping_reason,
            posting.status,
        )
        jobs_before = len(await _semantic_jobs(db))

        assert await decide_catalog(db, posting, {_sql.id}, defer_semantic=True) is None
        result = await run_posting_remap(
            db, {"posting_id": str(posting.id), "auto_continue": False}
        )

        assert result["skipped"] == 1
        assert (
            posting.mapping_method,
            posting.catalog_job_id,
            posting.mapping_reason,
            posting.status,
        ) == before
        assert len(await _semantic_jobs(db)) == jobs_before

    assert vector_guard == {"index": 0, "match": 0}


# --------------------------------------------------------------- lifecycle


async def test_repeated_decisions_keep_exactly_one_queued_job(db, source, vector_guard):
    sql, _family, _job_row = await _world(db)
    await set_switch(db, SEMANTIC_RERANK_KEY, True)
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)
    posting = await _posting(db, source, "defer-dedupe", ["sql"])

    for _ in range(5):
        await decide_catalog(db, posting, {sql.id}, defer_semantic=True)

    jobs = await _semantic_jobs(db)
    assert len(jobs) == 1
    assert jobs[0].payload["posting_id"] == str(posting.id)
    assert vector_guard == {"index": 0, "match": 0}


async def test_a_running_job_still_dedupes_the_next_decision(db, source, vector_guard):
    sql, _family, _job_row = await _world(db)
    await set_switch(db, SEMANTIC_RERANK_KEY, True)
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)
    posting = await _posting(db, source, "defer-running", ["sql"])
    [job] = await _semantic_jobs(db)
    job.status = "running"
    await db.flush()

    assert await enqueue_semantic_redecision(db, posting.id, commit=False) is None
    await decide_catalog(db, posting, {sql.id}, defer_semantic=True)

    assert len(await _semantic_jobs(db)) == 1
    assert vector_guard == {"index": 0, "match": 0}


async def test_single_posting_mode_never_creates_a_continuation(db, source, counting_vector):
    _sql, _family, job = await _world(db)
    counting_vector["job_id"] = job.id
    await set_switch(db, SEMANTIC_RERANK_KEY, False)
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)
    posting = await _posting(db, source, "defer-no-continuation", ["sql"])
    jobs_before = len(await _semantic_jobs(db))

    result = await run_posting_remap(db, {"posting_id": str(posting.id), "auto_continue": False})

    assert result["next_after_id"] is None
    assert len(await _semantic_jobs(db)) == jobs_before
    assert posting.mapping_method == MappingMethod.SEMANTIC.value


async def test_enqueue_commit_false_rides_the_callers_transaction(db):
    job_id = None
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            job = await enqueue(
                session,
                BackgroundJobType.POSTING_REMAP.value,
                {"posting_id": str(uuid.uuid4()), "auto_continue": False},
                commit=False,
            )
            job_id = job.id
            assert job_id is not None
            assert await session.get(BackgroundJob, job_id) is not None
            await session.rollback()
        finally:
            if transaction.is_active:
                await transaction.rollback()
            await session.close()

    assert await db.get(BackgroundJob, job_id) is None


# --------------------------------------------------------------- benchmark


async def _measure(decision, *, warmups: int = 3, iterations: int = BENCHMARK_DECISIONS):
    for _ in range(warmups):
        await decision()
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        await decision()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    index = min(len(samples) - 1, round(0.95 * (len(samples) - 1)))
    return statistics.median(samples), samples[index]


async def test_the_request_path_latency_and_call_counts(db, source, vector_guard):
    """The committed local benchmark described in the module docstring."""
    sql, _family, _job_row = await _world(db)
    await set_switch(db, SEMANTIC_RERANK_KEY, False)
    await set_switch(db, SEMANTIC_RESCUE_KEY, False)
    posting = await _posting(db, source, "defer-bench", ["sql"])
    skill_ids = {sql.id}

    off_p50, off_p95 = await _measure(
        lambda: decide_catalog(db, posting, skill_ids, defer_semantic=True)
    )
    assert await _semantic_jobs(db) == []
    assert vector_guard == {"index": 0, "match": 0}
    print(f"\nDEFER-BENCH off N={BENCHMARK_DECISIONS} p50={off_p50:.2f}ms p95={off_p95:.2f}ms")

    await set_switch(db, SEMANTIC_RERANK_KEY, True)
    await set_switch(db, SEMANTIC_RESCUE_KEY, True)
    on_p50, on_p95 = await _measure(
        lambda: decide_catalog(db, posting, skill_ids, defer_semantic=True)
    )
    jobs = await _semantic_jobs(db)
    assert len(jobs) == 1, "dedupe keeps one job across every decision"
    assert vector_guard == {"index": 0, "match": 0}
    print(f"DEFER-BENCH on  N={BENCHMARK_DECISIONS} p50={on_p50:.2f}ms p95={on_p95:.2f}ms")

    assert on_p50 >= 0 and off_p50 >= 0
    assert off_p95 < 2_000 and on_p95 < 2_000, "sanity ceiling, not a production SLA"
    assert (
        int((await db.execute(select(func.count()).select_from(BackgroundJob))).scalar_one()) == 1
    )
