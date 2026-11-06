"""The retrieval read path over the family vector store (plan 50 §6, P1d).

One service answers the two questions the product asks of a space:

* :meth:`VectorRetrievalService.search_text` — embed a free-text query once
  through the gateway ``embed`` task, search the active space per view,
  aggregate chunk hits into one score per document, and (optionally) fuse a
  lexical ranking with weighted RRF.
* :meth:`VectorRetrievalService.similar_documents` — use an indexed
  document's own view vectors as the query against another kind, over a
  bounded candidate set.

Both are *signals*. Hard filters stay SQL-side and are handed in as an opaque
:class:`~app.storage.vector_contract.ScopeSpec` that every backend enforces
before ranking, so a vector hit can never resurrect a filtered-out row.
Missing vectors, an unassigned provider, an embed failure, a missing index
and an over-cap scan all degrade to a structured :class:`RetrievalResult`
with a reason from the contract's closed vocabulary — never an exception and
never a silent zero.

Scores are plain cosine-derived (``per_view`` keeps the raw values for
explainability) so `max`/top-2-mean aggregation is comparable across
backends; the fused score is RRF over view and lexical rankings and is used
for *ordering* only.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AINotConfiguredError
from app.storage.tokenizer_contract import TokenizerSpec
from app.storage.vector_backends import (
    VectorBackendError,
    VectorBackendOverCap,
    VectorIndexMissing,
    VectorSpaceNotFound,
    filter_scope,
)
from app.storage.vector_contract import (
    CANDIDATE_MULTIPLIER,
    MAXSIM_CANDIDATE_CAP,
    RRF_K,
    V1_VIEWS,
    DegradedReason,
    ScopeSpec,
    VectorSpace,
    fused_order,
    rrf_merge,
    top_mean,
)
from app.storage.vector_store import VectorStoreService

CONTENT_SPACE = "content"
#: The default per-view weights of a posting-shaped query (summary and the
#: extracted views lead; the chunked body is the sparse-extraction fallback).
SEMANTIC_VIEW_WEIGHTS: Mapping[str, float] = {
    "summary": 1.5,
    "requirements": 1.5,
    "responsibilities": 1.5,
    "skills": 1.5,
    "body": 1.0,
}
#: Profile↔posting affinity only compares the views both sides compose.
AFFINITY_VIEW_WEIGHTS: Mapping[str, float] = {"summary": 1.5, "skills": 1.5, "body": 1.0}
#: Job↔posting view pairs and their weights (plan 50 §7.2): the extracted
#: facets lead, the chunked body is the sparse-extraction fallback.
JOB_MATCH_VIEW_PAIRS: Mapping[tuple[str, str], float] = {
    ("requirements", "requirements"): 1.5,
    ("responsibilities", "responsibilities"): 1.5,
    ("skills", "skills"): 1.25,
    ("summary", "summary"): 1.0,
    ("body", "body"): 0.5,
}
#: At most this many query chunks per view feed a document-as-query search.
MAX_QUERY_CHUNKS = 4

Embedder = Any  # Callable[[Sequence[str]], Awaitable[list[list[float]]]]


@dataclass(frozen=True)
class DocumentHit:
    """One ranked document: its product identity plus the score breakdown."""

    document_id: str
    kind: str
    source_id: str
    score: float
    per_view: Mapping[str, float] = field(default_factory=dict)
    fused_score: float = 0.0
    backend: str = ""


@dataclass(frozen=True)
class RetrievalResult:
    """Hits plus the structured degradation reason (§4.2) — never an error."""

    hits: tuple[DocumentHit, ...] = ()
    space: str = CONTENT_SPACE
    space_key: str = ""
    backend: str = ""
    degraded: DegradedReason | None = None
    timings: Mapping[str, float] = field(default_factory=dict)

    @property
    def source_ids(self) -> list[str]:
        """The product ids in rank order — what a caller feeds its SQL."""
        return [hit.source_id for hit in self.hits]

    def scores_by_source(self) -> dict[str, DocumentHit]:
        """Source id → hit, for per-row lookups (an affinity window)."""
        return {hit.source_id: hit for hit in self.hits}


def document_score(per_view: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Weighted sum of the per-view similarities, normalized to ``0..1``.

    A negative cosine (an anti-correlated view) counts as no evidence: it can
    lower a document's rank but never below the "nothing matched" floor, and
    the normalization keeps scores comparable across kinds that compose
    different numbers of views.
    """
    total_weight = sum(max(float(weights.get(view, 0.0)), 0.0) for view in per_view)
    if total_weight <= 0.0:
        return 0.0
    total = 0.0
    for view, similarity in per_view.items():
        weight = max(float(weights.get(view, 0.0)), 0.0)
        if weight:
            total += weight * max(float(similarity), 0.0)
    return total / total_weight


def aggregate_view_scores(
    hits: Sequence[Any],
    *,
    aggregation: str = "max",
) -> tuple[dict[str, dict[str, float]], str]:
    """Chunk hits → one score per (document, view); returns the backend name."""
    by_view: dict[str, dict[str, list[float]]] = {}
    backend = ""
    for hit in hits:
        backend = backend or str(hit.backend)
        by_view.setdefault(str(hit.view), {}).setdefault(str(hit.document_id), []).append(
            float(hit.similarity)
        )
    scores: dict[str, dict[str, float]] = {}
    for view, per_document in by_view.items():
        for document_id, values in per_document.items():
            scores.setdefault(document_id, {})[view] = (
                top_mean(values) if aggregation == "top_mean" else max(values)
            )
    return scores, backend


class VectorRetrievalService:
    """Read one space: text queries and document-as-query similarity."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        store: VectorStoreService | None = None,
        space_name: str = CONTENT_SPACE,
        space_id: str | uuid.UUID | None = None,
        embedder: Embedder | None = None,
        user_id: uuid.UUID | None = None,
        run: Any = None,
    ) -> None:
        if store is None:
            from app.core.database import sync_engine

            store = VectorStoreService(sync_engine)
        self.db = db
        self.store = store
        self.space_name = space_name
        # An explicit id reads a non-active (building) space — the pre-cutover
        # quality compare needs the same retrieval math as the live pointer.
        self.space_id = str(space_id) if space_id is not None else None
        self._embedder = embedder
        self._tags: dict[str, Any] = {}
        self._user_id = user_id
        self._run = run

    # ------------------------------------------------------------ public API

    async def search_text(
        self,
        query: str,
        *,
        kind: str | None = None,
        views: Sequence[str] | None = None,
        view_weights: Mapping[str, float] | None = None,
        scope: ScopeSpec | None = None,
        limit: int = 20,
        ef_search: int | None = None,
        candidate_multiplier: int = CANDIDATE_MULTIPLIER,
        aggregation: str = "max",
        lexical_ranked: Sequence[str] | None = None,
        lexical_weight: float = 1.0,
    ) -> RetrievalResult:
        """Rank documents of ``kind`` against a free-text query.

        ``lexical_ranked`` (source ids, best first) is fused with the semantic
        per-view rankings through weighted RRF; a lexical-only id still earns
        its rank, which is what keeps a query answerable with no vectors at
        all. The caller owns the hard filters — ``scope`` is enforced by the
        backend before scoring.
        """
        text = (query or "").strip()
        if not text or limit <= 0:
            return RetrievalResult(space=self.space_name)
        started = time.perf_counter()
        space = self._space()
        if isinstance(space, DegradedReason):
            return RetrievalResult(space=self.space_name, degraded=space)
        # Caller-supplied retrieval tags (plan 51 Q1a): the query embed is
        # attributable to the space and the requested kind, never to text.
        # `phase="query"` separates read-side spend from indexing (plan 201 S7).
        self._tags.clear()
        self._tags["space_id"] = str(space.space_id)
        self._tags["phase"] = "query"
        if kind is not None:
            self._tags["kind"] = kind
        vector = await self._embed_query(text)
        if isinstance(vector, DegradedReason):
            return RetrievalResult(space=self.space_name, degraded=vector)
        if len(vector) != space.dim:
            return RetrievalResult(
                space=space.name,
                space_key=space.key,
                backend=self.store.backend.name,
                degraded=DegradedReason.SPACE_MISMATCH,
            )
        resolved_views = _resolve_views(views or tuple(SEMANTIC_VIEW_WEIGHTS), view_weights)
        weights = _resolve_weights(resolved_views, view_weights)
        scoped = scope if scope is not None else self._kind_scope(kind)
        fetched, backend, degraded = self._search_views(
            space,
            vector,
            views=resolved_views,
            scope=scoped,
            limit=limit,
            ef_search=ef_search,
            candidate_multiplier=candidate_multiplier,
            aggregation=aggregation,
        )
        if degraded is not None:
            return RetrievalResult(
                space=space.name, space_key=space.key, backend=backend, degraded=degraded
            )
        return self._rank(
            space,
            fetched,
            weights,
            limit=limit,
            backend=backend,
            lexical_ranked=lexical_ranked,
            lexical_weight=lexical_weight,
            started=started,
        )

    async def similar_documents(
        self,
        *,
        source_kind: str,
        source_id: str,
        target_kind: str | None = None,
        view_weights: Mapping[str, float] | None = None,
        scope: ScopeSpec | None = None,
        limit: int = 20,
        ef_search: int | None = None,
        candidate_multiplier: int = CANDIDATE_MULTIPLIER,
        aggregation: str = "max",
        exclude_self: bool = True,
    ) -> RetrievalResult:
        """Rank documents near an already-indexed document's view vectors.

        No provider call: the query is the source document's stored vectors
        (read back through the backend, so pgvector/sqlite-vec work too). A
        source that is not indexed yet returns no hits with
        ``index_missing`` — callers keep their neutral fallback.
        """
        if limit <= 0:
            return RetrievalResult(space=self.space_name)
        started = time.perf_counter()
        space = self._space()
        if isinstance(space, DegradedReason):
            return RetrievalResult(space=self.space_name, degraded=space)
        try:
            query_document = self.store.find_document(space, kind=source_kind, source_id=source_id)
        except VectorBackendError:
            query_document = None
        if query_document is None:
            return RetrievalResult(
                space=space.name,
                backend=self.store.backend.name,
                degraded=DegradedReason.INDEX_MISSING,
            )
        stored = [
            vector
            for vector in self.store.document_vectors(space, document_id=query_document)
            if vector.vector
        ]
        if not stored:
            return RetrievalResult(
                space=space.name,
                backend=self.store.backend.name,
                degraded=DegradedReason.INDEX_MISSING,
            )
        weights = dict(view_weights or AFFINITY_VIEW_WEIGHTS)
        available = sorted({vector.view for vector in stored} & set(weights))
        if not available:
            return RetrievalResult(space=space.name, backend=self.store.backend.name)
        scoped = scope if scope is not None else self._kind_scope(target_kind)
        combined: dict[str, dict[str, float]] = {}
        backend = ""
        for view in available:
            chunks = [vector for vector in stored if vector.view == view][:MAX_QUERY_CHUNKS]
            per_document: dict[str, float] = {}
            for chunk in chunks:
                hits, view_backend, degraded = self._search_views(
                    space,
                    list(chunk.vector),
                    views=(view,),
                    scope=scoped,
                    limit=limit,
                    ef_search=ef_search,
                    candidate_multiplier=candidate_multiplier,
                    aggregation=aggregation,
                )
                backend = backend or view_backend
                if degraded is not None:
                    return RetrievalResult(
                        space=space.name, space_key=space.key, backend=backend, degraded=degraded
                    )
                for document_id, per_view in hits.items():
                    for similarity in per_view.values():
                        per_document[document_id] = max(
                            per_document.get(document_id, similarity), similarity
                        )
            for document_id, similarity in per_document.items():
                combined.setdefault(document_id, {})[view] = similarity
        if exclude_self:
            combined.pop(query_document, None)
        return self._rank(
            space,
            combined,
            weights,
            limit=limit,
            backend=backend,
            started=started,
        )

    async def match_documents(
        self,
        *,
        source_kind: str,
        source_id: str,
        target_kind: str | None = None,
        view_weights: Mapping[tuple[str, str], float] | None = None,
        scope: ScopeSpec | None = None,
        limit: int = 20,
        candidate_cap: int = MAXSIM_CANDIDATE_CAP,
        exclude_self: bool = True,
    ) -> RetrievalResult:
        """Score a stored document against another kind, view pair by view pair.

        The long-text counterpart of :meth:`similar_documents` (plan 50
        §7.2): a job and a posting are compared on matching views —
        requirements to requirements, responsibilities to
        responsibilities, skills to skills, summary to summary, and the
        chunked body as the sparse-extraction fallback.

        The per-view similarity is the bounded **MaxSim** approximation:
        each of the source's (capped) chunks is searched against the
        candidate set, the best candidate chunk similarity is kept per
        source chunk, and the mean over the source chunks bounds the value
        in ``0..1``. Candidate records per query chunk are capped by
        ``candidate_cap``; the expensive comparison never touches the
        corpus.

        No provider call: the query is the source document's stored vectors,
        read back through the backend, so linear/pgvector/sqlite-vec all
        work. A source that is not indexed yet returns ``index_missing`` and
        the caller keeps its lexical fallback. ``scope`` is enforced by the
        backend before scoring; an excluded row can never come back.
        """
        if limit <= 0:
            return RetrievalResult(space=self.space_name)
        started = time.perf_counter()
        space = self._space()
        if isinstance(space, DegradedReason):
            return RetrievalResult(space=self.space_name, degraded=space)
        try:
            query_document = self.store.find_document(space, kind=source_kind, source_id=source_id)
        except VectorBackendError:
            query_document = None
        if query_document is None:
            return RetrievalResult(
                space=space.name,
                backend=self.store.backend.name,
                degraded=DegradedReason.INDEX_MISSING,
            )
        stored = [
            vector
            for vector in self.store.document_vectors(space, document_id=query_document)
            if vector.vector
        ]
        if not stored:
            return RetrievalResult(
                space=space.name,
                backend=self.store.backend.name,
                degraded=DegradedReason.INDEX_MISSING,
            )
        pairs = dict(view_weights or JOB_MATCH_VIEW_PAIRS)
        source_chunks: dict[str, list[Any]] = {}
        for vector in stored:
            source_chunks.setdefault(str(vector.view), []).append(vector)
        active = [
            (source_view, target_view, float(weight))
            for (source_view, target_view), weight in sorted(pairs.items())
            if float(weight) > 0 and source_view in source_chunks
        ]
        if not active:
            return RetrievalResult(space=space.name, backend=self.store.backend.name)
        scoped = scope if scope is not None else self._kind_scope(target_kind)
        combined: dict[str, dict[str, float]] = {}
        weights: dict[str, float] = {}
        backend = ""
        for source_view, target_view, weight in active:
            chunks = sorted(source_chunks[source_view], key=lambda item: item.chunk_index)[
                :MAX_QUERY_CHUNKS
            ]
            weights[target_view] = weights.get(target_view, 0.0) + weight
            summed: dict[str, float] = {}
            for chunk in chunks:
                hits, view_backend, degraded = self._search_views(
                    space,
                    list(chunk.vector),
                    views=(target_view,),
                    scope=scoped,
                    limit=max(int(candidate_cap), 1),
                    ef_search=None,
                    candidate_multiplier=1,
                    aggregation="max",
                )
                backend = backend or view_backend
                if degraded is not None:
                    return RetrievalResult(
                        space=space.name, space_key=space.key, backend=backend, degraded=degraded
                    )
                for document_id, per_view in hits.items():
                    similarity = max(float(per_view.get(target_view, 0.0)), 0.0)
                    summed[document_id] = summed.get(document_id, 0.0) + similarity
            for document_id, total in summed.items():
                view_score = total / len(chunks)
                if view_score <= 0.0:
                    continue
                current = combined.setdefault(document_id, {}).get(target_view)
                if current is None or view_score > current:
                    combined[document_id][target_view] = view_score
        if exclude_self:
            combined.pop(query_document, None)
        return self._rank(
            space,
            combined,
            weights,
            limit=limit,
            backend=backend,
            started=started,
            tie_break="source",
        )

    async def match_text(
        self,
        text: str,
        *,
        target_kind: str | None = None,
        view_weights: Mapping[tuple[str, str], float] | None = None,
        scope: ScopeSpec | None = None,
        limit: int = 20,
        lexical_ranked: Sequence[str] | None = None,
        lexical_weight: float = 1.0,
    ) -> RetrievalResult:
        """The free-text counterpart of :meth:`match_documents`.

        Used when the posting has no indexed document yet (or for a one-off
        query): the text is embedded once through the gateway and searched
        against every target view of the pair map. Same degradation
        vocabulary, same scope enforcement, same weighted aggregation — the
        only difference is where the query vector comes from.
        """
        weights = dict(view_weights or JOB_MATCH_VIEW_PAIRS)
        target_views = tuple(dict.fromkeys(target for _, target in sorted(weights)))
        return await self.search_text(
            text,
            kind=target_kind,
            views=target_views,
            view_weights={view: float(weights.get((view, view), 1.0)) for view in target_views},
            scope=scope,
            limit=limit,
            candidate_multiplier=CANDIDATE_MULTIPLIER,
            lexical_ranked=lexical_ranked,
            lexical_weight=lexical_weight,
        )

    # ----------------------------------------------------------- internals

    def _space(self) -> VectorSpace | DegradedReason:
        try:
            if self.space_id is not None:
                return self.store.resolve_space(self.space_id)
            return self.store.active_space(self.space_name)
        except VectorSpaceNotFound:
            return DegradedReason.INDEX_MISSING
        except VectorBackendError:
            return DegradedReason.INDEX_MISSING

    @staticmethod
    def _kind_scope(kind: str | None) -> ScopeSpec | None:
        if kind is None:
            return None
        return filter_scope(kinds=(kind,))

    async def _embed_query(self, text: str) -> list[float] | DegradedReason:
        from app.services import embed_cache

        space = self._space()
        if isinstance(space, DegradedReason):
            return space
        key = embed_cache.cache_key(space, text)
        cached = embed_cache.get(key)
        if cached is not None:
            return cached
        try:
            if self._embedder is not None:
                vectors = await self._embedder([text])
            else:
                from app.ai.gateway import embed_texts

                vectors = await embed_texts(
                    self.db,
                    [text],
                    user_id=self._user_id,
                    run=self._run,
                    metadata=self._tags,
                    tokens_in=await self._query_tokens(text),
                )
        except AINotConfiguredError:
            return DegradedReason.PROVIDER_UNASSIGNED
        except Exception:
            return DegradedReason.EMBED_FAILED
        if not vectors or not vectors[0]:
            return DegradedReason.EMBED_FAILED
        vector = [float(value) for value in vectors[0]]
        embed_cache.put(key, vector)
        return vector

    async def _query_tokens(self, text: str) -> int | None:
        """The query's token count for the audit row (plan 201 S1).

        The space's tokenizer when the space is token-aware, otherwise the
        effective DB profile for its provider/model. ``None`` when no tokenizer
        is known — never a guess, and never a reason to fail the search.
        """
        try:
            space = self._space()
            if isinstance(space, DegradedReason):
                return None
            tokenizer = cast("TokenizerSpec | None", space.tokenizer)
            if tokenizer is None:
                from app.services import embedding_profiles

                profile = await embedding_profiles.resolve_for(self.db, space.provider, space.model)
                tokenizer = profile.tokenizer
            if tokenizer is None:
                return None
            from app.ai.tokenizers import get_tokenizer_service

            return get_tokenizer_service().count_or_fallback(tokenizer, text).tokens
        except Exception:
            return None

    def _search_views(
        self,
        space: VectorSpace,
        vector: Sequence[float],
        *,
        views: Sequence[str],
        scope: ScopeSpec | None,
        limit: int,
        ef_search: int | None,
        candidate_multiplier: int,
        aggregation: str,
    ) -> tuple[dict[str, dict[str, float]], str, DegradedReason | None]:
        """Per-view backend search → ``{document_id: {view: score}}``."""
        scoped = scope if scope is not None else ScopeSpec(kind="all", predicate=None)
        fetch = max(int(limit) * max(int(candidate_multiplier), 1), int(limit))
        combined: dict[str, dict[str, float]] = {}
        backend = self.store.backend.name
        for view in views:
            try:
                hits = self.store.search(
                    space,
                    vector,
                    views=(view,),
                    scope=scoped,
                    limit=fetch,
                    ef_search=ef_search,
                )
            except VectorBackendOverCap:
                return {}, backend, DegradedReason.OVER_CAP
            except VectorIndexMissing:
                return {}, backend, DegradedReason.INDEX_MISSING
            except VectorBackendError:
                return {}, backend, DegradedReason.INDEX_MISSING
            scores, view_backend = aggregate_view_scores(hits, aggregation=aggregation)
            backend = view_backend or backend
            for document_id, per_view in scores.items():
                combined.setdefault(document_id, {}).update(per_view)
        return combined, backend, None

    def _rank(
        self,
        space: VectorSpace,
        scores: Mapping[str, Mapping[str, float]],
        weights: Mapping[str, float],
        *,
        limit: int,
        backend: str,
        lexical_ranked: Sequence[str] | None = None,
        lexical_weight: float = 1.0,
        started: float | None = None,
        tie_break: str = "document",
    ) -> RetrievalResult:
        """Aggregate → fuse → truncate; ties break on the document id.

        ``tie_break="source"`` orders equal scores by the product's source id
        instead — the job↔posting match reads a caller's entity, and that id
        is stable across a reindex of the same store.
        """
        lexical_sources = [str(value) for value in lexical_ranked or ()]
        if not scores and not lexical_sources:
            return RetrievalResult(space=space.name, space_key=space.key, backend=backend)
        documents = self.store.lookup_documents(space, list(scores)) if scores else {}
        if lexical_sources:
            known = {info.source_id for info in documents.values()}
            missing = [value for value in lexical_sources if value not in known]
            if missing:
                documents.update(self.store.lookup_documents(space, source_ids=missing))
        by_source = {info.source_id: document_id for document_id, info in documents.items()}
        lexical_documents = [by_source[value] for value in lexical_sources if value in by_source]

        def order_key(document_id: str) -> tuple:
            score = -document_score(scores[document_id], weights)
            info = documents.get(document_id)
            if tie_break == "source" and info is not None:
                return (score, info.source_id, document_id)
            return (score, document_id)

        semantic_order = sorted(scores, key=order_key)
        view_order: dict[str, list[str]] = {}
        for view in weights:
            ranked = sorted(
                (document_id for document_id in scores if view in scores[document_id]),
                key=lambda document_id: (-scores[document_id][view], document_id),
            )
            if ranked:
                view_order[view] = ranked
        lists: list[list[str]] = list(view_order.values())
        list_weights: list[float] = [float(weights[view]) for view in view_order]
        if lexical_documents:
            lists.append(lexical_documents)
            list_weights.append(float(lexical_weight))
        if len(lists) > 1:
            fused = rrf_merge(lists, k=RRF_K, weights=list_weights)
            order = fused_order(fused)
        elif lexical_documents and not scores:
            order = lexical_documents
            fused = dict.fromkeys(order, 0.0)
        else:
            order = semantic_order
            fused = dict.fromkeys(semantic_order, 0.0)
        hits: list[DocumentHit] = []
        for document_id in order:
            if len(hits) >= limit:
                break
            per_view = dict(scores.get(document_id, {}))
            info = documents.get(document_id)
            hits.append(
                DocumentHit(
                    document_id=document_id,
                    kind=info.kind if info is not None else "",
                    source_id=info.source_id if info is not None else document_id,
                    score=round(document_score(per_view, weights), 6),
                    per_view={view: round(value, 6) for view, value in sorted(per_view.items())},
                    fused_score=round(float(fused.get(document_id, 0.0)), 8),
                    backend=backend,
                )
            )
        timings = {"total_ms": round((time.perf_counter() - started) * 1000, 3)} if started else {}
        return RetrievalResult(
            hits=tuple(hits),
            space=space.name,
            space_key=space.key,
            backend=backend,
            timings=timings,
        )


def _resolve_views(
    views: Sequence[str], view_weights: Mapping[str, float] | None
) -> tuple[str, ...]:
    wanted = list(views) if views else list(view_weights or SEMANTIC_VIEW_WEIGHTS)
    unknown = [view for view in wanted if view not in V1_VIEWS]
    if unknown:
        raise ValueError(f"unknown view(s): {unknown}")
    return tuple(dict.fromkeys(wanted))


def _resolve_weights(
    views: Sequence[str], view_weights: Mapping[str, float] | None
) -> dict[str, float]:
    defaults = SEMANTIC_VIEW_WEIGHTS if view_weights is None else view_weights
    return {view: float(defaults.get(view, 1.0)) for view in views}


__all__ = [
    "AFFINITY_VIEW_WEIGHTS",
    "CONTENT_SPACE",
    "JOB_MATCH_VIEW_PAIRS",
    "MAX_QUERY_CHUNKS",
    "SEMANTIC_VIEW_WEIGHTS",
    "DocumentHit",
    "RetrievalResult",
    "VectorRetrievalService",
    "aggregate_view_scores",
    "document_score",
]
