"""Index pipeline for the family vector store (plan 50 §5, P1c).

One document at a time: compose its views (pure, versioned composers) →
hash each record → resolve the active ``content`` space (creating and
provisioning it on first use) → embed only the records whose content
changed → upsert them with ``prune=False`` plus their ``text_ref`` pointer →
prune the keys that no longer compose.

The writer never deletes a record it did not just re-embed (the P1b
``records_to_embed`` footgun), and an unchanged document costs zero provider
calls. A missing embedding provider degrades to a structured outcome
(``provider_unassigned``) instead of a failed request or a half-written
document; a provider *failure* propagates so the background job retries.

Source loading is async (the app session) while the store is synchronous
(same seam as the P1b service). Provisioning happens here because this
module is only reached from a job/CLI — never a request path.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, cast

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AIBudgetExceededError, AINotConfiguredError
from app.models.enums.retrieval import VectorScopeType
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services.progress import ProgressCb
from app.services.vector_composers import (
    CHUNKER_VERSION,
    COMPOSER_VERSION,
    TOKEN_SAFETY_MARGIN,
    ComposedDocument,
    InputTooLong,
    compose_job_views,
    compose_posting_views,
    compose_profile_views,
    compose_skill_views,
    compose_token_records,
)
from app.storage.tokenizer_contract import ChunkConfig, TokenizerSpec
from app.storage.vector_backends import (
    BACKEND_LINEAR,
    ResolvedEmbedding,
    VectorIndexMissing,
    VectorSpaceNotFound,
)
from app.storage.vector_contract import DegradedReason, IndexRecord, VectorSpace
from app.storage.vector_provisioning import provision_space
from app.storage.vector_store import TextRef, VectorStoreService

logger = logging.getLogger(__name__)

CONTENT_SPACE = "content"
EMBED_BATCH_SIZE = 64

VECTOR_RECORD_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://neuronection.local/career/vector-record"
)


class Embedder(Protocol):
    """One provider call for a batch of texts.

    Production passes ``tokens=`` (the batch's counted tokens, plan 201 S1) so
    the gateway can audit real spend. An injected test callable may accept only
    the texts; the index service calls it without the keyword.
    """

    async def __call__(
        self, texts: Sequence[str], *, tokens: int | None = None
    ) -> list[list[float]]: ...


@dataclass(frozen=True)
class PreparedDocument:
    """One document staged for embedding, before any provider call (S5).

    Everything expensive that does not need vectors lives here: space
    resolution/provisioning, the token-aware recompose, the per-item input
    check and the stored-hash diff. ``changed`` may be empty — a changed
    ``source_hash`` with identical record hashes still needs register +
    prune. ``embed_calls_before`` lets a caller attribute provider requests.
    """

    kind: str
    source_id: str
    space: VectorSpace
    profile: EmbeddingProfile | None
    loaded: LoadedSource
    composed: ComposedDocument
    changed: tuple[Any, ...]
    changed_tokens: list[int] | None
    changed_exact: bool
    record_count: int
    document_id: str | None
    tags: dict[str, Any]
    precomputed: list[list[float]] | None = None
    embed_calls_before: int = 0
    space_creation_calls: int = 0

    @property
    def changed_token_total(self) -> int | None:
        """The document's own sent tokens (shared texts may overlap)."""
        if self.changed_tokens is None:
            return None
        return sum(self.changed_tokens)


@dataclass
class WindowEmbed:
    """The result of embedding a window of prepared documents.

    ``vectors`` maps the document's position in the window to vectors aligned
    with its ``changed`` records. ``failed`` carries the per-document error of
    a split retry that failed again; ``degraded`` the positions whose provider
    is unassigned. ``tokens`` is the **deduped** sent total for the window —
    the number the run counter and the audit rows agree on.
    """

    vectors: dict[int, list[list[float]]] = field(default_factory=dict)
    failed: dict[int, str] = field(default_factory=dict)
    degraded: set[int] = field(default_factory=set)
    doc_embed_calls: dict[int, int] = field(default_factory=dict)
    embed_calls: int = 0
    tokens: int | None = None
    tokens_exact: bool = True


@dataclass(frozen=True)
class EmbeddingProfile:
    """The resolved embedding configuration a write is about to use.

    ``tokenizer``/``chunk`` are the **effective** profile (admin → curated →
    fallback) and drive per-item budgeting, batching and token counts. They
    are also what a v2 build persists; a v1 auto-created space keeps its char
    chunker and only uses them for limits/accounting.
    """

    provider: str
    model: str
    normalize: bool = True
    query_prefix: str | None = None
    document_prefix: str | None = None
    tokenizer: TokenizerSpec | None = None
    chunk: ChunkConfig | None = None
    batch_max_items: int = EMBED_BATCH_SIZE
    batch_max_tokens: int | None = None

    def to_resolved(self, dim: int) -> ResolvedEmbedding:
        """The writer-guard view of this profile at the embedded dimension."""
        return ResolvedEmbedding(
            provider=self.provider,
            model=self.model,
            dim=dim,
            normalize=self.normalize,
            query_prefix=self.query_prefix,
            document_prefix=self.document_prefix,
        )


@dataclass(frozen=True)
class IndexOutcome:
    """One document's index result (the P1c job result contract)."""

    kind: str
    source_id: str
    space: str
    document_id: str | None = None
    scanned: int = 0
    embedded: int = 0
    skipped: int = 0
    written: int = 0
    pruned: int = 0
    degraded: str | None = None
    failed: int = 0
    failed_reason: str | None = None
    tokens: int | None = None
    tokens_exact: bool = False
    embed_calls: int = 0

    def as_result(self) -> dict[str, Any]:
        """The ``background_jobs.result`` payload (plan 51 §3.2 shape)."""
        return {
            "kind": self.kind,
            "source_id": self.source_id,
            "space": self.space,
            "document_id": self.document_id,
            "scanned": self.scanned,
            "embedded": self.embedded,
            "skipped": self.skipped,
            "written": self.written,
            "pruned": self.pruned,
            "failed": self.failed,
            "failed_ids": ([f"{self.kind}:{self.source_id}"] if self.failed else []),
            "failed_ids_truncated": False,
            "gate": None,
            "degraded": self.degraded,
            "failed_reason": self.failed_reason,
        }


@dataclass(frozen=True)
class LoadedSource:
    """A composed document plus the ownership axis it is indexed under."""

    composed: ComposedDocument
    scope_type: str
    scope_id: uuid.UUID | None = None
    profile_id: uuid.UUID | None = None


def record_id_for(document_id: str, view: str, chunk_index: int) -> str:
    """Stable record id for one document key (reindex keeps the identity)."""
    return str(uuid.uuid5(VECTOR_RECORD_NAMESPACE, f"{document_id}:{view}:{chunk_index}"))


@dataclass(frozen=True)
class SourceRow:
    """One indexable source row (the reconcile pass's scan unit)."""

    source_id: str
    updated_at: Any = None


_SOURCE_MODELS: dict[str, Any] = {}


def _source_model(kind: str) -> Any:
    if not _SOURCE_MODELS:
        from app.models.job_model import Job
        from app.models.posting_model import JobPosting
        from app.models.taxonomy_model import Skill
        from app.models.user_model import User

        _SOURCE_MODELS.update({"posting": JobPosting, "job": Job, "skill": Skill, "profile": User})
    try:
        return _SOURCE_MODELS[kind]
    except KeyError:
        raise ValueError(f"kind {kind!r} has no vector composer") from None


async def list_sources(
    db: AsyncSession,
    kind: str,
    *,
    since: Any = None,
    after: Any = None,
    limit: int | None = None,
) -> list[SourceRow]:
    """The kind's source rows in a stable ``(updated_at, id)`` order.

    This is the reconcile scan: an id list and its version stamp, never the
    composed text. ``since`` narrows to rows touched at/after a moment
    (``updated_at``); ``after`` is an exclusive keyset cursor as
    ``(updated_at, id)``.
    """
    model = _source_model(kind)
    statement = select(model.id, model.updated_at).order_by(model.updated_at, model.id)
    if since is not None:
        statement = statement.where(model.updated_at >= since)
    if after is not None:
        after_updated, after_id = after
        statement = statement.where(
            or_(
                model.updated_at > after_updated,
                and_(model.updated_at == after_updated, model.id > after_id),
            )
        )
    if limit is not None:
        statement = statement.limit(int(limit))
    return [
        SourceRow(source_id=str(source_id), updated_at=updated_at)
        for source_id, updated_at in (await db.execute(statement)).all()
    ]


async def count_sources(
    db: AsyncSession,
    kind: str,
    *,
    since: Any = None,
    after: Any = None,
) -> int:
    """How many source rows this kind holds (the coverage denominator).

    ``after`` counts only the rows beyond an exclusive ``(updated_at, id)``
    keyset cursor, so a batched reconcile reports its unscanned remainder
    without loading it.
    """
    model = _source_model(kind)
    statement = select(func.count()).select_from(model)
    if since is not None:
        statement = statement.where(model.updated_at >= since)
    if after is not None:
        after_updated, after_id = after
        statement = statement.where(
            or_(
                model.updated_at > after_updated,
                and_(model.updated_at == after_updated, model.id > after_id),
            )
        )
    return int((await db.execute(statement)).scalar() or 0)


def gateway_embedder(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    run: Any = None,
    tags: dict[str, Any] | None = None,
) -> Embedder:
    """The production embedder: every batch through the gateway ``embed`` task.

    ``tags`` is a live dictionary the caller mutates as it learns the
    retrieval dimensions (space/kind/view/chunk index); the gateway stores
    whatever is present at call time — it never invents a tag (plan 51 Q1a).
    """

    async def _embed(texts: Sequence[str], *, tokens: int | None = None) -> list[list[float]]:
        from app.ai.gateway import embed_texts

        return await embed_texts(
            db,
            list(texts),
            user_id=user_id,
            run=run,
            metadata=tags,
            tokens_in=tokens,
        )

    # The index service may pass ``tokens=`` only to an embedder that declares
    # support, so a test callable monkeypatched onto ``_embedder`` keeps its
    # one-argument contract.
    setattr(_embed, "supports_tokens", True)  # noqa: B010 - mypy-friendly marker

    return _embed


async def _load_posting(db: AsyncSession, source_id: str) -> LoadedSource | None:
    from app.models.posting_model import JobPosting

    posting = await db.get(JobPosting, uuid.UUID(source_id))
    if posting is None:
        return None
    return LoadedSource(
        composed=compose_posting_views(posting),
        scope_type=VectorScopeType.GLOBAL.value,
    )


async def _load_job(db: AsyncSession, source_id: str) -> LoadedSource | None:
    """Load a catalog job with its family and skill links eagerly loaded.

    Every job is indexed — draft and published alike: the vector metadata
    has no product-status column, so the *published* gate is applied where
    the job is read back (the semantic rescue and the similar-jobs read
    hydrate candidates against `Job.status`). Indexing a draft costs one
    document and means publishing it needs no reindex before it can match.
    """
    from sqlalchemy.orm import selectinload

    from app.models.job_model import Job, JobSkill

    job = (
        (
            await db.execute(
                select(Job)
                .options(
                    selectinload(Job.family),
                    selectinload(Job.skill_links).selectinload(JobSkill.skill),
                )
                .where(Job.id == uuid.UUID(source_id))
            )
        )
        .scalars()
        .first()
    )
    if job is None:
        return None
    skills = [
        {
            "label": link.skill.label if link.skill is not None else "",
            "key": link.skill.key if link.skill is not None else "",
            "importance": link.importance,
            "level": link.required_level,
        }
        for link in job.skill_links
    ]
    return LoadedSource(
        composed=compose_job_views(
            job,
            family_label=job.family.label if job.family is not None else None,
            skills=skills,
        ),
        scope_type=VectorScopeType.GLOBAL.value,
    )


async def _load_skill(db: AsyncSession, source_id: str) -> LoadedSource | None:
    from app.models.taxonomy_model import Skill

    skill = await db.get(Skill, uuid.UUID(source_id))
    if skill is None:
        return None
    return LoadedSource(
        composed=compose_skill_views(skill),
        scope_type=VectorScopeType.GLOBAL.value,
    )


async def _load_profile(db: AsyncSession, source_id: str) -> LoadedSource | None:
    from app.models.experience_model import ExperienceItem
    from app.models.taxonomy_model import InterestTag, Skill
    from app.models.user_model import Profile, UserInterest, UserSkill

    user_id = uuid.UUID(source_id)
    profiles = (
        (
            await db.execute(
                select(Profile)
                .where(Profile.user_id == user_id)
                .order_by(Profile.created_at, Profile.id)
            )
        )
        .scalars()
        .all()
    )
    interests = (
        (
            await db.execute(
                select(InterestTag.label)
                .join(UserInterest, UserInterest.interest_tag_id == InterestTag.id)
                .where(UserInterest.user_id == user_id)
                .order_by(InterestTag.key)
            )
        )
        .scalars()
        .all()
    )
    skills = (
        await db.execute(
            select(Skill.label, UserSkill.level)
            .join(UserSkill, UserSkill.skill_id == Skill.id)
            .where(UserSkill.user_id == user_id, UserSkill.hidden.is_(False))
            .order_by(Skill.key)
        )
    ).all()
    titles = (
        (
            await db.execute(
                select(ExperienceItem.title)
                .where(ExperienceItem.user_id == user_id, ExperienceItem.status == "active")
                .order_by(ExperienceItem.title, ExperienceItem.id)
            )
        )
        .scalars()
        .all()
    )
    composed = compose_profile_views(
        user_id=str(user_id),
        profiles=[
            {
                "education": (profile.basics or {}).get("education_level"),
                "city": (profile.basics or {}).get("city"),
                "country": (profile.basics or {}).get("country"),
            }
            for profile in profiles
        ],
        interests=list(interests),
        skills=[{"label": label, "level": int(level)} for label, level in skills],
        experience_titles=list(titles),
    )
    return LoadedSource(
        composed=composed,
        scope_type=VectorScopeType.USER.value,
        scope_id=user_id,
    )


_LOADERS: dict[str, Callable[[AsyncSession, str], Awaitable[LoadedSource | None]]] = {
    "posting": _load_posting,
    "job": _load_job,
    "skill": _load_skill,
    "profile": _load_profile,
}


async def load_source(db: AsyncSession, kind: str, source_id: str) -> LoadedSource | None:
    """Load and compose one source row; ``None`` when it no longer exists."""
    loader = _LOADERS.get(kind)
    if loader is None:
        raise ValueError(f"kind {kind!r} has no vector composer")
    try:
        canonical = str(uuid.UUID(str(source_id)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"source_id must be a UUID, got {source_id!r}") from exc
    return await loader(db, canonical)


class VectorIndexService:
    """Compose, embed and write one document's records into a space."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        store: VectorStoreService | None = None,
        space_name: str = CONTENT_SPACE,
        space_id: str | uuid.UUID | None = None,
        embedder: Embedder | None = None,
        profile: EmbeddingProfile | None = None,
        provision_backend: str | None = None,
        user_id: uuid.UUID | None = None,
        run: Any = None,
    ) -> None:
        if store is None:
            from app.core.database import sync_engine

            store = VectorStoreService(sync_engine)
        self.db = db
        self.store = store
        self.space_name = space_name
        # An explicit target bypasses the active pointer (a ``building``
        # space's backfill). It never creates a space; the lifecycle service
        # owns that decision.
        self.space_id = str(space_id) if space_id is not None else None
        # Live retrieval tags handed to the gateway with each embed batch
        # (plan 51 Q1a): the pipeline fills them in as it learns the space
        # and the batch's view; the gateway never derives them.
        self._tags: dict[str, Any] = {}
        self._embedder = embedder or gateway_embedder(db, user_id=user_id, run=run, tags=self._tags)
        self._profile = profile
        self._provision_backend = provision_backend
        self._user_id = user_id
        self._run = run
        self._verified_spaces: set[str] = set()
        self._embed_calls = 0

    async def index_document(
        self,
        *,
        kind: str,
        source_id: str,
        force: bool = False,
        source: LoadedSource | None = None,
        progress: ProgressCb | None = None,
    ) -> IndexOutcome:
        """Index one source row by kind + id."""
        loaded = source or await load_source(self.db, kind, source_id)
        if loaded is None:
            return IndexOutcome(
                kind=kind,
                source_id=source_id,
                space=self.space_name,
                degraded="source_missing",
            )
        return await self.index_composed(
            loaded,
            kind=kind,
            source_id=source_id,
            force=force,
            progress=progress,
        )

    async def _release_sqlite_writer(self) -> None:
        """Commit this session so the store's own connection can write.

        SQLite has one writer: the store commits through its own sync engine,
        while this session may hold a write (the caller's pending rows, or the
        gateway's ``ai_generations`` audit flush from the embed call). Without
        the release the sync connection waits the 30s busy timeout inside the
        event loop and the index degrades. Postgres keeps the transaction.
        """
        if self.db.get_bind().dialect.name == "sqlite":
            await self.db.commit()

    async def prepare(
        self,
        loaded: LoadedSource,
        *,
        kind: str,
        source_id: str,
        force: bool = False,
        progress: ProgressCb | None = None,
    ) -> IndexOutcome | PreparedDocument:
        """Stage one document for embedding — everything but the provider call.

        Space resolution and provisioning (the first document also creates and
        provisions the space, which embeds its records — those vectors come
        back as ``precomputed``), token-aware recompose, the per-item input
        check and the stored-hash diff. Returns a terminal
        :class:`IndexOutcome` for a degraded/failed document, or a
        :class:`PreparedDocument` whose ``changed`` may be empty (a changed
        ``source_hash`` with identical record hashes still needs register +
        prune).
        """
        composed = loaded.composed
        if composed.is_empty:
            return IndexOutcome(kind=kind, source_id=source_id, space=self.space_name)
        embed_calls_before = self._embed_calls
        self._tags.clear()
        self._tags["kind"] = kind
        self._tags["phase"] = "index"
        await self._release_sqlite_writer()
        await self._report(progress, 10, "composing")
        profile: EmbeddingProfile | None = None
        space: VectorSpace | None = self._find_space()
        precomputed: list[list[float]] | None = None
        if space is None:
            if self.space_id is not None:
                return self._degraded(kind, source_id, composed, DegradedReason.INDEX_MISSING)
            profile = await self._resolve_profile()
            if profile is None:
                return self._degraded(kind, source_id, composed)
            try:
                space, precomputed = await self._create_space(composed, profile, progress)
            except AIBudgetExceededError:
                # A token budget that tripped during the space-creation embed
                # propagates: the caller defers (plan 201 S1).
                raise
            except AINotConfiguredError:
                return self._degraded(kind, source_id, composed)
            except Exception as exc:
                # The space-creation embed is a real provider call: a failing
                # embedder fails this document exactly like the old per-row
                # path (the reconcile records it and moves on).
                return self._failed(kind, source_id, composed, exc)
            if space is None:
                return self._degraded(kind, source_id, composed)
        else:
            healthy = self._ensure_index(space)
            if healthy is None:
                return self._degraded(kind, source_id, composed, DegradedReason.INDEX_MISSING)
            space = healthy

        if space.token_aware:
            try:
                composed = compose_token_records(
                    composed,
                    tokenizer=space.tokenizer,  # type: ignore[arg-type]
                    chunk=space.chunk,  # type: ignore[arg-type]
                    document_prefix=space.document_prefix,
                )
            except InputTooLong as exc:
                return self._failed(kind, source_id, composed, exc)
            except Exception as exc:  # a missing/corrupt exact asset is a write failure
                from app.ai.tokenizers import TokenizerUnavailable

                if not isinstance(exc, TokenizerUnavailable):
                    raise
                return self._failed(kind, source_id, composed, exc, reason="tokenizer_missing")

        existing_document = self.store.find_document(space, kind=kind, source_id=source_id)
        existing = (
            self.store.existing_content_hashes(space, document_id=existing_document)
            if existing_document is not None
            else {}
        )
        changed = [
            record
            for record in composed.records
            if force or existing.get(record.key) != record.content_hash
        ]
        if profile is None and changed:
            profile = await self._resolve_profile()
        self._tags["space_id"] = str(space.space_id)
        if existing_document is not None:
            # Only registered documents carry one; a first index is attributed
            # through the run result's failed_ids (plan 201 S7 / AD10).
            self._tags["document_id"] = str(existing_document)
        views = {record.view for record in changed}
        if len(views) == 1:
            self._tags["view"] = next(iter(views))
        if len(changed) == 1:
            self._tags["chunk_index"] = changed[0].chunk_index
        counts, counts_exact, prefix_tokens = self._record_counts(space, profile, changed)
        if counts is not None:
            _tokenizer, max_input, _max_items, _max_tokens, _prefix = self._write_limits(
                space, profile
            )
            if max_input is not None:
                for record, count in zip(changed, counts, strict=True):
                    if count + prefix_tokens + TOKEN_SAFETY_MARGIN > max_input:
                        raise InputTooLong(
                            view=getattr(record, "view", None),
                            tokens=count,
                            limit=max_input,
                        )

        return PreparedDocument(
            kind=kind,
            source_id=source_id,
            space=space,
            profile=profile,
            loaded=loaded,
            composed=composed,
            changed=tuple(changed),
            changed_tokens=counts,
            changed_exact=counts_exact,
            record_count=len(composed.records),
            document_id=existing_document,
            tags=dict(self._tags),
            precomputed=precomputed,
            embed_calls_before=embed_calls_before,
            space_creation_calls=self._embed_calls - embed_calls_before,
        )

    async def write(
        self,
        prepared: PreparedDocument,
        vectors: Sequence[Sequence[float]],
        *,
        tokens: int | None = None,
        tokens_exact: bool = False,
        embed_calls: int = 0,
        progress: ProgressCb | None = None,
    ) -> IndexOutcome:
        """Commit a prepared document: register → upsert (prune=False) → prune.

        ``tokens`` is the caller's counted input tokens for this document's
        changed records (the window passes its per-document share; the
        single-document path falls back to its own counts). ``None`` counts
        nothing rather than guessing.
        """
        changed = prepared.changed
        if vectors is not None and len(vectors) != len(changed):
            raise RuntimeError(
                f"embedder returned {len(vectors)} vector(s) for {len(changed)} text(s)"
            )
        vectors = list(vectors or [])
        if tokens is None:
            tokens = prepared.changed_token_total
            tokens_exact = tokens_exact or prepared.changed_exact
        document_id = await self._register(prepared)
        index_records = [
            IndexRecord(
                record_id=record_id_for(document_id, record.view, record.chunk_index),
                document_id=document_id,
                view=record.view,
                chunk_index=record.chunk_index,
                embedding=tuple(vector),
                content_hash=record.content_hash,
                char_start=record.char_start,
                char_end=record.char_end,
                token_count=record.token_count,
                token_start=record.token_start,
                token_end=record.token_end,
            )
            for record, vector in zip(changed, vectors, strict=True)
        ]
        text_refs = {
            record.key: TextRef(dict(record.text_ref), record.text_ref_schema_version)
            for record in changed
            if record.text_ref
        }
        await self._report(progress, 80, "writing records")
        written = 0
        if index_records:
            indexed = self.store.upsert_document(
                prepared.space,
                document_id=document_id,
                records=index_records,
                resolved=(
                    prepared.profile.to_resolved(len(index_records[0].embedding))
                    if prepared.profile is not None
                    else None
                ),
                text_refs=text_refs,
                prune=False,
            )
            written = indexed.written
        pruned = self.store.prune_records(
            prepared.space,
            document_id=document_id,
            keep_keys=[record.key for record in prepared.composed.records],
        )
        await self._report(progress, 100, "indexed")
        return IndexOutcome(
            kind=prepared.kind,
            source_id=prepared.source_id,
            space=prepared.space.name,
            document_id=document_id,
            scanned=len(prepared.composed.records),
            embedded=len(index_records),
            skipped=len(prepared.composed.records) - len(changed),
            written=written,
            pruned=pruned,
            tokens=tokens,
            tokens_exact=tokens_exact,
            embed_calls=embed_calls,
        )

    async def index_composed(
        self,
        loaded: LoadedSource,
        *,
        kind: str,
        source_id: str,
        force: bool = False,
        progress: ProgressCb | None = None,
    ) -> IndexOutcome:
        """The single-document pipeline: prepare → embed → write (plan 201 S5).

        Equivalent to the pre-window path; the reconcile writer drives
        :meth:`prepare` / :meth:`embed_prepared` / :meth:`write` directly so
        many documents can share provider batches.
        """
        prepared = await self.prepare(
            loaded, kind=kind, source_id=source_id, force=force, progress=progress
        )
        if isinstance(prepared, IndexOutcome):
            return prepared
        vectors: list[list[float]] | None = prepared.precomputed
        if vectors is None and prepared.changed:
            await self._report(progress, 40, f"embedding {len(prepared.changed)} record(s)")
            try:
                vectors = await self._embed(
                    prepared.changed,
                    progress,
                    space=prepared.space,
                    profile=prepared.profile,
                    counts=prepared.changed_tokens,
                )
            except InputTooLong as exc:
                return self._failed(kind, prepared.source_id, prepared.composed, exc)
            if vectors is None:
                return self._degraded(kind, prepared.source_id, prepared.composed)
        outcome = await self.write(prepared, vectors or [], progress=progress)
        return replace(
            outcome,
            embed_calls=max(self._embed_calls - prepared.embed_calls_before, 0),
        )

    async def embed_prepared(
        self,
        prepared: Sequence[PreparedDocument],
        *,
        progress: ProgressCb | None = None,
    ) -> WindowEmbed:
        """Embed a window of prepared documents in shared batches (plan 201 S5).

        Records are deduped by content hash across the window (identical text
        is sent once and its vector fans out), split into batches that respect
        the profile's item/token limits, and embedded through one
        ``embed_batches`` pass — one rate-limit hit, one resolution, one
        budget check and one client for the whole window. A failed batch is
        retried once, per document, so one bad text cannot poison a window and
        every failure stays attributable. ``AIBudgetExceededError`` propagates
        (the caller defers); an unassigned provider marks every document
        degraded.
        """
        result = WindowEmbed()
        if not prepared:
            return result
        space = prepared[0].space
        profile = next((doc.profile for doc in prepared if doc.profile is not None), None)
        tokenizer, _max_input, max_items, max_tokens, prefix = self._write_limits(space, profile)
        prefix_tokens = 0
        if tokenizer is not None and prefix:
            from app.ai.tokenizers import get_tokenizer_service

            counted = get_tokenizer_service().count_or_fallback(tokenizer, prefix)
            prefix_tokens = counted.tokens

        token_aware = all(doc.changed_tokens is not None for doc in prepared)

        # A document whose prepare created the space arrives with its vectors
        # already embedded — never send it again (plan 201 S5).
        for doc_index, doc in enumerate(prepared):
            if doc.precomputed is not None:
                result.vectors[doc_index] = list(doc.precomputed)

        # Flatten with hash dedupe: identical text is sent once per window.
        entries: list[tuple[int, int]] = []
        texts: list[str] = []
        counts: list[int] = []
        by_hash: dict[str, tuple[int, int]] = {}
        for doc_index, doc in enumerate(prepared):
            if doc.precomputed is not None:
                continue
            for record_index, record in enumerate(doc.changed):
                if record.content_hash in by_hash:
                    continue
                by_hash[record.content_hash] = (doc_index, record_index)
                entries.append((doc_index, record_index))
                texts.append(record.text)
                counts.append(
                    doc.changed_tokens[record_index] if doc.changed_tokens is not None else 0
                )
        if not token_aware:
            counts = [0] * len(entries)

        # Batches hold positions into ``entries``/``texts``/``counts``.
        batches: list[list[int]] = []
        current: list[int] = []
        current_tokens = 0
        for position, _entry in enumerate(entries):
            cost = counts[position] + prefix_tokens
            if current and (
                len(current) >= max_items
                or (token_aware and max_tokens is not None and current_tokens + cost > max_tokens)
            ):
                batches.append(current)
                current = []
                current_tokens = 0
            current.append(position)
            current_tokens += cost
        if current:
            batches.append(current)

        def _batch_entries(batch: list[int]) -> list[tuple[int, int]]:
            return [entries[position] for position in batch]

        def _batch_tags(batch: list[int]) -> dict[str, Any]:
            doc_indexes = {entries[position][0] for position in batch}
            if len(doc_indexes) == 1:
                return dict(prepared[next(iter(doc_indexes))].tags)
            tags: dict[str, Any] = {
                "kind": prepared[0].kind,
                "space_id": prepared[0].tags.get("space_id"),
                "phase": "batch",
                "documents": len(doc_indexes),
            }
            views = {
                prepared[doc_index].changed[record_index].view
                for doc_index, record_index in _batch_entries(batch)
            }
            if len(views) == 1:
                tags["view"] = next(iter(views))
            return tags

        from app.ai.gateway import EmbedBatch, EmbedBatchOutcome, embed_batches

        gateway_batches = [
            EmbedBatch(
                tuple(texts[position] for position in batch),
                sum(counts[position] for position in batch) if token_aware else None,
                _batch_tags(batch),
            )
            for batch in batches
        ]
        production = getattr(self._embedder, "supports_tokens", False)
        try:
            if production:
                outcomes = await embed_batches(
                    self.db,
                    gateway_batches,
                    user_id=self._user_id,
                    run=self._run,
                )
            else:
                outcomes = []
                for gateway_batch in gateway_batches:
                    try:
                        vectors = await self._embedder(list(gateway_batch.texts))
                    except Exception as exc:
                        # An injected test embedder is the provider here: a
                        # failing batch becomes an outcome so the
                        # split-on-failure pass still runs.
                        outcomes.append(
                            EmbedBatchOutcome(
                                vectors=None,
                                error=f"{type(exc).__name__}: {exc}",
                                error_exc=exc,
                                tokens_in=gateway_batch.tokens,
                            )
                        )
                        continue
                    outcomes.append(
                        EmbedBatchOutcome(
                            vectors=[list(map(float, vector)) for vector in vectors],
                            tokens_in=gateway_batch.tokens,
                        )
                    )
        except AINotConfiguredError:
            result.degraded = set(range(len(prepared)))
            return result
        result.embed_calls = len(gateway_batches)
        for doc_index in range(len(prepared)):
            carried = sum(
                1
                for batch in batches
                if any(entries[position][0] == doc_index for position in batch)
            )
            if carried:
                result.doc_embed_calls[doc_index] = carried

        # Vectors are keyed by content hash, so a deduped duplicate reuses the
        # first occurrence's vector without a second provider call.
        vector_by_hash: dict[str, list[float]] = {}
        failed_hashes: set[str] = set()
        failed_batches: list[list[int]] = []
        for batch_entries, outcome in zip(batches, outcomes, strict=True):
            if outcome.vectors is None:
                failed_hashes.update(
                    prepared[doc_index].changed[record_index].content_hash
                    for doc_index, record_index in _batch_entries(batch_entries)
                )
                failed_batches.append(batch_entries)
                continue
            for position, vector in zip(batch_entries, outcome.vectors, strict=True):
                doc_index, record_index = entries[position]
                record = prepared[doc_index].changed[record_index]
                vector_by_hash[record.content_hash] = vector

        # Split-on-failure: a failed batch is retried once, per document, so a
        # single bad text cannot poison a window and failures stay attributable.
        retried: set[int] = set()
        for failed_batch in failed_batches:
            for doc_index in {entries[position][0] for position in failed_batch}:
                if doc_index in retried:
                    continue
                retried.add(doc_index)
                doc = prepared[doc_index]
                missing = [
                    record_index
                    for record_index, record in enumerate(doc.changed)
                    if record.content_hash not in vector_by_hash
                    and record.content_hash in failed_hashes
                ]
                if not missing:
                    continue
                subset = [doc.changed[record_index] for record_index in missing]
                subset_counts = (
                    [doc.changed_tokens[record_index] for record_index in missing]
                    if doc.changed_tokens is not None
                    else None
                )
                try:
                    retry_vectors = await self._embed(
                        subset,
                        progress,
                        space=space,
                        profile=doc.profile or profile,
                        counts=subset_counts,
                    )
                except Exception as exc:
                    result.failed[doc_index] = f"{type(exc).__name__}: {exc}"
                    continue
                result.embed_calls += 1
                result.doc_embed_calls[doc_index] = result.doc_embed_calls.get(doc_index, 0) + 1
                if retry_vectors is None:
                    result.degraded.add(doc_index)
                    continue
                for record, vector in zip(subset, retry_vectors, strict=True):
                    vector_by_hash[record.content_hash] = vector

        exact = all(doc.changed_exact for doc in prepared) if token_aware else False
        result.tokens = sum(counts) if token_aware else None
        result.tokens_exact = exact
        for doc_index, doc in enumerate(prepared):
            if doc.precomputed is not None:
                continue
            row: list[list[float]] = []
            for record in doc.changed:
                record_vector: list[float] | None = vector_by_hash.get(record.content_hash)
                if record_vector is None:
                    if doc_index not in result.failed:
                        result.failed[doc_index] = "embed_failed"
                    continue
                row.append(record_vector)
            if doc_index not in result.failed and doc_index not in result.degraded:
                result.vectors[doc_index] = row
        return result

    async def _register(self, prepared: PreparedDocument) -> str:
        await self._release_sqlite_writer()
        registered = self.store.register_document(
            prepared.space,
            kind=prepared.kind,
            source_id=prepared.source_id,
            scope_type=prepared.loaded.scope_type,
            scope_id=prepared.loaded.scope_id,
            profile_id=prepared.loaded.profile_id,
            source_hash=prepared.composed.source_hash,
            schema_version=int(COMPOSER_VERSION),
        )
        return registered.document_id

    def _degraded(
        self,
        kind: str,
        source_id: str,
        composed: ComposedDocument,
        reason: DegradedReason = DegradedReason.PROVIDER_UNASSIGNED,
    ) -> IndexOutcome:
        return IndexOutcome(
            kind=kind,
            source_id=source_id,
            space=self.space_name,
            scanned=len(composed.records),
            degraded=reason.value,
        )

    def _failed(
        self,
        kind: str,
        source_id: str,
        composed: ComposedDocument,
        error: Exception,
        *,
        reason: str | None = None,
    ) -> IndexOutcome:
        """A bounded, retry-safe write failure (never a truncation or loop)."""
        return IndexOutcome(
            kind=kind,
            source_id=source_id,
            space=self.space_name,
            scanned=len(composed.records),
            failed=1,
            failed_reason=reason or getattr(error, "reason", "write_failed"),
        )

    def _ensure_index(self, space: VectorSpace) -> VectorSpace | None:
        """Heal an active space that has no usable physical index.

        An existing space can carry ``index_table=None`` after a failed or
        legacy provision (or a desktop install that gained sqlite-vec later).
        The first write is the last chance to fix it off the request path:
        re-provision idempotently and continue with the refreshed handle, or
        report ``index_missing`` instead of writing into nothing and failing
        every retry forever.

        A verified space is remembered for the life of this service, so a
        reconcile pass probes once per space instead of once per document.
        """
        key = f"{space.space_id}:{space.index_table}"
        if key in self._verified_spaces:
            return space
        needs_provision = space.index_table is None and self.store.backend.name != BACKEND_LINEAR
        if not needs_provision:
            try:
                self.store.ensure_space(space)
                self._verified_spaces.add(key)
                return space
            except VectorIndexMissing:
                needs_provision = True
        if not needs_provision:
            return space
        try:
            with self.store.session_factory() as session:
                row = session.get(VectorSpaceRow, uuid.UUID(str(space.space_id)))
                if row is None:  # pragma: no cover - the space was just resolved
                    return None
                provision_space(
                    session, row, backend=self._provision_backend or self.store.backend.name
                )
                session.refresh(row)
            healed = self.store.resolve_space(str(row.id))
            self.store.ensure_space(healed)
            self._verified_spaces.add(f"{healed.space_id}:{healed.index_table}")
            return healed
        except Exception:  # a broken provision is a degraded write, not a crash
            logger.warning(
                "vector space %r could not be provisioned", self.space_name, exc_info=True
            )
            return None

    async def _resolve_profile(self) -> EmbeddingProfile | None:
        if self._profile is not None:
            return self._profile
        from app.ai.providers.resolution import resolve_task_model

        resolved = await resolve_task_model(self.db, "embed", self._user_id)
        if resolved is None:
            return None
        return await self._effective_profile(resolved.provider_type, resolved.model_name)

    async def _effective_profile(self, provider: str, model: str) -> EmbeddingProfile:
        """Resolve the **effective** profile (admin override included) from the DB.

        The code-only registry is only the last-resort fallback when the DB
        lookup itself fails; a write/build path must see the same tokenizer
        and limits the admin saved.
        """
        from app.services import embedding_profiles

        try:
            resolved = await embedding_profiles.resolve_for(self.db, provider, model)
            return EmbeddingProfile(
                provider=provider,
                model=model,
                tokenizer=resolved.tokenizer,
                chunk=resolved.chunk,
                batch_max_items=resolved.batch_max_items,
                batch_max_tokens=resolved.batch_max_tokens,
            )
        except Exception:
            logger.warning(
                "embedding profile DB resolution failed for %s/%s", provider, model, exc_info=True
            )
            from app.ai.tokenizers import resolve_embedding_profile

            fallback = resolve_embedding_profile(provider, model)
            return EmbeddingProfile(
                provider=provider,
                model=model,
                tokenizer=fallback.tokenizer,
                chunk=fallback.chunk,
                batch_max_items=fallback.batch_max_items,
                batch_max_tokens=fallback.batch_max_tokens,
            )

    def _find_space(self) -> VectorSpace | None:
        try:
            if self.space_id is not None:
                return self.store.resolve_space(self.space_id)
            return self.store.active_space(self.space_name)
        except VectorSpaceNotFound:
            return None

    async def _create_space(
        self,
        composed: ComposedDocument,
        profile: EmbeddingProfile,
        progress: ProgressCb | None,
    ) -> tuple[VectorSpace | None, list[list[float]] | None]:
        await self._report(progress, 20, "creating space")
        vectors = await self._embed(composed.records, progress, space=None, profile=profile)
        if not vectors:
            return None, None
        space = self.store.create_space(
            name=self.space_name,
            provider=profile.provider,
            model=profile.model,
            dim=len(vectors[0]),
            normalize=profile.normalize,
            query_prefix=profile.query_prefix,
            document_prefix=profile.document_prefix,
            chunker_version=CHUNKER_VERSION,
            composer_version=COMPOSER_VERSION,
        )
        with self.store.session_factory() as session:
            row = session.get(VectorSpaceRow, uuid.UUID(str(space.space_id)))
            if row is None:  # pragma: no cover - create_space just wrote it
                raise RuntimeError(f"space {self.space_name!r} vanished after creation")
            provision_space(
                session, row, backend=self._provision_backend or self.store.backend.name
            )
        return self.store.resolve_space(str(space.space_id)), vectors

    def _write_limits(
        self, space: VectorSpace | None, profile: EmbeddingProfile | None
    ) -> tuple[TokenizerSpec | None, int | None, int, int | None, str | None]:
        """The tokenizer, per-item input limit and per-request batch budget."""
        tokenizer = (
            cast(TokenizerSpec, space.tokenizer)
            if space is not None and space.token_aware
            else (profile.tokenizer if profile is not None else None)
        )
        max_input = tokenizer.max_input_tokens if tokenizer is not None else None
        max_items = profile.batch_max_items if profile is not None else EMBED_BATCH_SIZE
        max_tokens = profile.batch_max_tokens if profile is not None else None
        prefix = space.document_prefix if space is not None else None
        if prefix is None and profile is not None:
            prefix = profile.document_prefix
        return tokenizer, max_input, max(int(max_items), 1), max_tokens, prefix

    async def _embed(
        self,
        records: Sequence[Any],
        progress: ProgressCb | None,
        *,
        space: VectorSpace | None = None,
        profile: EmbeddingProfile | None = None,
        counts: list[int] | None = None,
    ) -> list[list[float]] | None:
        """Embed in batches split by **both** item count and token sum.

        The per-item ``max_input_tokens`` budget (prefix + safety margin
        included) is checked first and surfaces :class:`InputTooLong`; the
        per-request ``batch_max_items``/``batch_max_tokens`` budget then only
        decides where a batch ends. ``None`` means no provider is assigned.
        """
        if not records:
            return []
        tokenizer, _max_input, max_items, max_tokens, _prefix = self._write_limits(space, profile)
        counts, _exact, prefix_tokens = self._record_counts(space, profile, records)

        batches: list[list[Any]] = []
        batch_tokens: list[int | None] = []
        count_by_id = (
            {id(record): count for record, count in zip(records, counts, strict=True)}
            if counts
            else {}
        )
        if counts and tokenizer is not None:
            current: list[Any] = []
            current_tokens = 0
            for record, count in zip(records, counts, strict=True):
                cost = count + prefix_tokens
                if current and (
                    len(current) >= max_items
                    or (max_tokens is not None and current_tokens + cost > max_tokens)
                ):
                    batches.append(current)
                    current = []
                    current_tokens = 0
                current.append(record)
                current_tokens += cost
            if current:
                batches.append(current)
        else:
            batches = [
                list(records[start : start + max_items])
                for start in range(0, len(records), max_items)
            ]
        for batch in batches:
            if counts and tokenizer is not None:
                batch_tokens.append(sum(count_by_id[id(record)] for record in batch))
            else:
                batch_tokens.append(None)

        vectors: list[list[float]] = []
        total = max(len(records), 1)
        done = 0
        try:
            if getattr(self._embedder, "supports_tokens", False):
                from app.ai.gateway import EmbedBatch, embed_batches

                batch_texts = [[record.text for record in batch] for batch in batches]
                outcomes = await embed_batches(
                    self.db,
                    [
                        EmbedBatch(tuple(texts), tokens, dict(self._tags))
                        for texts, tokens in zip(batch_texts, batch_tokens, strict=True)
                    ],
                    user_id=self._user_id,
                    run=self._run,
                )
                for texts, outcome in zip(batch_texts, outcomes, strict=True):
                    if outcome.vectors is None:
                        if isinstance(outcome.error_exc, AINotConfiguredError):
                            return None
                        raise outcome.error_exc or RuntimeError(outcome.error or "embed failed")
                    vectors.extend(outcome.vectors)
                    self._embed_calls += 1
                    done += len(texts)
                    await self._report(
                        progress,
                        min(70, 20 + int(50 * done / total)),
                        "embedding",
                    )
            else:
                for batch in batches:
                    texts = [record.text for record in batch]
                    vectors.extend(await self._embedder(texts))
                    self._embed_calls += 1
                    done += len(batch)
                    await self._report(
                        progress,
                        min(70, 20 + int(50 * done / total)),
                        "embedding",
                    )
        except AINotConfiguredError:
            return None
        return vectors

    def _record_counts(
        self,
        space: VectorSpace | None,
        profile: EmbeddingProfile | None,
        records: Sequence[Any],
    ) -> tuple[list[int] | None, bool, int]:
        """Per-record token counts for batching and audit (plan 201 S1).

        ``(counts, exact, prefix_tokens)``; ``counts is None`` when no
        tokenizer is known — the audit row stays ``None`` rather than guessing.
        Never raises: a counting failure degrades to uncounted.
        """
        try:
            from app.ai.tokenizers import get_tokenizer_service

            tokenizer, _max_input, _max_items, _max_tokens, prefix = self._write_limits(
                space, profile
            )
            if tokenizer is None or not records:
                return None, False, 0
            service = get_tokenizer_service()
            counted_prefix = service.count_or_fallback(tokenizer, prefix) if prefix else None
            prefix_tokens = counted_prefix.tokens if counted_prefix is not None else 0
            effective, _degraded = service.effective_spec(tokenizer)
            counts: list[int] = []
            exact = True
            for record in records:
                if getattr(record, "token_count", None) is not None:
                    counts.append(int(record.token_count))
                    exact = exact and effective.exact
                else:
                    counted = service.count_or_fallback(tokenizer, record.text)
                    counts.append(counted.tokens)
                    exact = exact and counted.exact
            return counts, exact, prefix_tokens
        except Exception:
            logger.warning(
                "token counting unavailable for space %r", self.space_name, exc_info=True
            )
            return None, False, 0

    @staticmethod
    async def _report(progress: ProgressCb | None, value: int, stage: str) -> None:
        if progress is not None:
            await progress(value, stage)


__all__ = [
    "CONTENT_SPACE",
    "EMBED_BATCH_SIZE",
    "EmbeddingProfile",
    "IndexOutcome",
    "LoadedSource",
    "SourceRow",
    "VectorIndexService",
    "count_sources",
    "gateway_embedder",
    "list_sources",
    "load_source",
    "record_id_for",
]
