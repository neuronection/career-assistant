"""— hybrid retrieval: RRF fusion math, filter primacy (a
vector hit cannot resurrect a hard-filtered posting), lexical
degradation when embeddings are unavailable."""

from tests.conftest import _make_posting

from app.services.hybrid_search import fused_order, hybrid_candidate_order, rrf_merge


def test_rrf_merge_math():
    scores = rrf_merge([["a", "b", "c"], ["b", "d"]])
    # b: 2nd in list one, 1st in list two → 1/62 + 1/61
    assert abs(scores["b"] - (1 / 62 + 1 / 61)) < 1e-9
    # a: 1st in list one only → 1/61
    assert abs(scores["a"] - 1 / 61) < 1e-9
    # d: 2nd in list two only → 1/62
    assert abs(scores["d"] - 1 / 62) < 1e-9
    assert fused_order(scores)[0] == "b", "the item both lists agree on wins"


def test_hybrid_candidate_order_keeps_lexical_only_entries():
    merged = hybrid_candidate_order(["a", "b", "c"], ["c"])
    assert set(merged) == {"a", "b", "c"}, "union — no entry is dropped"
    assert merged[0] == "c"


async def test_relevance_sort_degrades_to_lexical_without_embeddings(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await _make_posting(db, source, external_id="hyb-1")
    result = await client.get(
        "/api/v1/postings/explore",
        params={"q": "data", "sort": "relevance"},
        headers=auth_headers,
    )
    assert result.status_code == 200, result.text
    assert result.json()["total"] >= 1, "no embeddings yet — lexical still works"


async def test_hybrid_rerank_respects_hard_filters(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    from app.services.embedding_service import EmbeddingService

    service = EmbeddingService(db)
    posting = await _make_posting(db, source, external_id="hyb-2")
    compose = "Data Analyst role at ExtractCo — data, data, data"
    await service.upsert_embedding("posting", posting.id, compose)

    # Sanity: the store holds the embedding, and near-identical text hits it.
    hits = await service.search_similar(compose)
    assert hits and hits[0]["entity_id"] == str(posting.id)

    # A hard filter (seniority the posting doesn't carry) excludes it —
    # the semantic hit must NOT resurrect it (candidates stay SQL-filtered).
    filtered = await client.get(
        "/api/v1/postings/explore",
        params={"q": "data", "sort": "relevance", "seniority": "lead"},
        headers=auth_headers,
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 0

    # Unfiltered: the embedded posting participates in the ranking.
    ok = await client.get(
        "/api/v1/postings/explore",
        params={"q": "data", "sort": "relevance"},
        headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text
    refs = [item["ref"] for item in ok.json()["items"]]
    assert posting.ref in refs
