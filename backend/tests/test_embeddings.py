"""The embeddings path after the P1d cutover (plan 50).

``ai_embeddings`` is gone: one vector store (``vector_spaces`` /
``vector_documents`` / ``vector_records`` + a physical index) serves every
semantic read. What remains of the embeddings *pipeline* is the gateway
``embed`` task — these tests pin that it still works and that nothing
reintroduces the retired table or the retired modules.
"""

import importlib
from uuid import UUID

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.ai.gateway import MOCK_EMBED_DIM, embed_texts
from app.core.config import settings
from tests.conftest import _uid


def test_the_legacy_store_is_gone():
    """Migration 0088 drops the table; no model/module may come back."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.models.embedding_model")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.embedding_service")


async def test_no_ai_embeddings_table_at_head():
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    finally:
        await engine.dispose()
    assert "ai_embeddings" not in tables
    assert {"vector_spaces", "vector_documents", "vector_records"} <= set(tables)


async def test_mock_vectors_are_deterministic_and_unit_length(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    vectors = await embed_texts(
        db, ["backend engineer role", "backend engineer role"], UUID(_uid(auth_headers))
    )
    assert len(vectors) == 2
    assert vectors[0] == vectors[1], "same text → same vector"
    assert len(vectors[0]) == MOCK_EMBED_DIM
    assert abs(sum(v * v for v in vectors[0]) - 1.0) < 0.01, "unit length"
    other = await embed_texts(db, ["chef position"], UUID(_uid(auth_headers)))
    assert other[0] != vectors[0]


async def test_embed_calls_store_the_caller_supplied_retrieval_tags(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """Plan 51 Q1a: the gateway stores exactly the tags the caller handed it
    (never inventing one), and an untagged call keeps the empty default."""
    from sqlalchemy import select

    from app.models.ai_model import AIGeneration

    user_id = UUID(_uid(auth_headers))
    tags = {
        "space_id": "11111111-1111-1111-1111-111111111111",
        "kind": "posting",
        "view": "summary",
        "chunk_index": 0,
    }
    await embed_texts(db, ["tagged text"], user_id, metadata=tags)
    tagged = (
        await db.execute(
            select(AIGeneration)
            .where(AIGeneration.task_type == "embed")
            .order_by(AIGeneration.created_at.desc(), AIGeneration.id.desc())
            .limit(1)
        )
    ).scalar_one()
    assert tagged.metadata_json == tags
    assert tagged.metadata_schema_version == 1

    await embed_texts(db, ["untagged text"], user_id)
    untagged = (
        await db.execute(
            select(AIGeneration)
            .where(AIGeneration.task_type == "embed")
            .order_by(AIGeneration.created_at.desc(), AIGeneration.id.desc())
            .limit(1)
        )
    ).scalar_one()
    assert untagged.id != tagged.id
    assert untagged.metadata_json == {}


async def test_a_caller_supplied_token_count_lands_on_the_audit_row(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """Plan 201 S1: real spend, not ``None`` — Usage, the EMBED budget and the
    budget alert all sum this column."""
    from sqlalchemy import select

    from app.models.ai_model import AIGeneration

    user_id = UUID(_uid(auth_headers))
    await embed_texts(db, ["counted text"], user_id, tokens_in=42)
    row = (
        await db.execute(
            select(AIGeneration)
            .where(AIGeneration.task_type == "embed")
            .order_by(AIGeneration.created_at.desc(), AIGeneration.id.desc())
            .limit(1)
        )
    ).scalar_one()
    assert row.tokens_in == 42
    assert row.tokens_out is None
    assert row.output == {"count": 1, "dim": MOCK_EMBED_DIM}


async def test_an_uncounted_embed_stays_honestly_none(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from sqlalchemy import select

    from app.models.ai_model import AIGeneration

    await embed_texts(db, ["uncounted text"], UUID(_uid(auth_headers)))
    row = (
        await db.execute(
            select(AIGeneration)
            .where(AIGeneration.task_type == "embed")
            .order_by(AIGeneration.created_at.desc(), AIGeneration.id.desc())
            .limit(1)
        )
    ).scalar_one()
    assert row.tokens_in is None


class _FlakyEmbedModel:
    """A provider model that fails a few times, then answers."""

    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0
        self.chunk_sizes: list[int | None] = []

    async def aembed_documents(self, texts, chunk_size=None):
        self.calls += 1
        self.chunk_sizes.append(chunk_size)
        if self.calls <= self.failures:
            raise RuntimeError("429 too many requests")
        return [[0.1, 0.2] for _ in texts]


def _patch_embedding_model(monkeypatch, model):
    from types import SimpleNamespace

    from app.ai import gateway as gateway_module

    resolved = SimpleNamespace(
        provider_type="openai",
        model_name="text-embedding-3-small",
        api_key="sk-test-key",
        base_url="https://embeddings.example.invalid/v1",
    )

    async def _resolve(db, task, user_id=None):
        return resolved

    monkeypatch.setattr("app.ai.providers.resolution.resolve_task_model", _resolve)
    monkeypatch.setattr("app.ai.model_cache.get_embedding_model", lambda *a, **k: model)
    monkeypatch.setattr(gateway_module, "_embed_retry_delay", lambda attempt, exc: 0.0)
    return gateway_module


async def test_a_transient_embed_failure_retries_inside_the_funnel(db, monkeypatch):
    """Plan 201 S3: the funnel owns retry, and one request is one audit row."""
    from sqlalchemy import select

    from app.models.ai_model import AIGeneration

    model = _FlakyEmbedModel(failures=2)
    gateway_module = _patch_embedding_model(monkeypatch, model)

    vectors = await gateway_module.embed_texts(db, ["a", "b", "c"])

    assert len(vectors) == 3
    assert model.calls == 3
    rows = (
        (await db.execute(select(AIGeneration).where(AIGeneration.task_type == "embed")))
        .scalars()
        .all()
    )
    assert len(rows) == 1, "one row per request outcome, never per attempt"
    assert rows[0].status == "ok"


async def test_an_embed_failure_after_the_attempts_records_one_error_row(db, monkeypatch):
    from sqlalchemy import select

    from app.models.ai_model import AIGeneration

    model = _FlakyEmbedModel(failures=99)
    gateway_module = _patch_embedding_model(monkeypatch, model)

    with pytest.raises(RuntimeError, match="429"):
        await gateway_module.embed_texts(db, ["a"])

    assert model.calls == gateway_module.EMBED_ATTEMPTS
    rows = (
        (await db.execute(select(AIGeneration).where(AIGeneration.task_type == "embed")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "error"


async def test_the_profile_sets_the_provider_request_size(db, monkeypatch):
    """LangChain's own default (1000) must never split our batch."""
    model = _FlakyEmbedModel(failures=0)
    gateway_module = _patch_embedding_model(monkeypatch, model)

    await gateway_module.embed_texts(db, ["a", "b", "c"])

    assert model.chunk_sizes == [3], "one provider request for the whole batch"


async def test_embed_batches_overlaps_provider_requests(db, monkeypatch):
    """Plan 201 S4: one funnel pass, provider calls under a semaphore."""
    import asyncio

    from sqlalchemy import select

    from app.models.ai_model import AIGeneration

    class _SlowModel:
        def __init__(self) -> None:
            self.inflight = 0
            self.peak = 0

        async def aembed_documents(self, texts, chunk_size=None):
            self.inflight += 1
            self.peak = max(self.peak, self.inflight)
            await asyncio.sleep(0.02)
            self.inflight -= 1
            return [[0.1, 0.2] for _ in texts]

    model = _SlowModel()
    gateway_module = _patch_embedding_model(monkeypatch, model)
    batches = [
        gateway_module.EmbedBatch((f"text-{index}",), 3, {"kind": f"kind-{index}"})
        for index in range(4)
    ]

    outcomes = await gateway_module.embed_batches(db, batches, concurrency=4)

    assert model.peak == 4, "the semaphore allows the requested overlap"
    assert all(outcome.vectors is not None for outcome in outcomes)
    assert [outcome.tokens_in for outcome in outcomes] == [3, 3, 3, 3]
    rows = (
        (
            await db.execute(
                select(AIGeneration)
                .where(AIGeneration.task_type == "embed")
                .order_by(AIGeneration.created_at.desc(), AIGeneration.id.desc())
                .limit(4)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 4, "one audit row per batch, written after the calls"
    assert {row.metadata_json["kind"] for row in rows} == {"kind-0", "kind-1", "kind-2", "kind-3"}
    assert all(row.tokens_in == 3 for row in rows)


async def test_embed_batches_serial_at_concurrency_one(db, monkeypatch):
    import asyncio

    class _SerialModel:
        def __init__(self) -> None:
            self.inflight = 0
            self.peak = 0

        async def aembed_documents(self, texts, chunk_size=None):
            self.inflight += 1
            self.peak = max(self.peak, self.inflight)
            await asyncio.sleep(0.01)
            self.inflight -= 1
            return [[0.3, 0.4] for _ in texts]

    model = _SerialModel()
    gateway_module = _patch_embedding_model(monkeypatch, model)
    batches = [gateway_module.EmbedBatch((f"text-{index}",)) for index in range(3)]

    outcomes = await gateway_module.embed_batches(db, batches, concurrency=1)

    assert model.peak == 1, "concurrency 1 restores the pre-plan-201 behaviour"
    assert len(outcomes) == 3


async def test_embed_batches_without_a_provider_audits_once_and_raises(db, monkeypatch):
    import pytest
    from sqlalchemy import select

    from app.ai.gateway import EmbedBatch, embed_batches
    from app.core.errors import AINotConfiguredError
    from app.models.ai_model import AIGeneration

    async def _none(db_, task, user_id=None):
        return None

    monkeypatch.setattr("app.ai.providers.resolution.resolve_task_model", _none)
    batches = [
        EmbedBatch(("a",), None, {"kind": "posting"}),
        EmbedBatch(("b",), None, {"kind": "posting"}),
    ]

    with pytest.raises(AINotConfiguredError):
        await embed_batches(db, batches)

    rows = (
        (await db.execute(select(AIGeneration).where(AIGeneration.task_type == "embed")))
        .scalars()
        .all()
    )
    assert len(rows) == 1, "one unconfigured row for the whole funnel pass"
    assert rows[0].status == "error"
    assert rows[0].metadata_json == {"kind": "posting"}
