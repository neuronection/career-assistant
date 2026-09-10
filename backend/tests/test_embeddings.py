"""— embeddings store: deterministic mock vectors, hash
dedupe, cosine retrieval, recompute + status surfaces."""

from uuid import UUID

from sqlalchemy import select

from tests.conftest import _make_posting, _uid

from app.models.embedding_model import AIEmbedding
from app.services.embedding_service import (
    EmbeddingService,
    cosine,
    compose_posting_text,
)


def test_cosine_math():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([], []) == 0.0
    assert abs(cosine([1.0, 2.0], [1.0, 2.0]) - 1.0) < 1e-9
    assert cosine([1.0], [1.0, 2.0]) == 0.0, "dim mismatch never crashes"


async def test_mock_vectors_are_deterministic_and_unit_length(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.ai.gateway import embed_texts

    vectors = await embed_texts(
        db, ["backend engineer role", "backend engineer role"], UUID(_uid(auth_headers))
    )
    assert len(vectors) == 2
    assert vectors[0] == vectors[1], "same text → same vector"
    assert abs(sum(v * v for v in vectors[0]) - 1.0) < 0.01, "unit length"
    other = await embed_texts(db, ["chef position"], UUID(_uid(auth_headers)))
    assert other[0] != vectors[0]


async def test_upsert_dedupes_on_content_hash(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    service = EmbeddingService(db)
    entity_id = UUID(int=1)
    row1, did1 = await service.upsert_embedding(
        "posting", entity_id, "A data engineering role in Athens", vector=[0.1, 0.2]
    )
    assert did1 is True
    row2, did2 = await service.upsert_embedding(
        "posting", entity_id, "A data engineering role in Athens", vector=[0.1, 0.2]
    )
    assert did2 is False, "same text skips the gateway entirely"
    row3, did3 = await service.upsert_embedding(
        "posting", entity_id, "A different role entirely", vector=[0.3, 0.4]
    )
    assert did3 is True, "changed text re-embeds"
    rows = (await db.execute(select(AIEmbedding))).scalars().all()
    assert len(rows) == 1, "one row per entity — latest text wins"


async def test_recompute_and_search_similar(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await _make_posting(db, source, external_id="emb-1")
    await _make_posting(db, source, external_id="emb-2")
    service = EmbeddingService(db)

    result = await service.recompute_postings(limit=10)
    assert result["embedded"] >= 1

    hits = await service.search_similar("anything at all", limit=5)
    assert hits, "stored embeddings rank against the query"
    assert all(set(h) >= {"entity_kind", "entity_id", "score"} for h in hits)
    top = hits[0]["score"]
    assert all(h["score"] <= top for h in hits), "descending by cosine"

    status = await service.status()
    assert any(s["entity_kind"] == "posting" for s in status)


async def test_compose_posting_text_covers_extract():
    class FakePosting:
        title = "Backend Engineer"
        org = "ACME"
        raw = {"description": "Build services."}
        extract = {
            "skills": [
                {"raw_label": "sql", "priority": "must_have", "required_level": 6}
            ],
            "responsibilities": [{"text": "Ship payments", "time_pct": 40}],
        }

    text = compose_posting_text(FakePosting())
    assert "Backend Engineer" in text and "ACME" in text
    assert "sql" in text and "must_have" in text and "6" in text
    assert "Ship payments (40%)" in text
