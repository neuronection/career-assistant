"""The resumable, budget-capped backfill/reconcile pass (plan 50 §5.7, P1d).

A partial run defers work and a rerun resumes it; unchanged content costs zero
embed calls; coverage snapshots are exact per kind; the caps bound spend; a
deleted source leaves no orphan document; scope metadata survives; failure ids
are bounded; cancellation returns a partial result.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.vector_model import (
    RetrievalCoverageSnapshot,
    VectorDocument,
    VectorRecord,
)
from app.services import vector_index_service as vis
from app.services.vector_index_service import LoadedSource
from app.services.vector_reconcile_service import (
    FAILED_IDS_CAP,
    KindCoverage,
    ReconcileResult,
    VectorReconcileService,
    parse_after,
    parse_carry,
    parse_completed_kinds,
    parse_kinds,
    parse_since,
)
from app.storage import vector_contract as vc
from app.storage.vector_backends import LinearBackend
from app.storage.vector_store import VectorStoreService
from tests.vector_harness import create_sqlite_engine

SPACE = "content"
BODY = " ".join(f"paragraph{index}" for index in range(30))


async def _mock(texts):
    """The deterministic mock vectors, without a gateway audit row."""
    from app.ai.gateway import _mock_embedding

    return [_mock_embedding(text) for text in texts]


class CountingEmbedder:
    """Counts embed calls, so "zero-cost rerun" is a measured fact."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls = 0
        self.texts: list[str] = []

    async def __call__(self, texts):
        self.calls += 1
        self.texts.extend(texts)
        return await self.inner(list(texts))


class FailingEmbedder:
    """Fails a chosen text (a per-document failure, not a batch failure)."""

    def __init__(self, fail_on: str) -> None:
        self.fail_on = fail_on

    async def __call__(self, texts):
        if any(self.fail_on in text for text in texts):
            raise RuntimeError("provider blew up on this document")
        return await _mock(texts)


@pytest.fixture
def engine(tmp_path) -> Iterator:
    candidate = create_sqlite_engine(tmp_path / "vector-reconcile.db")
    try:
        yield candidate
    finally:
        candidate.dispose()


def _fake_posting(source_id, title: str = "Backend Engineer", description: str = BODY):
    return SimpleNamespace(
        id=uuid.UUID(str(source_id)),
        title=title,
        org="ACME",
        raw={"description": description},
        extract={
            "skills": [{"raw_label": "python", "priority": "must_have", "required_level": 6}],
            "responsibilities": [{"text": "Ship payments", "time_pct": 60}],
        },
    )


def _store(engine) -> VectorStoreService:
    return VectorStoreService(engine, backend=LinearBackend(engine))


def _service(db, engine, *, embedder=None, **kwargs) -> VectorReconcileService:
    store = _store(engine)
    return VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=kwargs.pop("kinds", ("posting",)),
        embedder=embedder,
        **kwargs,
    )


def _patch_sources(monkeypatch, postings: list) -> None:
    """Serve the fake postings through the compose/list seam (no DB rows).

    Rows get deterministic ``updated_at`` stamps so the reconcile keyset can
    page them exactly like the real ``list_sources`` query.
    """
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 1, 1, tzinfo=UTC)
    stamped = [(row, base + timedelta(seconds=index)) for index, row in enumerate(postings)]
    by_id = {str(row.id): row for row in postings}

    def _ordered():
        return sorted(stamped, key=lambda pair: (pair[1], str(pair[0].id)))

    async def load_source(_db, kind, source_id):
        row = by_id.get(str(source_id))
        if row is None or kind != "posting":
            return None
        return LoadedSource(composed=vis.compose_posting_views(row), scope_type="global")

    async def list_sources(_db, kind, *, since=None, after=None, limit=None):
        if kind != "posting":
            return []
        rows = _ordered()
        if since is not None:
            rows = [pair for pair in rows if pair[1] >= since]
        if after is not None:
            after_updated, after_id = after
            rows = [
                pair for pair in rows if (pair[1], str(pair[0].id)) > (after_updated, str(after_id))
            ]
        if limit is not None:
            rows = rows[: int(limit)]
        return [vis.SourceRow(source_id=str(row.id), updated_at=updated) for row, updated in rows]

    async def count_sources(_db, kind, *, since=None, after=None):
        if kind != "posting":
            return 0
        rows = _ordered()
        if since is not None:
            rows = [pair for pair in rows if pair[1] >= since]
        if after is not None:
            after_updated, after_id = after
            rows = [
                pair for pair in rows if (pair[1], str(pair[0].id)) > (after_updated, str(after_id))
            ]
        return len(rows)

    monkeypatch.setattr(vis, "load_source", load_source)
    monkeypatch.setattr(vis, "list_sources", list_sources)
    monkeypatch.setattr(vis, "count_sources", count_sources)
    import app.services.vector_reconcile_service as vrs

    monkeypatch.setattr(vrs, "load_source", load_source)
    monkeypatch.setattr(vrs, "list_sources", list_sources)
    monkeypatch.setattr(vrs, "count_sources", count_sources)


def _snapshots(engine) -> list[RetrievalCoverageSnapshot]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(RetrievalCoverageSnapshot).order_by(RetrievalCoverageSnapshot.as_of)
            )
        )


# ------------------------------------------------------------------- backfill


async def test_backfill_indexes_every_source_and_reports_coverage(db, engine, monkeypatch):
    postings = [_fake_posting(uuid.uuid4(), title=f"Role {index}") for index in range(3)]
    _patch_sources(monkeypatch, postings)
    embedder = CountingEmbedder(_mock)
    service = _service(db, engine, embedder=embedder)

    result = await service.run()

    assert result.scanned == 3
    assert result.embedded == 3
    assert result.failed == 0
    assert result.deferred == 0
    assert result.skipped == 0
    [coverage] = result.kinds
    assert coverage.kind == "posting"
    assert coverage.total == 3
    assert coverage.missing == 0 and coverage.stale == 0 and coverage.failed == 0
    assert coverage.embedded == 3
    snapshots = _snapshots(engine)
    assert len(snapshots) == 1
    assert snapshots[0].total == 3 and snapshots[0].embedded == 3
    assert snapshots[0].kind == "posting"
    assert str(snapshots[0].space_id) == str(service._space().space_id)


async def test_rerun_of_unchanged_content_spends_zero_embeds(db, engine, monkeypatch):
    postings = [_fake_posting(uuid.uuid4()) for _ in range(2)]
    _patch_sources(monkeypatch, postings)
    store = _store(engine)
    first = VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    )
    outcome = await first.run()
    assert outcome.embedded == 2

    calls = 0

    async def counting(texts):
        nonlocal calls
        calls += 1
        return await _mock(texts)

    second = VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    )
    second._indexer._embedder = counting
    again = await second.run()

    assert again.embedded == 0
    assert again.skipped == 2, "both documents were already current"
    assert calls == 0, "unchanged content costs zero embed calls"
    assert again.kinds[0].embedded == 2, "coverage still counts them as embedded"


async def test_a_changed_source_is_stale_and_reembeds(db, engine, monkeypatch):
    posting = _fake_posting(uuid.uuid4())
    _patch_sources(monkeypatch, [posting])
    store = _store(engine)
    service = VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    )
    await service.run()

    posting.title = "Senior Backend Engineer"
    retry = VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    )
    result = await retry.run()

    assert result.embedded == 1
    assert result.kinds[0].stale == 0 and result.kinds[0].embedded == 1


async def test_the_document_budget_defers_and_a_rerun_resumes(db, engine, monkeypatch):
    postings = [_fake_posting(uuid.uuid4(), title=f"Role {index}") for index in range(4)]
    _patch_sources(monkeypatch, postings)
    store = _store(engine)

    first = VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting",),
        limit=2,
    )
    partial = await first.run()
    assert partial.embedded == 2
    assert partial.deferred == 2
    assert partial.kinds[0].missing == 2, "the deferred work is still missing"
    assert partial.kinds[0].embedded == 2

    second = VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    )
    resumed = await second.run()
    assert resumed.embedded == 2, "the rerun picks the deferred documents up"
    assert resumed.kinds[0].missing == 0
    assert resumed.kinds[0].embedded == 4
    with Session(engine) as session:
        assert len(session.scalars(select(VectorDocument)).all()) == 4


async def test_the_embed_budget_caps_a_single_run(db, engine, monkeypatch):
    postings = [_fake_posting(uuid.uuid4(), title=f"Role {index}") for index in range(3)]
    _patch_sources(monkeypatch, postings)
    store = _store(engine)

    service = VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting",),
        budget=1,
    )
    result = await service.run()

    assert result.budget_exhausted is True
    assert result.embedded == 1, "one document's records fit the unit budget"
    assert result.deferred == 2


async def test_a_corpus_larger_than_scan_limit_resumes_to_completion(db, engine, monkeypatch):
    postings = [_fake_posting(uuid.uuid4(), title=f"Role {index}") for index in range(5)]
    _patch_sources(monkeypatch, postings)
    embedder = CountingEmbedder(_mock)
    store = _store(engine)

    first = VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting",),
        scan_limit=2,
        embedder=embedder,
    )
    result = await first.run()

    assert result.scanned == 2, "the first batch is exactly scan_limit"
    assert result.embedded == 2
    assert result.done is False
    assert result.next_after["posting"] is not None
    assert result.remaining == 3
    assert result.completed_kinds == ()
    assert _snapshots(engine) == [], "a partial scan publishes no coverage point"

    seen = result.scanned
    runs = 0
    while not result.done:
        resumed = VectorReconcileService(
            db,
            store=store,
            provision_backend=vc.BACKEND_LINEAR,
            kinds=("posting",),
            scan_limit=2,
            embedder=embedder,
            after=result.next_after,
            carry=result.carry,
            completed_kinds=result.completed_kinds,
        )
        result = await resumed.run()
        seen += result.scanned
        runs += 1
        assert runs < 10, "the cursor chain terminates"

    assert seen == 5, "every source was scanned exactly once"
    assert result.done is True
    assert result.next_after["posting"] is None
    assert result.completed_kinds == ("posting",)
    assert embedder.calls == 5, "no document was double-indexed across the resume"

    with Session(engine) as session:
        documents = session.scalars(select(VectorDocument)).all()
        assert len(documents) == 5
        assert len({document.source_id for document in documents}) == 5

    [snapshot] = _snapshots(engine)
    assert snapshot.total == 5
    assert snapshot.embedded == 5, "the carried counters describe the whole kind"


async def test_capacity_exhaustion_mid_batch_resumes_from_the_last_processed_source(
    db, engine, monkeypatch
):
    postings = [_fake_posting(uuid.uuid4(), title=f"Role {index}") for index in range(5)]
    _patch_sources(monkeypatch, postings)
    embedder = CountingEmbedder(_mock)
    store = _store(engine)

    first = VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting",),
        scan_limit=10,
        limit=2,
        embedder=embedder,
    )
    partial = await first.run()

    assert partial.embedded == 2
    assert partial.deferred == 3, "the unscanned remainder is honestly deferred"
    assert partial.done is False
    assert partial.next_after["posting"] is not None
    assert partial.carry["posting"]["seen"] == 2
    assert _snapshots(engine) == []

    second = VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting",),
        scan_limit=10,
        limit=2,
        embedder=embedder,
        after=partial.next_after,
        carry=partial.carry,
        completed_kinds=partial.completed_kinds,
    )
    resumed = await second.run()
    assert resumed.embedded == 2
    assert resumed.done is False
    assert resumed.deferred == 1
    assert resumed.carry["posting"]["seen"] == 4

    third = VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting",),
        scan_limit=10,
        limit=2,
        embedder=embedder,
        after=resumed.next_after,
        carry=resumed.carry,
        completed_kinds=resumed.completed_kinds,
    )
    final = await third.run()
    assert final.embedded == 1
    assert final.done is True
    assert embedder.calls == 5

    with Session(engine) as session:
        documents = session.scalars(select(VectorDocument)).all()
        assert len(documents) == 5
        assert len({document.source_id for document in documents}) == 5
    [snapshot] = _snapshots(engine)
    assert snapshot.total == 5 and snapshot.embedded == 5


async def test_a_completed_kind_snapshots_while_another_kind_is_partial(db, engine, monkeypatch):
    from datetime import UTC, datetime, timedelta

    postings = [_fake_posting(uuid.uuid4())]
    skills = [
        SimpleNamespace(id=uuid.uuid4(), key=f"skill-{index}", label=f"Skill {index}", aliases=[])
        for index in range(3)
    ]
    base = datetime(2026, 1, 1, tzinfo=UTC)
    corpus = {
        "posting": (postings, [base]),
        "skill": (skills, [base + timedelta(seconds=index) for index in range(3)]),
    }
    loaded = {
        "posting": {
            str(row.id): LoadedSource(composed=vis.compose_posting_views(row), scope_type="global")
            for row in postings
        },
        "skill": {
            str(row.id): LoadedSource(composed=vis.compose_skill_views(row), scope_type="global")
            for row in skills
        },
    }
    calls: list[str] = []

    async def load_source(_db, kind, source_id):
        return loaded.get(kind, {}).get(str(source_id))

    async def list_sources(_db, kind, *, since=None, after=None, limit=None):
        calls.append(kind)
        rows, stamps = corpus.get(kind, ([], []))
        pairs = sorted(zip(rows, stamps, strict=True), key=lambda pair: (pair[1], str(pair[0].id)))
        if after is not None:
            after_updated, after_id = after
            pairs = [
                pair
                for pair in pairs
                if (pair[1], str(pair[0].id)) > (after_updated, str(after_id))
            ]
        if limit is not None:
            pairs = pairs[: int(limit)]
        return [vis.SourceRow(source_id=str(row.id), updated_at=stamp) for row, stamp in pairs]

    async def count_sources(_db, kind, *, since=None, after=None):
        rows, stamps = corpus.get(kind, ([], []))
        pairs = list(zip(rows, stamps, strict=True))
        if after is not None:
            after_updated, after_id = after
            pairs = [
                pair
                for pair in pairs
                if (pair[1], str(pair[0].id)) > (after_updated, str(after_id))
            ]
        return len(pairs)

    import app.services.vector_reconcile_service as vrs

    monkeypatch.setattr(vis, "load_source", load_source)
    monkeypatch.setattr(vis, "list_sources", list_sources)
    monkeypatch.setattr(vis, "count_sources", count_sources)
    monkeypatch.setattr(vrs, "load_source", load_source)
    monkeypatch.setattr(vrs, "list_sources", list_sources)
    monkeypatch.setattr(vrs, "count_sources", count_sources)

    store = _store(engine)
    first = VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting", "skill"),
        scan_limit=2,
        embedder=_mock,
    )
    partial = await first.run()

    assert partial.done is False
    assert partial.completed_kinds == ("posting",)
    assert partial.next_after["posting"] is None
    assert partial.next_after["skill"] is not None
    assert [snapshot.kind for snapshot in _snapshots(engine)] == ["posting"]

    calls.clear()
    resumed = await VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting", "skill"),
        scan_limit=2,
        embedder=_mock,
        after=partial.next_after,
        carry=partial.carry,
        completed_kinds=partial.completed_kinds,
    ).run()

    assert resumed.done is True
    assert calls == ["skill"], "an already-complete kind is not rescanned"
    assert sorted(snapshot.kind for snapshot in _snapshots(engine)) == ["posting", "skill"]


async def test_the_source_scan_never_asks_for_more_than_scan_limit(db, engine, monkeypatch):
    postings = [_fake_posting(uuid.uuid4(), title=f"Role {index}") for index in range(7)]
    _patch_sources(monkeypatch, postings)
    import app.services.vector_reconcile_service as vrs

    inner = vrs.list_sources
    limits: list[int | None] = []

    async def recording(_db, kind, *, since=None, after=None, limit=None):
        limits.append(limit)
        return await inner(_db, kind, since=since, after=after, limit=limit)

    monkeypatch.setattr(vrs, "list_sources", recording)
    result = await VectorReconcileService(
        db,
        store=_store(engine),
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting",),
        scan_limit=3,
        embedder=_mock,
    ).run()

    assert limits == [3], "the scan is one bounded page, never the whole corpus"
    assert result.scanned == 3
    assert result.next_after["posting"] is not None
    assert result.done is False


async def test_force_reembeds_current_documents(db, engine, monkeypatch):
    posting = _fake_posting(uuid.uuid4())
    _patch_sources(monkeypatch, [posting])
    store = _store(engine)
    await VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    ).run()

    forced = await VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting",),
        force=True,
    ).run()
    assert forced.embedded == 1
    assert forced.skipped == 0


# ------------------------------------------------------- failure + orphan sweep


async def test_a_failed_document_is_counted_and_bounded(db, engine, monkeypatch):
    postings = [_fake_posting(uuid.uuid4(), title=f"Boom {index}") for index in range(3)]
    _patch_sources(monkeypatch, postings)
    store = _store(engine)
    service = VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    )
    service._indexer._embedder = FailingEmbedder("Boom")

    result = await service.run()

    assert result.failed == 3
    assert len(result.failed_ids) == FAILED_IDS_CAP or len(result.failed_ids) == 3
    assert all(value.startswith("posting:") for value in result.failed_ids)
    assert result.kinds[0].failed == 3
    assert result.kinds[0].missing == 3, "a failed document never counts as embedded"


async def test_failed_ids_are_truncated(db, engine, monkeypatch):
    postings = [
        _fake_posting(uuid.uuid4(), title=f"Boom {index}") for index in range(FAILED_IDS_CAP + 5)
    ]
    _patch_sources(monkeypatch, postings)
    store = _store(engine)
    service = VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    )
    service._indexer._embedder = FailingEmbedder("Boom")

    result = await service.run()

    assert result.failed == FAILED_IDS_CAP + 5
    assert len(result.failed_ids) == FAILED_IDS_CAP
    assert result.failed_ids_truncated is True


async def test_a_deleted_source_removes_its_document(db, engine, monkeypatch):
    posting = _fake_posting(uuid.uuid4())
    _patch_sources(monkeypatch, [posting])
    store = _store(engine)
    await VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    ).run()
    with Session(engine) as session:
        assert len(session.scalars(select(VectorDocument)).all()) == 1

    _patch_sources(monkeypatch, [])  # the source row is gone
    result = await VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    ).run()

    assert result.orphans_removed == 1
    with Session(engine) as session:
        assert session.scalars(select(VectorDocument)).all() == []
        assert session.scalars(select(VectorRecord)).all() == []


async def test_orphan_sweep_walks_every_page(db, engine, monkeypatch):
    postings = [_fake_posting(uuid.uuid4(), title=f"Role {index}") for index in range(3)]
    _patch_sources(monkeypatch, postings)
    store = _store(engine)
    await VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    ).run()

    _patch_sources(monkeypatch, postings[:1])  # two documents are now orphans
    service = VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting",),
        scan_limit=2,
    )
    result = await service.run()

    assert result.orphans_removed == 2
    with Session(engine) as session:
        assert len(session.scalars(select(VectorDocument)).all()) == 1


async def test_a_windowed_pass_never_sweeps(db, engine, monkeypatch):
    """A `since` window is not the population: it must not delete documents
    outside the window."""
    posting = _fake_posting(uuid.uuid4())
    _patch_sources(monkeypatch, [posting])
    store = _store(engine)
    await VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    ).run()

    _patch_sources(monkeypatch, [])
    from datetime import UTC, datetime

    windowed = await VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("posting",),
        since=datetime(2026, 1, 1, tzinfo=UTC),
    ).run()
    assert windowed.orphans_removed == 0
    with Session(engine) as session:
        assert len(session.scalars(select(VectorDocument)).all()) == 1


async def test_cancellation_returns_a_partial_result(db, engine, monkeypatch):
    postings = [_fake_posting(uuid.uuid4(), title=f"Role {index}") for index in range(3)]
    _patch_sources(monkeypatch, postings)
    store = _store(engine)
    service = VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    )

    checks = {"count": 0}

    async def cancelled() -> bool:
        checks["count"] += 1
        return checks["count"] > 1

    result = await service.run(cancelled=cancelled)

    assert result.cancelled is True, "the run reports the partial state"
    assert result.scanned == 1
    assert result.embedded == 0
    assert result.deferred >= 1, "whatever was not reached is deferred, never lost"


async def test_provider_unassigned_defers_instead_of_failing(db, engine, monkeypatch):
    from app.core.errors import AINotConfiguredError

    postings = [_fake_posting(uuid.uuid4())]
    _patch_sources(monkeypatch, postings)
    store = _store(engine)
    service = VectorReconcileService(
        db, store=store, provision_backend=vc.BACKEND_LINEAR, kinds=("posting",)
    )

    async def unconfigured(texts):
        raise AINotConfiguredError("no embed provider")

    service._indexer._embedder = unconfigured
    result = await service.run()

    assert result.degraded == "provider_unassigned"
    assert result.failed == 0
    assert result.deferred == 1
    assert result.embedded == 0


# --------------------------------------------------------- auto-continuation


async def _reconcile_job(db, payload: dict):
    from app.models.background_job_model import BackgroundJob
    from app.models.enums import BackgroundJobType

    job = BackgroundJob(
        id=uuid.uuid4(),
        job_type=BackgroundJobType.VECTOR_RECONCILE.value,
        payload=payload,
        status="running",
    )
    db.add(job)
    await db.commit()
    return job


async def _followups(db, job_id):
    from app.models.background_job_model import BackgroundJob
    from app.models.enums import BackgroundJobType

    rows = await db.execute(
        select(BackgroundJob).where(
            BackgroundJob.job_type == BackgroundJobType.VECTOR_RECONCILE.value,
            BackgroundJob.id != job_id,
        )
    )
    return list(rows.scalars().all())


async def _invoke_reconcile_handler(db, job):
    from app.services import job_worker as jw

    async def progress(_value, _stage):
        return None

    async def not_cancelled():
        return False

    return await jw._run_vector_reconcile(db, job, progress=progress, cancelled=not_cancelled)


def _partial_result() -> ReconcileResult:
    return ReconcileResult(
        space=SPACE,
        kinds=(KindCoverage(kind="posting", total=5, missing=3),),
        scanned=2,
        embedded=2,
        deferred=3,
        remaining=3,
        next_after={
            "posting": {"updated_at": "2026-01-01T00:00:02+00:00", "id": str(uuid.uuid4())}
        },
        carry={"posting": {"seen": 2, "missing": 0, "stale": 0, "failed": 0, "embedded": 2}},
        done=False,
    )


async def test_a_partial_reconcile_enqueues_exactly_one_continuation(db, monkeypatch):
    import app.services.vector_reconcile_service as vrs

    partial = _partial_result()

    class FakeService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def run(self, **_kwargs):
            return partial

    monkeypatch.setattr(vrs, "VectorReconcileService", FakeService)
    job = await _reconcile_job(db, {"kinds": ["posting"], "scan_limit": 2})

    await _invoke_reconcile_handler(db, job)
    [followup] = await _followups(db, job.id)
    assert followup.status == "queued"
    assert followup.payload["after"] == partial.next_after
    assert followup.payload["carry"] == partial.carry
    assert followup.payload["completed_kinds"] == []
    assert followup.payload["scan_limit"] == 2
    assert followup.payload["continuation_key"]

    await _invoke_reconcile_handler(db, job)
    assert len(await _followups(db, job.id)) == 1, "the same cursor never duplicates"


async def test_a_completed_reconcile_enqueues_no_continuation(db, monkeypatch):
    import app.services.vector_reconcile_service as vrs

    class FakeService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def run(self, **_kwargs):
            return ReconcileResult(
                space=SPACE,
                kinds=(KindCoverage(kind="posting", total=1, embedded=1),),
                scanned=1,
                embedded=1,
                next_after={"posting": None},
                completed_kinds=("posting",),
                done=True,
            )

    monkeypatch.setattr(vrs, "VectorReconcileService", FakeService)
    job = await _reconcile_job(db, {"kinds": ["posting"], "scan_limit": 2})

    await _invoke_reconcile_handler(db, job)
    assert await _followups(db, job.id) == []


async def test_a_cancelled_reconcile_enqueues_no_continuation(db, monkeypatch):
    import app.services.vector_reconcile_service as vrs

    class FakeService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def run(self, **_kwargs):
            return ReconcileResult(
                space=SPACE,
                kinds=(KindCoverage(kind="posting", total=5, missing=5),),
                scanned=1,
                deferred=4,
                cancelled=True,
                next_after={
                    "posting": {
                        "updated_at": "2026-01-01T00:00:00+00:00",
                        "id": str(uuid.uuid4()),
                    }
                },
                done=False,
            )

    monkeypatch.setattr(vrs, "VectorReconcileService", FakeService)
    job = await _reconcile_job(db, {"kinds": ["posting"], "scan_limit": 2})

    await _invoke_reconcile_handler(db, job)
    assert await _followups(db, job.id) == [], "cancellation stops the chain"


# ------------------------------------------------------------------- payloads


def test_kind_parsing_bounds_the_vocabulary():
    assert parse_kinds(None) is None
    assert parse_kinds("posting,skill") == ("posting", "skill")
    assert parse_kinds(["profile"]) == ("profile",)
    assert parse_kinds(["job"]) == ("job",)
    for bad in ("material", "", []):
        with pytest.raises(ValueError):
            parse_kinds(bad)


def test_since_parsing_normalizes_to_utc():
    from datetime import UTC, datetime

    assert parse_since(None) is None
    parsed = parse_since("2026-11-02T00:00:00Z")
    assert parsed == datetime(2026, 11, 2, tzinfo=UTC)
    assert parse_since("2026-11-02T00:00:00") == datetime(2026, 11, 2, tzinfo=UTC)


def test_cursor_and_carry_payload_parsing():
    from datetime import UTC, datetime

    after = parse_after({"posting": {"updated_at": "2026-11-02T00:00:00Z", "id": "abc"}})
    assert after["posting"] == (datetime(2026, 11, 2, tzinfo=UTC), "abc")
    assert parse_after(None) == {}
    with pytest.raises(ValueError):
        parse_after({"posting": {"id": "abc"}})
    with pytest.raises(ValueError):
        parse_after({"material": {"updated_at": "2026-11-02T00:00:00Z", "id": "abc"}})

    carry = parse_carry({"posting": {"seen": 2, "missing": 1}})
    assert carry["posting"]["seen"] == 2
    assert carry["posting"]["missing"] == 1
    assert carry["posting"]["embedded"] == 0
    assert parse_completed_kinds(["posting"]) == ("posting",)


def test_result_payload_shape():
    result = ReconcileResult(
        space=SPACE,
        kinds=(KindCoverage(kind="posting", total=2),),
        scanned=2,
        embedded=1,
        failed=1,
        failed_ids=("posting:x",),
    )
    payload = result.as_dict()
    assert payload["space"] == SPACE
    assert payload["scanned"] == 2
    assert payload["embedded"] == 1
    assert payload["skipped"] == 0
    assert payload["deferred"] == 0
    assert payload["failed_ids"] == ["posting:x"]
    assert payload["kinds"][0]["kind"] == "posting"
    assert payload["done"] is True
    assert payload["remaining"] == 0
    assert payload["next_after"] == {}
    assert payload["carry"] == {}
    assert payload["completed_kinds"] == []


async def test_a_profile_document_keeps_its_user_scope(db, engine, monkeypatch):
    """Scope safety: a profile indexed by the reconcile pass is user-scoped, so
    no other user's scope filter can see it."""
    from app.models.enums.retrieval import VectorScopeType
    from app.services.vector_composers import compose_profile_views
    from app.storage.vector_backends import filter_scope

    user_id = uuid.uuid4()
    other_id = uuid.uuid4()

    async def load_source(_db, kind, source_id):
        if kind != "profile" or str(source_id) != str(user_id):
            return None
        return LoadedSource(
            composed=compose_profile_views(
                user_id=str(user_id),
                profiles=[{"education": "MSc", "city": "Athens", "country": "GR"}],
                interests=["data"],
                skills=[{"label": "Python", "level": 7}],
                experience_titles=["Analyst"],
            ),
            scope_type=VectorScopeType.USER.value,
            scope_id=user_id,
        )

    async def list_sources(_db, kind, *, since=None, after=None, limit=None):
        return [vis.SourceRow(source_id=str(user_id))] if kind == "profile" else []

    async def count_sources(_db, kind, *, since=None, after=None):
        return 1 if kind == "profile" else 0

    import app.services.vector_reconcile_service as vrs

    monkeypatch.setattr(vis, "load_source", load_source)
    monkeypatch.setattr(vis, "list_sources", list_sources)
    monkeypatch.setattr(vis, "count_sources", count_sources)
    monkeypatch.setattr(vrs, "load_source", load_source)
    monkeypatch.setattr(vrs, "list_sources", list_sources)
    monkeypatch.setattr(vrs, "count_sources", count_sources)

    store = _store(engine)
    result = await VectorReconcileService(
        db,
        store=store,
        provision_backend=vc.BACKEND_LINEAR,
        kinds=("profile",),
        embedder=_mock,
    ).run()
    assert result.embedded == 1

    space = store.active_space(SPACE)
    [info] = store.lookup_documents(space, kind="profile").values()
    assert info.scope_type == "user"
    assert info.scope_id == str(user_id)

    document_vector = store.document_vectors(space, document_id=info.document_id)
    assert document_vector
    query = list(document_vector[0].vector)

    own = store.search(
        space,
        query,
        views=("summary",),
        scope=filter_scope(scope_ids=[str(user_id)]),
        limit=5,
    )
    assert [hit.document_id for hit in own] == [info.document_id]
    stranger = store.search(
        space,
        query,
        views=("summary",),
        scope=filter_scope(scope_ids=[str(other_id)]),
        limit=5,
    )
    assert stranger == [], "another user's scope can never see this profile document"


async def test_the_reconcile_indexes_catalog_jobs(db, engine, seeded_catalog):
    """``job`` joined the reconcile kinds: the catalog backfill uses the same
    bounded pass and publishes a ``job`` coverage snapshot like any other
    kind."""
    from sqlalchemy import func as sa_func

    from app.models.job_model import Job

    service = _service(db, engine, kinds=("job",), limit=1000, embedder=CountingEmbedder(_mock))
    result = await service.run()

    total = int((await db.execute(select(sa_func.count()).select_from(Job))).scalar() or 0)
    assert total > 0
    assert result.done is True
    [coverage] = result.kinds
    assert coverage.kind == "job"
    assert coverage.total == total
    assert coverage.missing == 0 and coverage.failed == 0
    assert coverage.embedded == total
    store = _store(engine)
    space = store.active_space(SPACE)
    assert store.count_documents(space, kind="job") == total
    snapshots = _snapshots(engine)
    assert [snapshot.kind for snapshot in snapshots] == ["job"]


async def test_the_reconcile_handler_passes_an_explicit_space_id(db, monkeypatch):
    """A ``VECTOR_RECONCILE`` payload can target a building space by id."""
    import app.services.vector_reconcile_service as vrs

    seen: dict = {}

    class FakeService:
        def __init__(self, *_args, **kwargs) -> None:
            seen.update(kwargs)

        async def run(self, **_kwargs):
            return ReconcileResult(space="content", space_id=seen.get("space_id"), done=True)

    monkeypatch.setattr(vrs, "VectorReconcileService", FakeService)
    space_id = str(uuid.uuid4())
    job = await _reconcile_job(db, {"kinds": ["posting"], "space_id": space_id})

    result = await _invoke_reconcile_handler(db, job)

    assert seen["space_id"] == space_id
    assert result["space_id"] == space_id


async def test_a_reconcile_continuation_keeps_the_explicit_space_id(db, monkeypatch):
    import app.services.vector_reconcile_service as vrs

    partial = _partial_result()

    class FakeService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def run(self, **_kwargs):
            return partial

    monkeypatch.setattr(vrs, "VectorReconcileService", FakeService)
    space_id = str(uuid.uuid4())
    job = await _reconcile_job(db, {"kinds": ["posting"], "scan_limit": 2, "space_id": space_id})

    await _invoke_reconcile_handler(db, job)

    [followup] = await _followups(db, job.id)
    assert followup.payload["space_id"] == space_id
