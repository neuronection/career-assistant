"""The metadata-owning vector store service (plan 50 §3, §4, P1b).

One seam owns the portable metadata — ``vector_spaces``,
``vector_documents`` and ``vector_records`` — plus the content-hash and
dimension guards, document registration, deletion and the orphan sweep. The
physical index belongs to a :class:`VectorBackend`; the service passes the
same session into the backend's index hooks so metadata and index rows for
one document commit atomically.

This module never issues DDL. Provisioning is
:mod:`app.storage.vector_provisioning` (a migration or the P1c index job).
Records carry their source pointer (``TextRef``) and the write path is
two-step for incremental workers: ``upsert_document(..., prune=False)`` for
the changed records, then ``prune_records`` for the keys that no longer
compose. Call-site cutover remains P1d.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.enums.retrieval import VectorScopeType
from app.models.vector_model import (
    VectorDocument,
    VectorRecord,
    chunk_config_from_columns,
    tokenizer_spec_from_columns,
)
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.storage.tokenizer_contract import ChunkConfig, TokenizerSpec
from app.storage.vector_backends import (
    ResolvedEmbedding,
    SessionBackedBackend,
    VectorBackendError,
    VectorDocumentNotFound,
    VectorRecordIdentityMismatch,
    VectorSpaceMismatch,
    VectorSpaceNotFound,
    assert_writer_matches_space,
    get_backend,
    writer_mismatch_reason,
)
from app.storage.vector_contract import (
    V1_VIEWS,
    BackendHealth,
    IndexHit,
    IndexRecord,
    ScopeSpec,
    SpaceStatus,
    VectorSpace,
)
from app.storage.vector_contract import space_key as make_space_key
from app.storage.vector_contract import space_key_v2 as make_space_key_v2


@dataclass(frozen=True)
class RegisteredDocument:
    """The metadata handle a composer/worker writes records against."""

    document_id: str
    created: bool
    source_hash: str


@dataclass(frozen=True)
class IndexedDocument:
    """The outcome of one document upsert."""

    document_id: str
    records: int
    written: int
    removed: int = 0


@dataclass(frozen=True)
class TextRef:
    """A pointer at the source text of one record — never a copy of it.

    Kept service-local on purpose: the vendored family contract's
    ``IndexRecord`` stays a pure index DTO, and provenance is a product
    concern (the contract only says records carry a reference).
    """

    ref: dict[str, str]
    schema_version: int | None = None


@dataclass(frozen=True)
class DocumentInfo:
    """The product-facing identity of one indexed document (read path)."""

    document_id: str
    kind: str
    source_id: str
    scope_type: str
    scope_id: str | None = None
    profile_id: str | None = None


@dataclass(frozen=True)
class StoredVector:
    """One stored record vector, for using a document as the query."""

    record_id: str
    view: str
    chunk_index: int
    vector: tuple[float, ...]


def _make_sessionmaker(bind: Engine | sessionmaker[Session]) -> sessionmaker[Session]:
    return sessionmaker(bind=bind, expire_on_commit=False) if isinstance(bind, Engine) else bind


def canonical_source_id(value: str) -> str:
    """Canonicalize a source id once: UUID-backed sources are hyphenated lowercase."""
    raw = str(value).strip()
    try:
        return str(uuid.UUID(raw))
    except (TypeError, ValueError):
        return raw


def resolve_space_row(
    session: Session, space: VectorSpace | VectorSpaceRow | uuid.UUID | str
) -> VectorSpaceRow:
    """The persisted row is the only trusted model/dim configuration."""
    if isinstance(space, VectorSpaceRow):
        row = session.get(VectorSpaceRow, space.id)
    elif isinstance(space, VectorSpace):
        if space.space_id is not None:
            row = session.get(VectorSpaceRow, uuid.UUID(str(space.space_id)))
        else:
            row = session.scalars(
                select(VectorSpaceRow)
                .where(
                    VectorSpaceRow.name == space.name,
                    VectorSpaceRow.status == str(space.status),
                )
                .order_by(VectorSpaceRow.created_at.desc())
                .limit(1)
            ).first()
    else:
        row = session.get(VectorSpaceRow, uuid.UUID(str(space)))
    if row is None:
        raise VectorSpaceNotFound(f"vector space {space!r} has no persisted row")
    return row


def _row_columns(row: VectorSpaceRow) -> dict:
    return {
        "tokenizer_kind": row.tokenizer_kind,
        "tokenizer_identifier": row.tokenizer_identifier,
        "tokenizer_revision": row.tokenizer_revision,
        "tokenizer_artifact_sha256": row.tokenizer_artifact_sha256,
        "tokenizer_exact": row.tokenizer_exact,
        "tokenizer_source": row.tokenizer_source,
        "max_input_tokens": row.max_input_tokens,
        "chunk_max_tokens": row.chunk_max_tokens,
        "chunk_overlap_tokens": row.chunk_overlap_tokens,
        "chunk_max_chars": row.chunk_max_chars,
    }


def canonical_space(row: VectorSpaceRow) -> VectorSpace:
    """Build the contract DTO from the persisted row (index_table included).

    The tokenizer/chunk are reconstructed from the stored scalars; the key is
    the stored ``space_key`` verbatim and is never recomputed here.
    """
    columns = _row_columns(row)
    return VectorSpace(
        name=row.name,
        provider=row.provider,
        model=row.model,
        dim=row.dim,
        metric=row.metric,
        normalize=row.normalize,
        query_prefix=row.query_prefix,
        document_prefix=row.document_prefix,
        chunker_version=row.chunker_version,
        composer_version=row.composer_version,
        status=SpaceStatus(row.status),
        space_id=str(row.id),
        index_table=row.index_table,
        stored_key=row.space_key,
        tokenizer=tokenizer_spec_from_columns(columns),
        chunk=chunk_config_from_columns(columns),
    )


def _assert_chunk_fits(
    tokenizer: TokenizerSpec, chunk: ChunkConfig, document_prefix: str | None
) -> None:
    """Refuse a creation whose chunk budget cannot fit the model input.

    The document prefix and the same safety margin the composer uses are
    counted with the selected tokenizer; a missing exact asset degrades to the
    conservative heuristic for this check instead of blocking a build.
    """
    from app.ai.tokenizers import get_tokenizer_service
    from app.services.vector_composers import TOKEN_SAFETY_MARGIN

    prefix_tokens = 0
    if document_prefix:
        counted = get_tokenizer_service().count_or_fallback(tokenizer, document_prefix)
        prefix_tokens = counted.tokens
    chunk.assert_fits(
        tokenizer.max_input_tokens,
        prefix_tokens=prefix_tokens,
        safety_margin=TOKEN_SAFETY_MARGIN,
    )


def _assert_dto_matches_row(space: VectorSpace, row: VectorSpaceRow) -> None:
    reason = writer_mismatch_reason(
        space,
        ResolvedEmbedding(
            provider=row.provider,
            model=row.model,
            dim=row.dim,
            normalize=row.normalize,
            query_prefix=row.query_prefix,
            document_prefix=row.document_prefix,
        ),
    )
    if reason is not None:
        raise VectorSpaceMismatch(f"space DTO disagrees with the persisted row — {reason}")
    if space.key != row.space_key:
        raise VectorSpaceMismatch(
            "space key identity disagrees with the persisted row — "
            f"dto={space.key!r}, row={row.space_key!r}"
        )
    if row.status != str(space.status):
        raise VectorSpaceMismatch(
            f"space status mismatch — row={row.status!r}, dto={str(space.status)!r}"
        )
    if space.index_table is not None and space.index_table != row.index_table:
        raise VectorSpaceMismatch(
            f"space index_table mismatch — row={row.index_table!r}, dto={space.index_table!r}"
        )


class VectorStoreService:
    """Own the vector metadata and delegate the physical index to a backend."""

    def __init__(
        self,
        bind: Engine | sessionmaker[Session],
        backend: SessionBackedBackend | None = None,
    ) -> None:
        self._session_factory = _make_sessionmaker(bind)
        if backend is None:
            engine = bind if isinstance(bind, Engine) else bind.kw.get("bind")
            if not isinstance(engine, Engine):
                raise ValueError(
                    "VectorStoreService needs an Engine or a sessionmaker bound to one"
                )
            backend = cast(SessionBackedBackend, get_backend(engine))
        self._backend = backend

    @property
    def backend(self) -> SessionBackedBackend:
        return self._backend

    @property
    def session_factory(self) -> sessionmaker[Session]:
        """The store's session factory — for the provisioning/job seam only."""
        return self._session_factory

    def create_space(
        self,
        *,
        name: str,
        provider: str,
        model: str,
        dim: int,
        normalize: bool = True,
        query_prefix: str | None = None,
        document_prefix: str | None = None,
        chunker_version: str = "1",
        composer_version: str = "1",
        status: SpaceStatus = SpaceStatus.ACTIVE,
        tokenizer: TokenizerSpec | None = None,
        chunk: ChunkConfig | None = None,
    ) -> VectorSpace:
        """Get-or-create a space for ``name`` with this configuration.

        An ``active`` create returns a matching active space as-is; a
        different configuration raises :class:`VectorSpaceMismatch` (a
        model/dim change is a new ``building`` space and a cutover, never an
        in-place rewrite). A ``building`` create is idempotent for the same
        configuration and never touches the active pointer; a second
        *different* building space for the same name is refused (at most one
        active + one building per name). The physical index is *not* created
        here — provisioning owns DDL.

        A token-aware space passes **both** ``tokenizer`` and ``chunk``: the
        row persists the flattened identity, ``chunker_version`` is forced to
        ``'2'`` and the key is the explicit :func:`space_key_v2` pre-image.
        Omitting both keeps the legacy v1 behaviour; passing only one is a
        programming error, never a half-configured row.
        """
        if dim < 1:
            raise ValueError("dim must be positive")
        if (tokenizer is None) != (chunk is None):
            raise ValueError("tokenizer and chunk must be provided together")
        resolved = ResolvedEmbedding(
            provider=provider,
            model=model,
            dim=dim,
            normalize=normalize,
            query_prefix=query_prefix,
            document_prefix=document_prefix,
        )
        columns: dict = {}
        if tokenizer is not None and chunk is not None:
            chunker_version = "2"
            _assert_chunk_fits(tokenizer, chunk, document_prefix)
            columns = {
                "tokenizer_kind": tokenizer.kind.value,
                "tokenizer_identifier": tokenizer.identifier,
                "tokenizer_revision": tokenizer.revision,
                "tokenizer_artifact_sha256": tokenizer.artifact_sha256,
                "tokenizer_exact": tokenizer.exact,
                "tokenizer_source": tokenizer.source.value,
                "max_input_tokens": tokenizer.max_input_tokens,
                "chunk_max_tokens": chunk.max_chunk_tokens,
                "chunk_overlap_tokens": chunk.overlap_tokens,
                "chunk_max_chars": chunk.max_chars,
            }
            computed_key = make_space_key_v2(
                provider,
                model,
                dim,
                normalize,
                query_prefix,
                document_prefix,
                chunker_version,
                composer_version,
                tokenizer=tokenizer,
                chunk=chunk,
            )
        else:
            computed_key = make_space_key(
                provider,
                model,
                dim,
                normalize,
                query_prefix,
                document_prefix,
                chunker_version,
                composer_version,
            )
        with self._session_factory() as session:
            existing_rows = list(
                session.scalars(
                    select(VectorSpaceRow)
                    .where(
                        VectorSpaceRow.name == name,
                        VectorSpaceRow.status == status.value,
                    )
                    .order_by(VectorSpaceRow.created_at.desc())
                )
            )
            matching = next(
                (candidate for candidate in existing_rows if candidate.space_key == computed_key),
                None,
            )
            if status is SpaceStatus.ACTIVE:
                if matching is not None:
                    mismatch = writer_mismatch_reason(canonical_space(matching), resolved)
                    if mismatch is not None:
                        raise VectorSpaceMismatch(
                            f"active space {name!r} has a different configuration — {mismatch}"
                        )
                    return canonical_space(matching)
                if existing_rows:
                    raise VectorSpaceMismatch(
                        f"active space {name!r} has a different stored identity — "
                        f"row={existing_rows[0].space_key!r}, requested={computed_key!r}"
                    )
            elif matching is not None:
                mismatch = writer_mismatch_reason(canonical_space(matching), resolved)
                if mismatch is not None:
                    raise VectorSpaceMismatch(
                        f"building space {name!r} has a different configuration — {mismatch}"
                    )
                return canonical_space(matching)
            elif existing_rows:
                raise VectorSpaceMismatch(
                    f"a different {status.value} space named {name!r} already exists; "
                    "retire or drop it before building another"
                )
            row = VectorSpaceRow(
                name=name,
                provider=provider,
                model=model,
                dim=dim,
                normalize=normalize,
                query_prefix=query_prefix,
                document_prefix=document_prefix,
                chunker_version=chunker_version,
                composer_version=composer_version,
                status=status.value,
                space_key=computed_key,
                **columns,
            )
            session.add(row)
            session.commit()
            return canonical_space(row)

    def resolve_space(self, space: VectorSpace | uuid.UUID | str) -> VectorSpace:
        """Validate an optional DTO against the persisted row and return it."""
        with self._session_factory() as session:
            row = resolve_space_row(session, space)
            if isinstance(space, VectorSpace):
                _assert_dto_matches_row(space, row)
            return canonical_space(row)

    def active_space(self, name: str) -> VectorSpace:
        """Resolve the one ``active`` space for a name (the read-path pointer)."""
        with self._session_factory() as session:
            row = session.scalars(
                select(VectorSpaceRow)
                .where(
                    VectorSpaceRow.name == name,
                    VectorSpaceRow.status == SpaceStatus.ACTIVE.value,
                )
                .order_by(VectorSpaceRow.created_at.desc())
                .limit(1)
            ).first()
            if row is None:
                raise VectorSpaceNotFound(f"no active vector space named {name!r}")
            return canonical_space(row)

    def ensure_space(self, space: VectorSpace | uuid.UUID | str) -> VectorSpace:
        canonical = self.resolve_space(space)
        self._backend.ensure_space(canonical)
        return canonical

    def register_document(
        self,
        space: VectorSpace | uuid.UUID | str,
        *,
        kind: str,
        source_id: str,
        scope_type: str,
        source_hash: str,
        schema_version: int,
        scope_id: uuid.UUID | str | None = None,
        profile_id: uuid.UUID | str | None = None,
    ) -> RegisteredDocument:
        """Create or refresh the document row; returns its stable id."""
        if scope_type not in {member.value for member in VectorScopeType}:
            raise ValueError(f"unknown scope_type: {scope_type!r}")
        if not kind or not source_id:
            raise ValueError("kind and source_id are required")
        canonical_source = canonical_source_id(source_id)
        with self._session_factory() as session:
            row = resolve_space_row(session, space)
            document = session.scalars(
                select(VectorDocument).where(
                    VectorDocument.space_id == row.id,
                    VectorDocument.kind == kind,
                    VectorDocument.source_id == canonical_source,
                )
            ).first()
            created = document is None
            if document is None:
                document = VectorDocument(
                    space_id=row.id,
                    kind=kind,
                    source_id=canonical_source,
                    scope_type=scope_type,
                    scope_id=uuid.UUID(str(scope_id)) if scope_id is not None else None,
                    profile_id=uuid.UUID(str(profile_id)) if profile_id is not None else None,
                    source_hash=source_hash,
                    schema_version=schema_version,
                )
                session.add(document)
            else:
                document.scope_type = scope_type
                document.scope_id = uuid.UUID(str(scope_id)) if scope_id is not None else None
                document.profile_id = uuid.UUID(str(profile_id)) if profile_id is not None else None
                document.source_hash = source_hash
                document.schema_version = schema_version
            session.flush()
            document_id = str(document.id)
            session.commit()
        return RegisteredDocument(document_id=document_id, created=created, source_hash=source_hash)

    def find_document(
        self,
        space: VectorSpace | uuid.UUID | str,
        *,
        kind: str,
        source_id: str,
    ) -> str | None:
        """The registered document id for a source, or ``None`` when absent.

        The index worker needs the id to compare content hashes *before* it
        embeds; registering only after a successful embed keeps a degraded
        run from advancing the document's ``source_hash``.
        """
        canonical = self.resolve_space(space)
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            found = session.scalars(
                select(VectorDocument.id).where(
                    VectorDocument.space_id == row.id,
                    VectorDocument.kind == kind,
                    VectorDocument.source_id == canonical_source_id(source_id),
                )
            ).first()
            return str(found) if found is not None else None

    def _validate_records(
        self, space: VectorSpace, document_id: uuid.UUID, records: Sequence[IndexRecord]
    ) -> None:
        seen: set[tuple[str, int]] = set()
        for record in records:
            if uuid.UUID(str(record.document_id)) != document_id:
                raise VectorBackendError(
                    f"record {record.record_id} belongs to document {record.document_id}, "
                    f"not {document_id}"
                )
            if len(record.embedding) != space.dim:
                raise VectorSpaceMismatch(
                    f"record {record.record_id} has dim {len(record.embedding)}, "
                    f"space {space.name!r} expects {space.dim}"
                )
            if record.view not in V1_VIEWS:
                raise VectorBackendError(f"unknown view {record.view!r}")
            if space.token_aware and record.token_count is None:
                raise VectorBackendError(
                    f"record {record.record_id} has no token offsets for a token-aware space"
                )
            if not space.token_aware and record.token_count is not None:
                raise VectorBackendError(
                    f"record {record.record_id} carries token offsets for a legacy space"
                )
            key = (record.view, record.chunk_index)
            if key in seen:
                raise VectorBackendError(f"duplicate record key {key!r} in one document upsert")
            seen.add(key)

    def upsert_document(
        self,
        space: VectorSpace | uuid.UUID | str,
        *,
        document_id: uuid.UUID | str,
        records: Sequence[IndexRecord],
        resolved: ResolvedEmbedding | None = None,
        text_refs: Mapping[tuple[str, int], TextRef] | None = None,
        prune: bool = True,
    ) -> IndexedDocument:
        """Write metadata + physical index rows for one document atomically.

        Semantics — a worker writing only the records whose content changed
        must pass ``prune=False`` (the default is authoritative: keys absent
        from ``records`` are deleted from metadata *and* the physical index).
        Call :meth:`prune_records` afterwards with the full composed key set
        to drop keys that no longer exist; that two-step write never deletes
        a record it did not re-embed.

        ``text_refs`` maps a record key ``(view, chunk_index)`` to its source
        pointer. When supplied it is authoritative for this write — a key
        with no entry stores no pointer; when omitted, an existing pointer
        is left untouched and a new record stores none.
        """
        canonical = self.resolve_space(space)
        if resolved is not None:
            assert_writer_matches_space(canonical, resolved)
        document_uuid = uuid.UUID(str(document_id))
        self._validate_records(canonical, document_uuid, records)
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            document = session.scalars(
                select(VectorDocument).where(
                    VectorDocument.id == document_uuid,
                    VectorDocument.space_id == row.id,
                )
            ).first()
            if document is None:
                raise VectorDocumentNotFound(
                    f"document {document_uuid} is not registered in space {canonical.name!r}"
                )
            existing = {
                (record.view, record.chunk_index): record
                for record in session.scalars(
                    select(VectorRecord).where(VectorRecord.document_id == document_uuid)
                )
            }
            new_keys = {(record.view, record.chunk_index) for record in records}
            stale_ids = (
                [stored.id for key, stored in existing.items() if key not in new_keys]
                if prune
                else []
            )
            if stale_ids:
                self._backend.delete_record_ids_index(session, canonical, stale_ids)
                session.execute(delete(VectorRecord).where(VectorRecord.id.in_(stale_ids)))
            written = 0
            for record in records:
                key = (record.view, record.chunk_index)
                stored = existing.get(key)
                record_uuid = uuid.UUID(str(record.record_id))
                pointer = text_refs.get(key) if text_refs is not None else None
                if stored is None:
                    session.add(
                        VectorRecord(
                            id=record_uuid,
                            document_id=document_uuid,
                            space_id=row.id,
                            view=record.view,
                            chunk_index=record.chunk_index,
                            char_start=record.char_start,
                            char_end=record.char_end,
                            token_count=record.token_count,
                            token_start=record.token_start,
                            token_end=record.token_end,
                            content_hash=record.content_hash,
                            text_ref=dict(pointer.ref) if pointer is not None else None,
                            text_ref_schema_version=(
                                pointer.schema_version if pointer is not None else None
                            ),
                        )
                    )
                else:
                    if stored.id != record_uuid:
                        raise VectorRecordIdentityMismatch(
                            "record identity changed for "
                            f"({document_uuid}, {record.view}, {record.chunk_index})"
                        )
                    stored.char_start = record.char_start
                    stored.char_end = record.char_end
                    stored.token_count = record.token_count
                    stored.token_start = record.token_start
                    stored.token_end = record.token_end
                    stored.content_hash = record.content_hash
                    if text_refs is not None:
                        stored.text_ref = dict(pointer.ref) if pointer is not None else None
                        stored.text_ref_schema_version = (
                            pointer.schema_version if pointer is not None else None
                        )
                written += 1
            session.flush()
            self._backend.upsert_index(session, canonical, records)
            session.commit()
        return IndexedDocument(
            document_id=str(document_uuid),
            records=len(records),
            written=written,
            removed=len(stale_ids),
        )

    def prune_records(
        self,
        space: VectorSpace | uuid.UUID | str,
        *,
        document_id: uuid.UUID | str,
        keep_keys: Collection[tuple[str, int]],
    ) -> int:
        """Delete records whose key is no longer composed (index included).

        The companion of ``upsert_document(..., prune=False)``: the worker
        writes only changed records, then prunes against the full composed
        key set, so an unchanged record is never deleted and re-embedded.
        """
        canonical = self.resolve_space(space)
        document_uuid = uuid.UUID(str(document_id))
        keep = {(str(view), int(chunk)) for view, chunk in keep_keys}
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            existing = list(
                session.execute(
                    select(VectorRecord.id, VectorRecord.view, VectorRecord.chunk_index).where(
                        VectorRecord.document_id == document_uuid,
                        VectorRecord.space_id == row.id,
                    )
                )
            )
            stale_ids = [
                record_id
                for record_id, view, chunk_index in existing
                if (str(view), int(chunk_index)) not in keep
            ]
            if not stale_ids:
                return 0
            self._backend.delete_record_ids_index(session, canonical, stale_ids)
            session.execute(delete(VectorRecord).where(VectorRecord.id.in_(stale_ids)))
            session.commit()
        return len(stale_ids)

    def records_to_embed(
        self,
        space: VectorSpace | uuid.UUID | str,
        *,
        document_id: uuid.UUID | str,
        records: Sequence[IndexRecord],
    ) -> list[IndexRecord]:
        """Drop records whose ``content_hash`` already matches (zero embed calls).

        Pair this with an incremental write: ``upsert_document(...,
        prune=False)`` for the returned records, then ``prune_records`` with
        every composed key. Feeding the filtered list to the default
        authoritative upsert would delete the unchanged records.
        """
        stored = self.existing_content_hashes(space, document_id=document_id)
        return [
            record
            for record in records
            if stored.get((record.view, record.chunk_index)) != record.content_hash
        ]

    def existing_content_hashes(
        self,
        space: VectorSpace | uuid.UUID | str,
        *,
        document_id: uuid.UUID | str,
    ) -> dict[tuple[str, int], str]:
        """The stored content hashes that let a worker skip unchanged views."""
        canonical = self.resolve_space(space)
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            return {
                (record.view, record.chunk_index): record.content_hash
                for record in session.scalars(
                    select(VectorRecord).where(
                        VectorRecord.document_id == uuid.UUID(str(document_id)),
                        VectorRecord.space_id == row.id,
                    )
                )
            }

    def delete_document(
        self,
        space: VectorSpace | uuid.UUID | str,
        document_id: uuid.UUID | str,
    ) -> bool:
        """Delete the physical index rows and the metadata document atomically."""
        canonical = self.resolve_space(space)
        document_uuid = uuid.UUID(str(document_id))
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            document = session.scalars(
                select(VectorDocument).where(
                    VectorDocument.id == document_uuid,
                    VectorDocument.space_id == row.id,
                )
            ).first()
            if document is None:
                return False
            self._backend.delete_document_index(session, canonical, str(document_uuid))
            session.execute(
                delete(VectorDocument).where(
                    VectorDocument.id == document_uuid,
                    VectorDocument.space_id == row.id,
                )
            )
            session.commit()
        return True

    def delete_scope(
        self,
        space: VectorSpace | uuid.UUID | str,
        *,
        scope_type: str,
        scope_id: uuid.UUID | str | None,
    ) -> int:
        """Erasure hook: hard-delete every document on one ownership axis."""
        canonical = self.resolve_space(space)
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            condition = [
                VectorDocument.space_id == row.id,
                VectorDocument.scope_type == scope_type,
            ]
            if scope_id is None:
                condition.append(VectorDocument.scope_id.is_(None))
            else:
                condition.append(VectorDocument.scope_id == uuid.UUID(str(scope_id)))
            document_ids = list(session.scalars(select(VectorDocument.id).where(*condition)))
            for document_id in document_ids:
                self._backend.delete_document_index(session, canonical, str(document_id))
            if document_ids:
                session.execute(delete(VectorDocument).where(*condition))
                session.commit()
        return len(document_ids)

    def orphan_sweep(
        self,
        space: VectorSpace | uuid.UUID | str,
        resolver: Callable[[str, str], bool],
        *,
        limit: int = 500,
        after_id: uuid.UUID | str | None = None,
        dry_run: bool = False,
    ) -> int:
        """Delete documents whose polymorphic source no longer resolves.

        ``after_id`` walks pages by document id (the maintenance action's
        bounded sweep); ``dry_run`` counts what would be deleted without
        touching metadata or the physical index.
        """
        canonical = self.resolve_space(space)
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            statement = (
                select(
                    VectorDocument.id,
                    VectorDocument.kind,
                    VectorDocument.source_id,
                )
                .where(VectorDocument.space_id == row.id)
                .order_by(VectorDocument.id)
                .limit(limit)
            )
            if after_id is not None:
                statement = statement.where(VectorDocument.id > uuid.UUID(str(after_id)))
            documents = list(session.execute(statement))
            stale = [
                document_id
                for document_id, kind, source_id in documents
                if not resolver(str(kind), str(source_id))
            ]
            if stale and not dry_run:
                for document_id in stale:
                    if canonical.index_table is not None:
                        self._backend.delete_document_index(session, canonical, str(document_id))
                session.execute(delete(VectorDocument).where(VectorDocument.id.in_(stale)))
                session.commit()
        return len(stale)

    def search(
        self,
        space: VectorSpace | uuid.UUID | str,
        query: Sequence[float],
        *,
        views: Collection[str],
        scope: ScopeSpec,
        limit: int,
        ef_search: int | None = None,
    ) -> list[IndexHit]:
        canonical = self.resolve_space(space)
        return self._backend.search(
            canonical,
            query,
            views=tuple(views),
            scope=scope,
            limit=limit,
            ef_search=ef_search,
        )

    def count(self, space: VectorSpace | uuid.UUID | str) -> int:
        return self._backend.count(self.resolve_space(space))

    def health(self, space: VectorSpace | uuid.UUID | str) -> BackendHealth:
        return self._backend.health(self.resolve_space(space))

    def lookup_documents(
        self,
        space: VectorSpace | uuid.UUID | str,
        document_ids: Sequence[str] | None = None,
        *,
        source_ids: Sequence[str] | None = None,
        kind: str | None = None,
        after_id: uuid.UUID | str | None = None,
        limit: int | None = None,
    ) -> dict[str, DocumentInfo]:
        """The product identity (kind + source id) of indexed documents.

        The read path ranks document ids; this is how a caller maps them back
        to its own rows without trusting anything stored in a vector table.
        ``source_ids`` is the inverse lookup (a caller that holds its own ids).
        """
        canonical = self.resolve_space(space)
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            statement = select(VectorDocument).where(VectorDocument.space_id == row.id)
            if document_ids is not None:
                if not document_ids:
                    return {}
                statement = statement.where(
                    VectorDocument.id.in_([uuid.UUID(str(value)) for value in document_ids])
                )
            if source_ids is not None:
                if not source_ids:
                    return {}
                statement = statement.where(
                    VectorDocument.source_id.in_([str(value) for value in source_ids])
                )
            if kind is not None:
                statement = statement.where(VectorDocument.kind == kind)
            if after_id is not None:
                statement = statement.where(VectorDocument.id > uuid.UUID(str(after_id)))
            statement = statement.order_by(VectorDocument.id)
            if limit is not None:
                statement = statement.limit(int(limit))
            return {
                str(document.id): DocumentInfo(
                    document_id=str(document.id),
                    kind=str(document.kind),
                    source_id=str(document.source_id),
                    scope_type=str(document.scope_type),
                    scope_id=str(document.scope_id) if document.scope_id else None,
                    profile_id=str(document.profile_id) if document.profile_id else None,
                )
                for document in session.scalars(statement)
            }

    def document_hashes(
        self,
        space: VectorSpace | uuid.UUID | str,
        *,
        kind: str | None = None,
        source_ids: Sequence[str] | None = None,
    ) -> dict[str, str]:
        """``source_id → stored source_hash`` for the space's documents.

        The reconcile pass compares this to a fresh composition: an equal
        hash costs zero embedding calls, a different one marks the document
        stale. ``source_ids`` bounds the read to one scan batch instead of
        loading the whole kind into memory.
        """
        canonical = self.resolve_space(space)
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            statement = select(VectorDocument.source_id, VectorDocument.source_hash).where(
                VectorDocument.space_id == row.id
            )
            if kind is not None:
                statement = statement.where(VectorDocument.kind == kind)
            if source_ids is not None:
                if not source_ids:
                    return {}
                statement = statement.where(
                    VectorDocument.source_id.in_([str(value) for value in source_ids])
                )
            return {
                str(source_id): str(source_hash)
                for source_id, source_hash in session.execute(statement)
            }

    def count_documents(
        self,
        space: VectorSpace | uuid.UUID | str,
        *,
        kind: str | None = None,
    ) -> int:
        """How many documents of a kind the space holds."""
        canonical = self.resolve_space(space)
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            statement = (
                select(func.count())
                .select_from(VectorDocument)
                .where(VectorDocument.space_id == row.id)
            )
            if kind is not None:
                statement = statement.where(VectorDocument.kind == kind)
            return int(session.scalar(statement) or 0)

    def document_vectors(
        self, space: VectorSpace | uuid.UUID | str, *, document_id: uuid.UUID | str
    ) -> list[StoredVector]:
        """Read one document's stored vectors back, in view/chunk order."""
        canonical = self.resolve_space(space)
        document_uuid = uuid.UUID(str(document_id))
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            records = list(
                session.execute(
                    select(VectorRecord.id, VectorRecord.view, VectorRecord.chunk_index)
                    .where(
                        VectorRecord.document_id == document_uuid,
                        VectorRecord.space_id == row.id,
                    )
                    .order_by(VectorRecord.view, VectorRecord.chunk_index)
                )
            )
        if not records:
            return []
        vectors = self._backend.fetch_vectors(canonical, [record_id for record_id, _, _ in records])
        return [
            StoredVector(
                record_id=str(record_id),
                view=str(view),
                chunk_index=int(chunk_index),
                vector=vectors[str(record_id)],
            )
            for record_id, view, chunk_index in records
            if vectors.get(str(record_id))
        ]
