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
    MAX_QUERY_CHUNKS,
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


# --------------------------------------------------------- document matching


def _seed_job(harness: Harness) -> str:
    """A job document with the four extracted views plus a body chunk."""
    job_id = str(uuid.uuid4())
    harness.add_document("job", kind="job", source_id=job_id)
    harness.index_many(
        [
            harness.record("job", (1.0, 0.0, 0.0, 0.0), view="requirements"),
            harness.record("job", (0.0, 1.0, 0.0, 0.0), view="responsibilities"),
            harness.record("job", (0.0, 0.0, 1.0, 0.0), view="skills"),
            harness.record("job", (0.0, 0.0, 0.0, 1.0), view="summary"),
            harness.record("job", (1.0, 0.0, 0.0, 0.0), view="body"),
        ]
    )
    return job_id


async def test_match_documents_ranks_the_correct_job_per_view(harness: Harness):
    job_id = _seed_job(harness)
    harness.add_document("right", kind="job", source_id="right-job")
    harness.add_document("wrong", kind="job", source_id="wrong-job")
    harness.index_many(
        [
            harness.record("right", (1.0, 0.0, 0.0, 0.0), view="requirements"),
            harness.record("right", (0.0, 1.0, 0.0, 0.0), view="responsibilities"),
            harness.record("right", (0.0, 0.0, 1.0, 0.0), view="skills"),
            harness.record("right", (0.0, 0.0, 0.0, 1.0), view="summary"),
            harness.record("wrong", (0.6, 0.8, 0.0, 0.0), view="requirements"),
            harness.record("wrong", (0.8, 0.6, 0.0, 0.0), view="responsibilities"),
            harness.record("wrong", (0.0, 0.0, 0.6, 0.8), view="skills"),
            harness.record("wrong", (0.0, 0.0, 0.8, 0.6), view="summary"),
        ]
    )

    result = await _service(harness).match_documents(
        source_kind="job",
        source_id=job_id,
        target_kind="job",
        limit=5,
    )

    assert [hit.source_id for hit in result.hits] == ["right-job", "wrong-job"]
    assert result.degraded is None
    assert result.hits[0].per_view["requirements"] == pytest.approx(1.0)
    assert result.hits[0].per_view["responsibilities"] == pytest.approx(1.0)
    assert result.hits[0].score == pytest.approx(1.0)
    assert result.hits[1].per_view["requirements"] == pytest.approx(0.6)
    assert result.hits[1].score == pytest.approx(0.6, abs=1e-5)
    assert result.hits[1].score < result.hits[0].score


async def test_match_documents_maxsim_aggregates_query_chunks(harness: Harness):
    posting_id = str(uuid.uuid4())
    harness.add_document("posting", kind="posting", source_id=posting_id)
    harness.index_many(
        [
            harness.record("posting", (1.0, 0.0, 0.0, 0.0), view="body", chunk_index=0),
            harness.record("posting", (0.0, 1.0, 0.0, 0.0), view="body", chunk_index=1),
        ]
    )
    harness.add_document("both", kind="job", source_id="both-views")
    harness.add_document("one", kind="job", source_id="one-view")
    harness.index_many(
        [
            harness.record("both", (1.0, 0.0, 0.0, 0.0), view="body", chunk_index=0),
            harness.record("both", (0.0, 1.0, 0.0, 0.0), view="body", chunk_index=1),
            harness.record("one", (1.0, 0.0, 0.0, 0.0), view="body", chunk_index=0),
        ]
    )

    result = await _service(harness).match_documents(
        source_kind="posting",
        source_id=posting_id,
        target_kind="job",
        view_weights={("body", "body"): 1.0},
        limit=5,
    )

    by_source = {hit.source_id: hit for hit in result.hits}
    assert by_source["both-views"].per_view["body"] == pytest.approx(1.0)
    assert by_source["one-view"].per_view["body"] == pytest.approx(0.5)
    assert [hit.source_id for hit in result.hits] == ["both-views", "one-view"]


async def test_match_documents_caps_query_chunks(harness: Harness):
    posting_id = str(uuid.uuid4())
    harness.add_document("posting", kind="posting", source_id=posting_id)
    records = [
        harness.record("posting", (1.0, 0.0, 0.0, 0.0), view="body", chunk_index=index)
        for index in range(MAX_QUERY_CHUNKS + 2)
    ]
    records[-1] = harness.record(
        "posting", (0.0, 1.0, 0.0, 0.0), view="body", chunk_index=MAX_QUERY_CHUNKS + 1
    )
    harness.index_many(records)
    harness.add_document("late", kind="job", source_id="late-only")
    harness.index("late", (0.0, 1.0, 0.0, 0.0), view="body")

    result = await _service(harness).match_documents(
        source_kind="posting",
        source_id=posting_id,
        target_kind="job",
        view_weights={("body", "body"): 1.0},
        limit=5,
    )

    assert result.hits == (), "the informative chunk sits past the query-chunk cap"


async def test_match_documents_candidate_cap_bounds_the_scan(harness: Harness):
    job_id = _seed_job(harness)
    harness.add_document("near", kind="job", source_id="near")
    harness.index("near", (1.0, 0.0, 0.0, 0.0), view="requirements")
    limits: list[int] = []

    class SpyStore:
        def __init__(self, inner):
            self._inner = inner
            self.backend = inner.backend

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def search(self, *args, **kwargs):
            limits.append(int(kwargs["limit"]))
            return self._inner.search(*args, **kwargs)

    service = VectorRetrievalService(
        None,  # type: ignore[arg-type]
        store=SpyStore(harness.service),  # type: ignore[arg-type]
        space_name=SPACE,
    )
    await service.match_documents(
        source_kind="job",
        source_id=job_id,
        target_kind="job",
        view_weights={("requirements", "requirements"): 1.0},
        candidate_cap=7,
        limit=5,
    )
    assert limits == [7], "the candidate set is capped, never the corpus"


async def test_match_documents_excludes_self_and_ties_break_on_source_id(harness: Harness):
    job_id = str(uuid.uuid4())
    harness.add_document("query", kind="job", source_id=job_id)
    harness.index("query", (1.0, 0.0, 0.0, 0.0), view="requirements")
    for name, source in (("b", "b-job"), ("a", "a-job")):
        harness.add_document(name, kind="job", source_id=source)
        harness.index(name, (1.0, 0.0, 0.0, 0.0), view="requirements")

    result = await _service(harness).match_documents(
        source_kind="job",
        source_id=job_id,
        target_kind="job",
        view_weights={("requirements", "requirements"): 1.0},
        limit=5,
    )
    assert [hit.source_id for hit in result.hits] == ["a-job", "b-job"]


async def test_match_documents_scope_is_enforced_before_ranking(harness: Harness):
    job_id = _seed_job(harness)
    harness.add_document("allowed", kind="job", source_id="allowed")
    harness.add_document("excluded", kind="job", source_id="excluded")
    harness.index_many(
        [
            harness.record("allowed", (0.2, 0.2, 0.2, 0.2), view="requirements"),
            harness.record("excluded", (1.0, 0.0, 0.0, 0.0), view="requirements"),
        ]
    )

    result = await _service(harness).match_documents(
        source_kind="job",
        source_id=job_id,
        target_kind="job",
        view_weights={("requirements", "requirements"): 1.0},
        scope=filter_scope(kinds=("job",), source_ids=["allowed"]),
        limit=5,
    )
    assert [hit.source_id for hit in result.hits] == ["allowed"]


async def test_match_documents_without_an_indexed_source_degrades(harness: Harness):
    result = await _service(harness).match_documents(
        source_kind="job", source_id=str(uuid.uuid4()), target_kind="posting"
    )
    assert result.hits == ()
    assert result.degraded is vc.DegradedReason.INDEX_MISSING


async def test_match_documents_without_an_active_space_degrades(engine):
    result = await VectorRetrievalService(
        None,  # type: ignore[arg-type]
        store=VectorStoreService(engine, backend=LinearBackend(engine)),
        space_name="missing-space",
    ).match_documents(source_kind="job", source_id=str(uuid.uuid4()), target_kind="posting")
    assert result.hits == ()
    assert result.degraded is vc.DegradedReason.INDEX_MISSING


async def test_match_documents_parity_across_backends(harness: Harness):
    job_id = _seed_job(harness)
    for name, vector in (("a", (1.0, 0.0, 0.0, 0.0)), ("b", (0.7, 0.7, 0.0, 0.0))):
        harness.add_document(name, kind="job", source_id=f"{name}-job")
        harness.index(name, vector, view="requirements")
        harness.index(name, vector, view="summary")

    linear = create_space(harness.engine, backend_name=vc.BACKEND_LINEAR, dim=DIM)
    try:
        linear.add_document("job", kind="job", source_id=job_id)
        linear.index_many(
            [
                linear.record("job", (1.0, 0.0, 0.0, 0.0), view="requirements"),
                linear.record("job", (0.0, 1.0, 0.0, 0.0), view="responsibilities"),
                linear.record("job", (0.0, 0.0, 1.0, 0.0), view="skills"),
                linear.record("job", (0.0, 0.0, 0.0, 1.0), view="summary"),
                linear.record("job", (1.0, 0.0, 0.0, 0.0), view="body"),
            ]
        )
        for name, vector in (("a", (1.0, 0.0, 0.0, 0.0)), ("b", (0.7, 0.7, 0.0, 0.0))):
            linear.add_document(name, kind="job", source_id=f"{name}-job")
            linear.index(name, vector, view="requirements")
            linear.index(name, vector, view="summary")
        native_result = await _service(harness).match_documents(
            source_kind="job", source_id=job_id, target_kind="job", limit=5
        )
        linear_result = await VectorRetrievalService(
            None,  # type: ignore[arg-type]
            store=linear.service,
            space_name=linear.space.name,
        ).match_documents(source_kind="job", source_id=job_id, target_kind="job", limit=5)

        assert [hit.source_id for hit in native_result.hits] == [
            hit.source_id for hit in linear_result.hits
        ]
        assert [hit.score for hit in native_result.hits] == pytest.approx(
            [hit.score for hit in linear_result.hits], abs=1e-5
        )
    finally:
        drop_space(linear)


async def test_match_text_embeds_once_and_searches_the_target_views(harness: Harness):
    harness.add_document("job", kind="job", source_id="job-1")
    harness.index_many(
        [
            harness.record("job", (1.0, 0.0, 0.0, 0.0), view="requirements"),
            harness.record("job", (0.0, 1.0, 0.0, 0.0), view="body"),
        ]
    )
    embedder = StubEmbedder({"Senior data engineer": [1.0, 0.0, 0.0, 0.0]})
    result = await _service(harness, embedder=embedder).match_text(
        "Senior data engineer",
        target_kind="job",
        view_weights={("requirements", "requirements"): 1.0, ("body", "body"): 1.0},
        limit=5,
    )
    assert embedder.calls == 1
    assert [hit.source_id for hit in result.hits] == ["job-1"]
    assert result.hits[0].per_view["requirements"] == pytest.approx(1.0)
    assert result.hits[0].per_view["body"] == pytest.approx(0.0)


async def test_match_text_degrades_without_a_provider(harness: Harness):
    harness.add_document("job", kind="job", source_id="job-1")
    harness.index("job", (1.0, 0.0, 0.0, 0.0), view="requirements")
    result = await VectorRetrievalService(
        None,  # type: ignore[arg-type]
        store=harness.service,
        space_name=SPACE,
        embedder=RaisingEmbedder(AINotConfiguredError("no provider")),
    ).match_text("anything", target_kind="job")
    assert result.hits == ()
    assert result.degraded is vc.DegradedReason.PROVIDER_UNASSIGNED


async def test_a_repeated_query_embedding_is_served_from_the_cache(harness: Harness):
    """Plan 201 S6: the read-path rule — the query is embedded once per
    (space, prefix, normalized text) and cached."""
    harness.add_document("a", source_id="source-a")
    harness.index("a", (1.0, 0.0, 0.0, 0.0))
    embedder = StubEmbedder({"backend engineer": [1.0, 0.0, 0.0, 0.0]})
    service = _service(harness, embedder=embedder)

    first = await service.search_text("Backend   engineer", kind="posting", limit=3)
    second = await service.search_text("backend engineer", kind="posting", limit=3)

    assert embedder.calls == 1, "the normalized repeat is a cache hit"
    assert [hit.source_id for hit in second.hits] == [hit.source_id for hit in first.hits]


async def test_a_different_space_or_prefix_misses_the_cache(harness: Harness):
    harness.add_document("a", source_id="source-a")
    harness.index("a", (1.0, 0.0, 0.0, 0.0))
    embedder = StubEmbedder({"backend engineer": [1.0, 0.0, 0.0, 0.0]})
    service = _service(harness, embedder=embedder)

    await service.search_text("backend engineer", kind="posting", limit=3)
    assert embedder.calls == 1

    from app.services import embed_cache

    # The key separates the prefix role even when the space key is shared.
    key = embed_cache.cache_key(harness.space, "backend engineer")
    stale_key = (key[0], "document-prefix", key[2])
    embed_cache.put(stale_key, [0.0, 0.0, 0.0, 0.0])
    await service.search_text("backend engineer", kind="posting", limit=3)
    assert embedder.calls == 1, "a document-prefix entry never serves a query"


async def test_an_expired_cache_entry_misses(db, harness: Harness, monkeypatch):
    from types import SimpleNamespace

    from app.services import embed_cache

    space = SimpleNamespace(key="space-x", query_prefix=None)
    key = embed_cache.cache_key(space, "query text")
    embed_cache.put(key, [1.0, 0.0])
    monkeypatch.setattr(embed_cache, "TTL_SECONDS", 0.0)

    assert embed_cache.get(key) is None, "an expired entry is a miss, not a stale hit"


def test_cache_keys_are_digests_never_raw_text():
    from types import SimpleNamespace

    from app.services import embed_cache

    space = SimpleNamespace(key="space-x", query_prefix=None)
    key = embed_cache.cache_key(space, "a sensitive resume question")
    joined = "".join(key)
    assert "sensitive" not in joined


async def test_the_query_embed_is_tagged_phase_query(harness: Harness):
    """Plan 201 S7: read-side spend separates from indexing in the ledger."""
    harness.add_document("a", source_id="source-a")
    harness.index("a", (1.0, 0.0, 0.0, 0.0))
    service = _service(harness, embedder=StubEmbedder({"q": [1.0, 0.0, 0.0, 0.0]}))

    await service.search_text("q", kind="posting", limit=3)

    assert service._tags["phase"] == "query"
    assert service._tags["space_id"] == str(harness.space.space_id)
    assert service._tags["kind"] == "posting"
