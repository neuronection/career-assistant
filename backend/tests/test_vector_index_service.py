"""The index pipeline and its job handler (plan 50 §5, P1c).

Real gateway mock provider: a posting is composed, embedded once, written
with ``prune=False`` and its ``text_ref`` pointers; a re-index of unchanged
content performs zero embed calls; changing one view re-embeds one record;
removing a chunk prunes it; a missing provider degrades honestly; the
``VECTOR_INDEX`` handler obeys the stage/progress/result contract.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import MOCK_EMBED_DIM
from app.core.errors import AINotConfiguredError
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobType
from app.models.vector_model import VectorDocument, VectorRecord
from app.services import vector_index_service as vis
from app.services.job_worker import HANDLERS, JobWorker, enqueue
from app.services.vector_composers import compose_posting_views
from app.services.vector_index_service import (
    CONTENT_SPACE,
    EmbeddingProfile,
    LoadedSource,
    VectorIndexService,
    gateway_embedder,
    load_source,
    record_id_for,
)
from app.storage import vector_contract as vc
from app.storage.vector_backends import LinearBackend, VectorSpaceNotFound
from app.storage.vector_store import VectorStoreService
from tests.conftest import _make_posting
from tests.vector_harness import create_sqlite_engine

BODY = " ".join(f"paragraph{index}" for index in range(400))


class CountingEmbedder:
    """Counts gateway batches; every vector is the deterministic mock's."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls = 0
        self.texts: list[str] = []

    async def __call__(self, texts):
        self.calls += 1
        self.texts.extend(texts)
        return await self.inner(list(texts))


class UnconfiguredEmbedder:
    async def __call__(self, texts):
        raise AINotConfiguredError("no embed provider is assigned")


@pytest.fixture
def engine(tmp_path) -> Iterator:
    candidate = create_sqlite_engine(tmp_path / "vector-index.db")
    try:
        yield candidate
    finally:
        candidate.dispose()


def _store(engine) -> VectorStoreService:
    return VectorStoreService(engine, backend=LinearBackend(engine))


def _service(db, engine, **kwargs) -> VectorIndexService:
    return VectorIndexService(
        db,
        store=_store(engine),
        provision_backend=vc.BACKEND_LINEAR,
        **kwargs,
    )


def _record_keys(engine, document_id: str) -> set[tuple[str, int]]:
    with Session(engine) as session:
        return {
            (record.view, record.chunk_index)
            for record in session.scalars(
                select(VectorRecord).where(VectorRecord.document_id == uuid.UUID(document_id))
            )
        }


def _record_ids(engine, document_id: str) -> set[str]:
    with Session(engine) as session:
        return {
            str(record.id)
            for record in session.scalars(
                select(VectorRecord).where(VectorRecord.document_id == uuid.UUID(document_id))
            )
        }


def _fake_posting(source_id, **overrides) -> SimpleNamespace:
    values = {
        "id": uuid.UUID(str(source_id)),
        "title": "Backend Engineer",
        "org": "ACME",
        "raw": {"description": BODY},
        "extract": {
            "skills": [{"raw_label": "python", "priority": "must_have", "required_level": 6}],
            "responsibilities": [{"text": "Ship payments", "time_pct": 60}],
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_index_posting_end_to_end(db, engine, source, seeded_catalog):
    posting = await _make_posting(db, source, external_id="vec-1")
    outcome = await _service(db, engine).index_document(kind="posting", source_id=str(posting.id))
    assert outcome.degraded is None
    assert outcome.space == CONTENT_SPACE
    assert outcome.scanned == outcome.embedded == outcome.written > 0
    assert outcome.skipped == 0
    assert outcome.pruned == 0
    assert outcome.document_id is not None

    store = _store(engine)
    space = store.active_space(CONTENT_SPACE)
    assert space.dim == MOCK_EMBED_DIM
    assert space.provider == "mock"
    assert space.composer_version == "1"
    assert space.index_table is None, "linear provisioning owns no physical table"
    assert store.count(space) == outcome.scanned

    with Session(engine) as session:
        documents = session.scalars(select(VectorDocument)).all()
        assert len(documents) == 1
        assert documents[0].source_id == str(posting.id)
        assert documents[0].scope_type == "global"
        records = session.scalars(select(VectorRecord)).all()
        assert records
        for record in records:
            assert record.text_ref is not None
            assert record.text_ref["table"] == "job_postings"
            assert record.text_ref["id"] == str(posting.id)
            assert record.text_ref_schema_version == 1
            assert record.embedding is not None, "the linear backend stores the vector"


async def test_the_embed_audit_write_is_released_before_the_store_writes(
    db, engine, source, seeded_catalog
):
    """SQLite has one writer: the gateway's embed call flushes the audit row
    into this session, so the indexer commits it before the store's own
    connection writes. Postgres keeps the single transaction."""
    posting = await _make_posting(db, source, external_id="vec-audit-release")
    events: list[str] = []
    original_commit = db.commit

    async def _spy_commit():
        events.append("commit")
        await original_commit()

    db.commit = _spy_commit  # type: ignore[method-assign]
    indexer = _service(db, engine)
    original_register = indexer.store.register_document

    def _spy_register(*args, **kwargs):
        events.append("register")
        return original_register(*args, **kwargs)

    indexer.store.register_document = _spy_register  # type: ignore[method-assign]
    inner = indexer._embedder

    class _AuditEmbedder:
        async def __call__(self, texts):
            events.append("embed")
            await db.flush()
            return await inner(texts)

    indexer._embedder = _AuditEmbedder()
    try:
        outcome = await indexer.index_document(kind="posting", source_id=str(posting.id))
    finally:
        db.commit = original_commit  # type: ignore[method-assign]

    assert outcome.degraded is None
    embed_at = events.index("embed")
    register_at = events.index("register")
    released = [
        index
        for index, event in enumerate(events)
        if event == "commit" and embed_at < index < register_at
    ]
    if db.get_bind().dialect.name == "sqlite":
        assert released, f"the audit write must commit before the store write: {events}"
    else:
        assert not released, f"Postgres keeps one transaction across the write: {events}"


async def test_reindex_of_unchanged_content_costs_zero_embeds(db, engine, source, seeded_catalog):
    posting = await _make_posting(db, source, external_id="vec-2")
    counter = CountingEmbedder(gateway_embedder(db))
    service = _service(db, engine, embedder=counter)

    first = await service.index_document(kind="posting", source_id=str(posting.id))
    assert counter.calls == 1
    calls_after_first = counter.calls
    ids_after_first = _record_ids(engine, str(first.document_id))

    second = await service.index_document(kind="posting", source_id=str(posting.id))
    assert counter.calls == calls_after_first, "an unchanged document embeds nothing"
    assert second.embedded == 0
    assert second.skipped == first.scanned
    assert second.document_id == first.document_id
    assert second.pruned == 0
    assert _record_ids(engine, str(first.document_id)) == ids_after_first
    assert ids_after_first == {
        record_id_for(str(first.document_id), view, chunk)
        for view, chunk in _record_keys(engine, str(first.document_id))
    }


async def test_unchanged_reindex_needs_neither_a_provider_nor_an_embed(
    db, engine, source, seeded_catalog
):
    posting = await _make_posting(db, source, external_id="vec-9")
    await _service(db, engine).index_document(kind="posting", source_id=str(posting.id))

    counter = CountingEmbedder(UnconfiguredEmbedder())
    outcome = await _service(db, engine, embedder=counter).index_document(
        kind="posting", source_id=str(posting.id)
    )
    assert outcome.degraded is None
    assert outcome.embedded == 0
    assert counter.calls == 0, "an unchanged document never asks for a provider"


async def test_changed_view_reembeds_only_that_view(db, engine, source, seeded_catalog):
    posting = await _make_posting(db, source, external_id="vec-3")
    counter = CountingEmbedder(gateway_embedder(db))
    service = _service(db, engine, embedder=counter)

    composed = compose_posting_views(_fake_posting(posting.id))
    await service.index_composed(
        LoadedSource(composed=composed, scope_type="global"),
        kind="posting",
        source_id=str(posting.id),
    )
    counter.calls = 0
    counter.texts.clear()

    updated = compose_posting_views(
        _fake_posting(
            posting.id,
            extract={
                "skills": [{"raw_label": "python", "priority": "must_have", "required_level": 6}],
                "responsibilities": [{"text": "Own the payments roadmap", "time_pct": 40}],
            },
        )
    )
    outcome = await service.index_composed(
        LoadedSource(composed=updated, scope_type="global"),
        kind="posting",
        source_id=str(posting.id),
    )
    assert outcome.embedded == 1, "only the responsibilities view changed"
    assert outcome.skipped == len(composed.records) - 1
    assert counter.calls == 1
    assert "Own the payments roadmap" in counter.texts[0]
    assert outcome.pruned == 0


async def test_removed_chunk_is_pruned_without_a_reembed(db, engine, source, seeded_catalog):
    posting = await _make_posting(db, source, external_id="vec-4")
    counter = CountingEmbedder(gateway_embedder(db))
    service = _service(db, engine, embedder=counter)

    long_composed = compose_posting_views(_fake_posting(posting.id))
    first = await service.index_composed(
        LoadedSource(composed=long_composed, scope_type="global"),
        kind="posting",
        source_id=str(posting.id),
    )
    body_chunks = [record for record in long_composed.records if record.view == "body"]
    assert len(body_chunks) > 1
    counter.calls = 0

    shortened = BODY[:1600]
    short_composed = compose_posting_views(
        _fake_posting(posting.id, raw={"description": shortened})
    )
    assert len([record for record in short_composed.records if record.view == "body"]) == 1
    outcome = await service.index_composed(
        LoadedSource(composed=short_composed, scope_type="global"),
        kind="posting",
        source_id=str(posting.id),
    )
    assert outcome.embedded == 0, "the surviving chunk's text is unchanged"
    assert outcome.pruned == len(body_chunks) - 1
    assert outcome.document_id == first.document_id

    kept = {record.key for record in short_composed.records}
    with Session(engine) as session:
        keys = {
            (record.view, record.chunk_index)
            for record in session.scalars(
                select(VectorRecord).where(
                    VectorRecord.document_id == uuid.UUID(str(first.document_id))
                )
            )
        }
    assert keys == kept


async def test_force_reembeds_an_unchanged_document(db, engine, source, seeded_catalog):
    posting = await _make_posting(db, source, external_id="vec-5")
    counter = CountingEmbedder(gateway_embedder(db))
    service = _service(db, engine, embedder=counter)
    composed = compose_posting_views(_fake_posting(posting.id))
    loaded = LoadedSource(composed=composed, scope_type="global")
    await service.index_composed(loaded, kind="posting", source_id=str(posting.id))
    counter.calls = 0

    outcome = await service.index_composed(
        loaded, kind="posting", source_id=str(posting.id), force=True
    )
    assert outcome.embedded == len(composed.records)
    assert outcome.skipped == 0
    assert counter.calls == 1


async def test_missing_provider_degrades_without_creating_a_space(db, engine):
    source_id = str(uuid.uuid4())
    loaded = LoadedSource(
        composed=compose_posting_views(_fake_posting(source_id)),
        scope_type="global",
    )
    service = _service(
        db,
        engine,
        embedder=UnconfiguredEmbedder(),
        profile=EmbeddingProfile(provider="openai", model="text-embedding-3-small"),
    )
    outcome = await service.index_composed(loaded, kind="posting", source_id=source_id)
    assert outcome.degraded == vc.DegradedReason.PROVIDER_UNASSIGNED.value
    assert outcome.embedded == 0 and outcome.document_id is None
    with pytest.raises(VectorSpaceNotFound):
        _store(engine).active_space(CONTENT_SPACE)
    with Session(engine) as session:
        assert session.scalars(select(VectorDocument)).all() == []


async def test_missing_provider_leaves_existing_records_and_source_hash_intact(
    db, engine, source, seeded_catalog
):
    posting = await _make_posting(db, source, external_id="vec-6")
    composed = compose_posting_views(_fake_posting(posting.id))
    loaded = LoadedSource(composed=composed, scope_type="global")
    await _service(db, engine).index_composed(loaded, kind="posting", source_id=str(posting.id))
    with Session(engine) as session:
        document = session.scalars(select(VectorDocument)).one()
        before_hash = document.source_hash
        before_records = len(session.scalars(select(VectorRecord)).all())

    broken = _service(
        db,
        engine,
        embedder=UnconfiguredEmbedder(),
        profile=EmbeddingProfile(provider="mock", model="mock-small"),
    )
    changed = compose_posting_views(
        _fake_posting(posting.id, raw={"description": "A completely new description"})
    )
    outcome = await broken.index_composed(
        LoadedSource(composed=changed, scope_type="global"),
        kind="posting",
        source_id=str(posting.id),
    )
    assert outcome.degraded == vc.DegradedReason.PROVIDER_UNASSIGNED.value
    with Session(engine) as session:
        document = session.scalars(select(VectorDocument)).one()
        assert document.source_hash == before_hash
        assert len(session.scalars(select(VectorRecord)).all()) == before_records


async def test_unknown_kind_and_missing_source_are_honest(db, engine):
    service = _service(db, engine)
    assert (
        await service.index_document(kind="posting", source_id=str(uuid.uuid4()))
    ).degraded == "source_missing"
    with pytest.raises(ValueError):
        await load_source(db, "material", str(uuid.uuid4()))
    with pytest.raises(ValueError):
        await load_source(db, "posting", "not-a-uuid")


async def test_profile_kind_indexes_user_scoped_documents(db, engine, profile_ready):
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().one()
    outcome = await _service(db, engine, user_id=user.id).index_document(
        kind="profile", source_id=str(user.id)
    )
    assert outcome.degraded is None
    assert outcome.scanned > 0
    with Session(engine) as session:
        document = session.scalars(select(VectorDocument)).one()
        assert document.scope_type == "user"
        assert document.scope_id == user.id
        assert document.profile_id is None
        assert all(
            record.text_ref["table"] == "users"
            for record in session.scalars(select(VectorRecord)).all()
        )


async def test_job_kind_indexes_catalog_job_views(db, engine, seeded_catalog):
    """A catalog job joins the same store as a posting: the same five views,
    skill links with importance/level, and pointers at ``jobs``."""
    from app.models.job_model import Job

    job = (await db.execute(select(Job).where(Job.code == "software-developer"))).scalars().one()
    counter = CountingEmbedder(gateway_embedder(db))
    outcome = await _service(db, engine, embedder=counter).index_document(
        kind="job", source_id=str(job.id)
    )
    assert outcome.degraded is None
    assert outcome.scanned == outcome.embedded == outcome.written > 0
    assert counter.calls == 1
    with Session(engine) as session:
        document = session.scalars(select(VectorDocument)).one()
        assert document.kind == "job"
        assert document.source_id == str(job.id)
        assert document.scope_type == "global"
        records = session.scalars(select(VectorRecord)).all()
        assert {"summary", "requirements", "skills"} <= {record.view for record in records}
        for record in records:
            assert record.text_ref["table"] == "jobs"
            assert record.text_ref["id"] == str(job.id)

    refreshed = await _service(db, engine, embedder=counter).index_document(
        kind="job", source_id=str(job.id)
    )
    assert refreshed.embedded == 0
    assert counter.calls == 1, "an unchanged job embeds nothing"


async def test_a_draft_job_is_still_indexed(db, engine, seeded_catalog):
    """The store carries no product status: drafts are indexed too, so
    publishing needs no reindex. The published gate lives in the readers."""
    from app.models.job_model import Job

    job = (await db.execute(select(Job).limit(1))).scalars().one()
    job.status = "draft"
    await db.flush()
    outcome = await _service(db, engine).index_document(kind="job", source_id=str(job.id))
    assert outcome.degraded is None
    with Session(engine) as session:
        assert session.scalars(select(VectorDocument)).one().kind == "job"


async def test_skill_kind_composes_one_short_vector(db, engine, seeded_catalog):
    from app.models.taxonomy_model import Skill

    skill = (await db.execute(select(Skill).order_by(Skill.key).limit(1))).scalars().one()
    outcome = await _service(db, engine).index_document(kind="skill", source_id=str(skill.id))
    assert outcome.scanned == 1
    assert outcome.embedded == 1
    with Session(engine) as session:
        record = session.scalars(select(VectorRecord)).one()
        assert record.view == "summary"
        assert record.text_ref == {
            "table": "skills",
            "id": str(skill.id),
            "field": "key+label+aliases",
        }


def _bind_test_store(db, engine):
    """Patch the module seam so the handler builds a store on the temp DB."""

    def _factory(*args, **kwargs):
        kwargs.setdefault("store", _store(engine))
        kwargs.setdefault("provision_backend", vc.BACKEND_LINEAR)
        return VectorIndexService(*args, **kwargs)

    return _factory


async def test_vector_index_job_handler_reports_the_result_contract(
    db, engine, source, seeded_catalog, monkeypatch
):
    posting = await _make_posting(db, source, external_id="vec-7")
    monkeypatch.setattr(vis, "VectorIndexService", _bind_test_store(db, engine))
    stages: list[tuple[int, str]] = []
    job = BackgroundJob(
        job_type=BackgroundJobType.VECTOR_INDEX.value,
        payload={"kind": "posting", "source_id": str(posting.id)},
        status="queued",
        attempts=1,
        max_attempts=1,
    )
    db.add(job)
    await db.flush()

    async def progress(value: int, stage: str) -> None:
        stages.append((value, stage))

    async def never_cancelled() -> bool:
        return False

    assert "vector_index" in HANDLERS
    result = await HANDLERS["vector_index"](db, job, progress=progress, cancelled=never_cancelled)
    assert set(result) >= {
        "scanned",
        "embedded",
        "skipped",
        "written",
        "pruned",
        "failed",
        "failed_ids",
        "failed_ids_truncated",
        "gate",
        "degraded",
    }
    assert result["failed"] == 0 and result["gate"] is None
    assert result["embedded"] == result["scanned"] > 0
    assert stages[0][1] == "loading source"
    assert stages[-1] == (100, "indexed")


async def test_job_worker_executes_a_vector_index_job(
    db, engine, source, seeded_catalog, monkeypatch
):
    posting = await _make_posting(db, source, external_id="vec-8")
    monkeypatch.setattr(vis, "VectorIndexService", _bind_test_store(db, engine))
    job = await enqueue(
        db,
        BackgroundJobType.VECTOR_INDEX.value,
        {"kind": "posting", "source_id": str(posting.id)},
    )
    worker = JobWorker(db)
    claimed = await worker.claim_next()
    assert claimed is not None and claimed.id == job.id
    await worker.execute(claimed)
    await db.refresh(job)
    assert job.status == "succeeded"
    assert job.progress == 100
    assert job.result["embedded"] > 0


async def test_an_active_space_without_an_index_is_reprovisioned_before_the_write(
    db, engine, source, seeded_catalog
):
    """The P1c retry trap: an active space whose ``index_table`` is NULL (a
    failed or legacy provision) must heal on the first write, not fail
    forever against a missing index."""
    from app.models.vector_model import VectorSpace as VectorSpaceRow
    from app.storage.vector_backends import (
        BACKEND_SQLITE_VEC,
        SqliteVecBackend,
        sqlite_vec_available,
    )

    if not sqlite_vec_available(engine):  # pragma: no cover - desktop extra absent
        pytest.skip("sqlite-vec is not loadable in this interpreter")

    async def embedder(texts):
        from app.ai.gateway import _mock_embedding

        return [_mock_embedding(text) for text in texts]

    posting = await _make_posting(db, source, external_id="vec-heal")
    store = VectorStoreService(engine, backend=SqliteVecBackend(engine))  # type: ignore[arg-type]
    space = store.create_space(
        name=CONTENT_SPACE,
        provider="mock",
        model="mock-embed",
        dim=MOCK_EMBED_DIM,
    )
    assert space.index_table is None, "an active space can exist unprovisioned"

    service = VectorIndexService(
        db,
        store=store,
        provision_backend=BACKEND_SQLITE_VEC,
        embedder=embedder,
        profile=vis.EmbeddingProfile(provider="mock", model="mock-embed"),
    )
    outcome = await service.index_document(kind="posting", source_id=str(posting.id))

    assert outcome.degraded is None, "the write heals the space instead of degrading"
    healed = store.active_space(CONTENT_SPACE)
    assert healed.index_table is not None, "the first write provisioned the index"
    with Session(engine) as session:
        assert session.get(VectorSpaceRow, uuid.UUID(str(healed.space_id))) is not None


async def test_a_space_that_cannot_be_provisioned_reports_index_missing(
    db, engine, source, seeded_catalog, monkeypatch
):
    """A heal that cannot succeed degrades the write honestly — it never
    loops on a missing table."""
    from app.storage.vector_backends import SqliteVecBackend, sqlite_vec_available

    if not sqlite_vec_available(engine):  # pragma: no cover - desktop extra absent
        pytest.skip("sqlite-vec is not loadable in this interpreter")

    posting = await _make_posting(db, source, external_id="vec-nofix")
    store = VectorStoreService(engine, backend=SqliteVecBackend(engine))  # type: ignore[arg-type]
    store.create_space(name=CONTENT_SPACE, provider="mock", model="mock-embed", dim=MOCK_EMBED_DIM)

    def broken_provision(*_args, **_kwargs):
        raise RuntimeError("provisioning is unavailable")

    monkeypatch.setattr(vis, "provision_space", broken_provision)

    async def embedder(texts):
        from app.ai.gateway import _mock_embedding

        return [_mock_embedding(text) for text in texts]

    service = VectorIndexService(
        db,
        store=store,
        embedder=embedder,
        profile=vis.EmbeddingProfile(provider="mock", model="mock-embed"),
    )
    outcome = await service.index_document(kind="posting", source_id=str(posting.id))

    assert outcome.degraded == "index_missing"
    assert outcome.written == 0
    assert store.active_space(CONTENT_SPACE).index_table is None
