"""— hybrid retrieval: RRF fusion math, filter primacy (a vector hit cannot
resurrect a hard-filtered posting), lexical degradation when the retrieval
index is missing, and the fused ordering being best-first.

The semantic ranking reads the family vector store (plan 50 P1d); these tests
index posting documents directly so the ranking is exactly controlled.
"""

from collections.abc import Iterator

import pytest

from app.ai.gateway import MOCK_EMBED_DIM
from app.services.hybrid_search import fused_order, hybrid_candidate_order, rrf_merge
from tests.conftest import _make_posting
from tests.vector_harness import ContentIndexer, content_indexer, create_native_engine, drop_space


@pytest.fixture
def vectors() -> Iterator[ContentIndexer]:
    engine = create_native_engine()
    indexer = content_indexer(engine, dim=MOCK_EMBED_DIM)
    try:
        yield indexer
    finally:
        drop_space(indexer.harness)
        engine.dispose()


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


async def test_relevance_sort_degrades_to_lexical_without_an_index(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await _make_posting(db, source, external_id="hyb-1")
    result = await client.get(
        "/api/v1/postings/explore",
        params={"q": "data", "sort": "relevance"},
        headers=auth_headers,
    )
    assert result.status_code == 200, result.text
    assert result.json()["total"] >= 1, "no index yet — lexical still works"


async def test_hybrid_rerank_respects_hard_filters(
    client, auth_headers, profile_ready, seeded_catalog, db, source, vectors
):
    from app.ai.gateway import embed_texts

    posting = await _make_posting(db, source, external_id="hyb-2")
    compose = "Data Analyst role at ExtractCo — data, data, data"
    vector = (await embed_texts(db, [compose]))[0]
    vectors.index("posting", str(posting.id), tuple(vector))

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


async def test_hybrid_order_puts_the_agreed_posting_first(
    client, auth_headers, profile_ready, seeded_catalog, db, source, vectors
):
    """The fused score is best-first (the legacy rank-as-score inversion is
    fixed): the posting both the lexical and the semantic ranking favour leads.
    """
    from app.ai.gateway import embed_texts

    semantic_hit = await _make_posting(
        db, source, external_id="hyb-agree", title="Data Analyst", org="AgreeCo"
    )
    lexical_only = await _make_posting(
        db, source, external_id="hyb-lex", title="Data Wrangler (no vector)", org="LexCo"
    )
    vector = (await embed_texts(db, ["data analyst role"]))[0]
    vectors.index("posting", str(semantic_hit.id), tuple(vector))

    result = await client.get(
        "/api/v1/postings/explore",
        params={"q": "data", "sort": "relevance"},
        headers=auth_headers,
    )
    assert result.status_code == 200, result.text
    ids = [item["id"] for item in result.json()["items"]]
    assert str(semantic_hit.id) in ids and str(lexical_only.id) in ids
    assert ids[0] == str(semantic_hit.id), "agreement wins; the lexical-only row still ranks"
