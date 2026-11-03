"""The retrieval read path (plan 50 §6, P1d).

Exact/linear parity with the legacy Python cosine ranking on the same corpus
and window, chunk aggregation, per-view scores, scope safety, the full
degradation matrix (missing index, unassigned provider, failed embed, dim
mismatch, over cap) and document-as-query similarity.

The legacy `ai_embeddings` path ranked with a plain cosine over pooled text;
these tests compute the reference ordering with the contract's
:func:`~app.storage.vector_contract.cosine` over the same deterministic
corpus, which is exactly the ranking the old store produced.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AINotConfiguredError
from app.models.vector_model import VectorRecord
from app.services.vector_retrieval_service import (
    DocumentHit,
    RetrievalResult,
    VectorRetrievalService,
    document_score,
)
from app.storage import vector_contract as vc
from app.storage.vector_backends import (
    LinearBackend,
    VectorBackendOverCap,
    document_scope,
    filter_scope,
)
from app.storage.vector_store import VectorStoreService
from tests.vector_harness import Harness, create_native_engine, create_space, drop_space

DIM = 4
SPACE = "content"


class StubEmbedder:
    """A deterministic query embedder: one fixed vector per text."""

    def __init__(self, vectors: dict[str, list[float]], *, default: list[float] | None = None):
        self.vectors = vectors
        self.default = default
        self.calls = 0

    async def __call__(self, texts):
        self.calls += 1
        fallback = self.default or [1.0, 0.0, 0.0, 0.0]
        return [list(self.vectors.get(text, fallback)) for text in texts]


class RaisingEmbedder:
    def __init__(self, error: Exception):
        self.error = error

    async def __call__(self, texts):
        raise self.error


class OverCapBackend(LinearBackend):
    """A linear backend that always reports the honest cap breach."""

    def search(self, space, query, *, views, scope, limit, ef_search=None):  # type: ignore[override]
        raise VectorBackendOverCap("scoped candidates exceed the cap")


@pytest.fixture
def engine() -> Iterator:
    native = create_native_engine()
    try:
        yield native
    finally:
        native.dispose()


@pytest.fixture
def harness(engine) -> Iterator[Harness]:
    space = create_space(engine, name=SPACE, dim=DIM)
    try:
        yield space
    finally:
        drop_space(space)


def _service(harness: Harness, **kwargs) -> VectorRetrievalService:
    return VectorRetrievalService(
        None,  # type: ignore[arg-type] — no gateway call when an embedder is injected
        store=harness.service,
        space_name=SPACE,
        **kwargs,
    )


def _reference_order(corpus: dict[str, list[float]], query: list[float]) -> list[str]:
    return sorted(corpus, key=lambda key: (-vc.cosine(query, corpus[key]), key))


# ------------------------------------------------------------------ search


async def test_search_text_ranks_by_cosine_with_per_view_scores(harness: Harness):
    harness.add_document("a", source_id="source-a")
    harness.add_document("b", source_id="source-b")
    harness.add_document("c", source_id="source-c")
    harness.index("a", (1.0, 0.0, 0.0, 0.0))
    harness.index("b", (0.8, 0.6, 0.0, 0.0))
    harness.index("c", (0.0, 1.0, 0.0, 0.0))
    embedder = StubEmbedder({"backend engineer": [1.0, 0.0, 0.0, 0.0]})

    result = await _service(harness, embedder=embedder).search_text(
        "backend engineer", kind="posting", views=("summary",), limit=3
    )
    assert [hit.source_id for hit in result.hits] == ["source-a", "source-b", "source-c"]
    assert result.degraded is None
    assert result.backend == harness.backend_name
    assert result.hits[0].score == pytest.approx(1.0)
    assert result.hits[2].score == pytest.approx(0.0)
    assert result.hits[0].per_view == {"summary": pytest.approx(1.0)}
    assert embedder.calls == 1, "one query embedding per search"


async def test_search_text_matches_the_legacy_cosine_ranking(harness: Harness):
    """Parity: same corpus, same window → the same order and scores."""
    corpus = {
        "source-1": [1.0, 0.0, 0.0, 0.0],
        "source-2": [0.9, 0.1, 0.2, 0.0],
        "source-3": [0.2, 0.9, 0.1, 0.0],
        "source-4": [-0.5, 0.5, 0.5, 0.5],
        "source-5": [0.33, 0.33, 0.33, 0.0],
    }
    for index, (source_id, vector) in enumerate(corpus.items()):
        name = f"doc-{index}"
        harness.add_document(name, source_id=source_id)
        harness.index(name, tuple(vector))
    query = [0.8, 0.2, 0.1, 0.0]
    embedder = StubEmbedder({"data engineer": query})

    result = await _service(harness, embedder=embedder).search_text(
        "data engineer", kind="posting", views=("summary",), limit=10
    )
    assert [hit.source_id for hit in result.hits] == _reference_order(corpus, query)
    by_source = {hit.source_id: hit for hit in result.hits}
    for source_id, vector in corpus.items():
        assert by_source[source_id].score == pytest.approx(
            max(vc.cosine(query, vector), 0.0), abs=1e-6
        ), "the new store reproduces the legacy cosine score"


async def test_search_text_ties_break_on_document_id(harness: Harness):
    harness.add_document("b", source_id="source-b")
    harness.add_document("a", source_id="source-a")
    for name in ("a", "b"):
        harness.index(name, (1.0, 0.0, 0.0, 0.0))

    result = await _service(
        harness, embedder=StubEmbedder({"q": [1.0, 0.0, 0.0, 0.0]})
    ).search_text("q", kind="posting", views=("summary",), limit=5)
    assert [hit.document_id for hit in result.hits] == sorted(
        str(value) for value in harness.documents.values()
    ), "ties break on the document id, never on insertion order"


async def test_chunk_aggregation_max_and_top_mean(harness: Harness):
    harness.add_document("a", source_id="source-a")
    harness.index_many(
        [
            harness.record("a", (1.0, 0.0, 0.0, 0.0), view="body", chunk_index=0),
            harness.record("a", (0.0, 1.0, 0.0, 0.0), view="body", chunk_index=1),
        ]
    )
    embedder = StubEmbedder({"q": [1.0, 0.0, 0.0, 0.0]})

    maximum = await _service(harness, embedder=embedder).search_text(
        "q", kind="posting", views=("body",), limit=5, aggregation="max"
    )
    mean = await _service(harness, embedder=embedder).search_text(
        "q", kind="posting", views=("body",), limit=5, aggregation="top_mean"
    )
    assert maximum.hits[0].per_view["body"] == pytest.approx(1.0)
    assert mean.hits[0].per_view["body"] == pytest.approx(0.5), "top-2 mean over the chunks"


async def test_scope_filter_cannot_be_resurrected_by_a_vector_hit(harness: Harness):
    harness.add_document("a", source_id="source-a")
    harness.add_document("b", source_id="source-b")
    harness.index("a", (1.0, 0.0, 0.0, 0.0))
    harness.index("b", (1.0, 0.0, 0.0, 0.0))
    embedder = StubEmbedder({"q": [1.0, 0.0, 0.0, 0.0]})

    result = await _service(harness, embedder=embedder).search_text(
        "q",
        kind="posting",
        views=("summary",),
        scope=filter_scope(source_ids=("source-b",)),
        limit=5,
    )
    assert [hit.source_id for hit in result.hits] == ["source-b"]


async def test_missing_vectors_are_absent_not_errors(harness: Harness):
    harness.add_document("a", source_id="source-a")
    harness.index("a", (0.0, 1.0, 0.0, 0.0))
    harness.add_document("b", source_id="source-b")  # indexed document, no records

    result = await _service(
        harness, embedder=StubEmbedder({"q": [1.0, 0.0, 0.0, 0.0]})
    ).search_text("q", kind="posting", views=("summary",), limit=5)
    assert result.degraded is None
    assert [hit.source_id for hit in result.hits] == ["source-a"]


async def test_lexical_rrf_keeps_lexical_only_documents(harness: Harness):
    harness.add_document("a", source_id="source-a")
    harness.add_document("b", source_id="source-b")
    harness.index("a", (1.0, 0.0, 0.0, 0.0))

    result = await _service(
        harness, embedder=StubEmbedder({"q": [1.0, 0.0, 0.0, 0.0]})
    ).search_text(
        "q",
        kind="posting",
        views=("summary",),
        limit=5,
        lexical_ranked=["source-b"],
    )
    assert [hit.source_id for hit in result.hits] == ["source-a", "source-b"], (
        "the item both rankings agree on wins; the lexical-only row still ranks"
    )
    assert result.hits[1].score == 0.0
    assert result.hits[1].fused_score > 0.0


# ------------------------------------------------------------- degradation


async def test_unassigned_provider_degrades(harness: Harness):
    result = await _service(
        harness, embedder=RaisingEmbedder(AINotConfiguredError("no provider"))
    ).search_text("q", kind="posting")
    assert result.hits == ()
    assert result.degraded is vc.DegradedReason.PROVIDER_UNASSIGNED


async def test_embed_failure_degrades(harness: Harness):
    result = await _service(harness, embedder=RaisingEmbedder(TimeoutError("slow"))).search_text(
        "q", kind="posting"
    )
    assert result.hits == ()
    assert result.degraded is vc.DegradedReason.EMBED_FAILED


async def test_dim_mismatch_degrades_as_space_mismatch(harness: Harness):
    result = await _service(harness, embedder=StubEmbedder({"q": [1.0, 0.0, 0.0]})).search_text(
        "q", kind="posting"
    )
    assert result.hits == ()
    assert result.degraded is vc.DegradedReason.SPACE_MISMATCH


async def test_missing_index_degrades(engine):
    store = VectorStoreService(engine, backend=LinearBackend(engine))
    service = VectorRetrievalService(
        None,  # type: ignore[arg-type]
        store=store,
        space_name="no-such-space",
        embedder=StubEmbedder({"q": [1.0, 0.0, 0.0, 0.0]}),
    )
    result = await service.search_text("q", kind="posting")
    assert result.hits == ()
    assert result.degraded is vc.DegradedReason.INDEX_MISSING


async def test_over_cap_degrades(harness: Harness):
    store = VectorStoreService(harness.engine, backend=OverCapBackend(harness.engine))
    service = VectorRetrievalService(
        None,  # type: ignore[arg-type]
        store=store,
        space_name=SPACE,
        embedder=StubEmbedder({"q": [1.0, 0.0, 0.0, 0.0]}),
    )
    result = await service.search_text("q", kind="posting")
    assert result.degraded is vc.DegradedReason.OVER_CAP


# --------------------------------------------------------- similar_documents


def _seed_profile(harness: Harness, user_id: str, vector: tuple[float, ...]) -> uuid.UUID:
    harness.add_document("profile", kind="profile", source_id=user_id, scope_type="user")
    harness.index("profile", vector)
    return harness.documents["profile"]


async def test_similar_documents_ranks_against_the_query_view_vectors(harness: Harness):
    user_id = str(uuid.uuid4())
    _seed_profile(harness, user_id, (1.0, 0.0, 0.0, 0.0))
    harness.add_document("near", source_id="near")
    harness.add_document("far", source_id="far")
    harness.index("near", (1.0, 0.0, 0.0, 0.0))
    harness.index("far", (0.0, 1.0, 0.0, 0.0))

    result = await _service(harness).similar_documents(
        source_kind="profile",
        source_id=user_id,
        target_kind="posting",
        view_weights={"summary": 1.0},
        limit=5,
    )
    assert [hit.source_id for hit in result.hits] == ["near", "far"]
    assert result.hits[0].score == pytest.approx(1.0)
    assert result.degraded is None


async def test_similar_documents_excludes_the_source_itself(harness: Harness):
    harness.add_document("a", source_id="source-a")
    harness.add_document("b", source_id="source-b")
    harness.index("a", (1.0, 0.0, 0.0, 0.0))
    harness.index("b", (0.9, 0.1, 0.0, 0.0))

    result = await _service(harness).similar_documents(
        source_kind="posting", source_id="source-a", target_kind="posting", limit=5
    )
    assert [hit.source_id for hit in result.hits] == ["source-b"]


async def test_similar_documents_without_an_indexed_source_degrades(harness: Harness):
    result = await _service(harness).similar_documents(
        source_kind="profile", source_id=str(uuid.uuid4()), target_kind="posting"
    )
    assert result.hits == ()
    assert result.degraded is vc.DegradedReason.INDEX_MISSING


async def test_similar_documents_aggregates_multiple_views(harness: Harness):
    user_id = str(uuid.uuid4())
    harness.add_document("profile", kind="profile", source_id=user_id, scope_type="user")
    harness.add_document("summary-match", source_id="summary-match")
    harness.add_document("skills-match", source_id="skills-match")
    harness.index_many(
        [
            harness.record("profile", (1.0, 0.0, 0.0, 0.0), view="summary"),
            harness.record("profile", (0.0, 1.0, 0.0, 0.0), view="skills"),
            harness.record("summary-match", (1.0, 0.0, 0.0, 0.0), view="summary"),
            harness.record("summary-match", (0.0, 0.0, 1.0, 0.0), view="skills"),
            harness.record("skills-match", (0.0, 0.0, 1.0, 0.0), view="summary"),
            harness.record("skills-match", (0.0, 1.0, 0.0, 0.0), view="skills"),
        ]
    )

    result = await _service(harness).similar_documents(
        source_kind="profile",
        source_id=user_id,
        target_kind="posting",
        view_weights={"summary": 2.0, "skills": 1.0},
        limit=5,
    )
    assert [hit.source_id for hit in result.hits] == ["summary-match", "skills-match"]
    assert result.hits[0].per_view == {
        "skills": pytest.approx(0.0),
        "summary": pytest.approx(1.0),
    }
    assert result.hits[0].score > result.hits[1].score, "the heavier view wins the tie-break"
    assert result.hits[0].score == pytest.approx(2.0 / 3.0)


# ------------------------------------------------------------------ helpers


def test_document_score_helper_clamps_and_normalizes():
    assert document_score({"summary": 1.0}, {"summary": 1.0}) == pytest.approx(1.0)
    assert document_score({"summary": -1.0}, {"summary": 1.0}) == pytest.approx(0.0)
    assert document_score(
        {"summary": 1.0, "body": 0.0}, {"summary": 3.0, "body": 1.0}
    ) == pytest.approx(0.75)
    assert document_score({}, {"summary": 1.0}) == 0.0
    assert document_score({"summary": 1.0}, {}) == 0.0


def test_result_helpers_expose_source_ids_and_scores():
    result = RetrievalResult(
        hits=(
            DocumentHit(document_id="d1", kind="posting", source_id="s1", score=0.9),
            DocumentHit(document_id="d2", kind="posting", source_id="s2", score=0.5),
        )
    )
    assert result.source_ids == ["s1", "s2"]
    assert result.scores_by_source()["s2"].score == 0.5


def test_document_vectors_round_trip_through_the_backend(harness: Harness):
    harness.add_document("a", source_id="source-a")
    harness.index("a", (1.0, 0.0, 0.0, 0.0), view="summary")
    stored = harness.service.document_vectors(harness.space, document_id=harness.documents["a"])
    assert [(entry.view, entry.chunk_index) for entry in stored] == [("summary", 0)]
    assert stored[0].vector == pytest.approx((1.0, 0.0, 0.0, 0.0))


def test_lookup_documents_by_source_ids(harness: Harness):
    harness.add_document("a", source_id="source-a")
    found = harness.service.lookup_documents(harness.space, source_ids=["source-a", "nope"])
    assert [(info.kind, info.source_id) for info in found.values()] == [("posting", "source-a")]


def test_document_scope_helper_still_admits_exact_documents(harness: Harness):
    harness.add_document("a", source_id="source-a")
    harness.index("a", (1.0, 0.0, 0.0, 0.0))
    with Session(harness.engine) as session:
        records = session.scalars(
            select(VectorRecord).where(VectorRecord.document_id == harness.documents["a"])
        ).all()
        assert records, "the record exists in the space"
    hits = harness.search((1.0, 0.0, 0.0, 0.0), scope=document_scope([str(harness.documents["a"])]))
    assert [hit.document_id for hit in hits] == [str(harness.documents["a"])]


async def test_search_text_parity_across_backends(harness: Harness):
    """Exact/linear parity: the same corpus and query produce the same order
    and scores on the dialect backend and the linear fallback."""
    corpus = {
        "source-a": (1.0, 0.0, 0.0, 0.0),
        "source-b": (0.7, 0.7, 0.0, 0.0),
        "source-c": (0.0, 0.0, 1.0, 0.0),
        "source-d": (-0.6, 0.8, 0.0, 0.0),
    }
    for index, (source_id, vector) in enumerate(corpus.items()):
        harness.add_document(f"doc-{index}", source_id=source_id)
        harness.index(f"doc-{index}", vector)

    linear_harness = create_space(harness.engine, backend_name=vc.BACKEND_LINEAR, dim=DIM)
    try:
        for index, (source_id, vector) in enumerate(corpus.items()):
            linear_harness.add_document(f"doc-{index}", source_id=source_id)
            linear_harness.index(f"doc-{index}", vector)
        query = [0.8, 0.2, 0.1, 0.0]
        embedder = StubEmbedder({"data engineer": query})
        native = await _service(harness, embedder=embedder).search_text(
            "data engineer", kind="posting", views=("summary",), limit=10
        )
        linear = await VectorRetrievalService(
            None,  # type: ignore[arg-type]
            store=linear_harness.service,
            space_name=linear_harness.space.name,
            embedder=StubEmbedder({"data engineer": query}),
        ).search_text("data engineer", kind="posting", views=("summary",), limit=10)

        assert [hit.source_id for hit in native.hits] == [hit.source_id for hit in linear.hits], (
            "identical top-k on every backend"
        )
        assert [hit.score for hit in native.hits] == pytest.approx(
            [hit.score for hit in linear.hits], abs=1e-5
        ), "float32 storage rounding is the only difference"
        assert linear.backend == vc.BACKEND_LINEAR
    finally:
        drop_space(linear_harness)
