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
