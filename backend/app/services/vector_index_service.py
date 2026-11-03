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

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AINotConfiguredError
from app.models.enums.retrieval import VectorScopeType
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services.vector_composers import (
    CHUNKER_VERSION,
    COMPOSER_VERSION,
    ComposedDocument,
    compose_posting_views,
    compose_profile_views,
    compose_skill_views,
)
from app.storage.vector_backends import ResolvedEmbedding, VectorSpaceNotFound
from app.storage.vector_contract import DegradedReason, IndexRecord, VectorSpace
from app.storage.vector_provisioning import provision_space
from app.storage.vector_store import TextRef, VectorStoreService

CONTENT_SPACE = "content"
EMBED_BATCH_SIZE = 64

VECTOR_RECORD_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://neuronection.local/career/vector-record"
)

ProgressCb = Callable[[int, str], Awaitable[None]]
Embedder = Callable[[Sequence[str]], Awaitable[list[list[float]]]]


@dataclass(frozen=True)
class EmbeddingProfile:
    """The resolved embedding configuration a write is about to use."""

    provider: str
    model: str
    normalize: bool = True
    query_prefix: str | None = None
    document_prefix: str | None = None

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
            "failed": 0,
            "failed_ids": [],
            "failed_ids_truncated": False,
            "gate": None,
            "degraded": self.degraded,
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


def gateway_embedder(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    run: Any = None,
) -> Embedder:
    """The production embedder: every batch through the gateway ``embed`` task."""

    async def _embed(texts: Sequence[str]) -> list[list[float]]:
        from app.ai.gateway import embed_texts

        return await embed_texts(db, list(texts), user_id=user_id, run=run)

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
    "skill": _load_skill,
    "profile": _load_profile,
}


async def load_source(db: AsyncSession, kind: str, source_id: str) -> LoadedSource | None:
    """Load and compose one source row; ``None`` when it no longer exists."""
    loader = _LOADERS.get(kind)
    if loader is None:
        raise ValueError(f"kind {kind!r} has no vector composer in P1c")
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
        self._embedder = embedder or gateway_embedder(db, user_id=user_id, run=run)
        self._profile = profile
        self._provision_backend = provision_backend
        self._user_id = user_id

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

    async def index_composed(
        self,
        loaded: LoadedSource,
        *,
        kind: str,
        source_id: str,
        force: bool = False,
        progress: ProgressCb | None = None,
    ) -> IndexOutcome:
        """The pipeline proper: an already-composed document in, outcome out."""
        composed = loaded.composed
        if composed.is_empty:
            return IndexOutcome(kind=kind, source_id=source_id, space=self.space_name)
        await self._report(progress, 10, "composing")
        profile: EmbeddingProfile | None = None
        space: VectorSpace | None = self._find_space()
        precomputed: list[list[float]] | None = None
        if space is None:
            profile = await self._resolve_profile()
            if profile is None:
                return self._degraded(kind, source_id, composed)
            space, precomputed = await self._create_space(composed, profile, progress)
            if space is None:
                return self._degraded(kind, source_id, composed)

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
        vectors = precomputed
        if vectors is None and changed:
            await self._report(progress, 40, f"embedding {len(changed)} record(s)")
            if profile is None:
                profile = await self._resolve_profile()
            if profile is None:
                return self._degraded(kind, source_id, composed)
            vectors = await self._embed([record.text for record in changed], progress)
            if vectors is None:
                return self._degraded(kind, source_id, composed)
        if vectors is not None and len(vectors) != len(changed):
            raise RuntimeError(
                f"embedder returned {len(vectors)} vector(s) for {len(changed)} text(s)"
            )
        vectors = vectors or []

        registered = self.store.register_document(
            space,
            kind=kind,
            source_id=source_id,
            scope_type=loaded.scope_type,
            scope_id=loaded.scope_id,
            profile_id=loaded.profile_id,
            source_hash=composed.source_hash,
            schema_version=int(COMPOSER_VERSION),
        )
        document_id = registered.document_id
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
                space,
                document_id=document_id,
                records=index_records,
                resolved=(
                    profile.to_resolved(len(index_records[0].embedding))
                    if profile is not None
                    else None
                ),
                text_refs=text_refs,
                prune=False,
            )
            written = indexed.written
        pruned = self.store.prune_records(
            space,
            document_id=document_id,
            keep_keys=[record.key for record in composed.records],
        )
        await self._report(progress, 100, "indexed")
        return IndexOutcome(
            kind=kind,
            source_id=source_id,
            space=space.name,
            document_id=document_id,
            scanned=len(composed.records),
            embedded=len(index_records),
            skipped=len(composed.records) - len(changed),
            written=written,
            pruned=pruned,
        )

    def _degraded(self, kind: str, source_id: str, composed: ComposedDocument) -> IndexOutcome:
        return IndexOutcome(
            kind=kind,
            source_id=source_id,
            space=self.space_name,
            scanned=len(composed.records),
            degraded=DegradedReason.PROVIDER_UNASSIGNED.value,
        )

    async def _resolve_profile(self) -> EmbeddingProfile | None:
        if self._profile is not None:
            return self._profile
        from app.ai.providers.resolution import resolve_task_model

        resolved = await resolve_task_model(self.db, "embed", self._user_id)
        if resolved is None:
            return None
        return EmbeddingProfile(provider=resolved.provider_type, model=resolved.model_name)

    def _find_space(self) -> VectorSpace | None:
        try:
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
        vectors = await self._embed([record.text for record in composed.records], progress)
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
            provision_space(session, row, backend=self._provision_backend)
        return self.store.resolve_space(str(space.space_id)), vectors

    async def _embed(
        self, texts: Sequence[str], progress: ProgressCb | None
    ) -> list[list[float]] | None:
        """Embed in gateway-sized batches; ``None`` when no provider is assigned."""
        vectors: list[list[float]] = []
        total = max(len(texts), 1)
        try:
            for start in range(0, len(texts), EMBED_BATCH_SIZE):
                batch = list(texts[start : start + EMBED_BATCH_SIZE])
                vectors.extend(await self._embedder(batch))
                await self._report(
                    progress,
                    min(70, 20 + int(50 * (start + len(batch)) / total)),
                    "embedding",
                )
        except AINotConfiguredError:
            return None
        return vectors

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
    "VectorIndexService",
    "gateway_embedder",
    "load_source",
    "record_id_for",
]
