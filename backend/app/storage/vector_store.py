"""The metadata-owning vector store service (plan 50 §3, §4, P1b).

One seam owns the portable metadata — ``vector_spaces``,
``vector_documents`` and ``vector_records`` — plus the content-hash and
dimension guards, document registration, deletion and the orphan sweep. The
physical index belongs to a :class:`VectorBackend`; the service passes the
same session into the backend's index hooks so metadata and index rows for
one document commit atomically.

This module never issues DDL. Provisioning is
:mod:`app.storage.vector_provisioning` (a migration or the P1c reindex job).
Composers and call-site cutover are P1c; the service is already usable by
them without further store work.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import cast

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.enums.retrieval import VectorScopeType
from app.models.vector_model import VectorDocument, VectorRecord
from app.models.vector_model import VectorSpace as VectorSpaceRow
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


def canonical_space(row: VectorSpaceRow) -> VectorSpace:
    """Build the contract DTO from the persisted row (index_table included)."""
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
    ) -> IndexedDocument:
        """Write metadata + physical index rows for one document atomically."""
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
            written = 0
            for record in records:
                key = (record.view, record.chunk_index)
                stored = existing.get(key)
                record_uuid = uuid.UUID(str(record.record_id))
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
                            content_hash=record.content_hash,
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
                    stored.content_hash = record.content_hash
                written += 1
            session.flush()
            self._backend.upsert_index(session, canonical, records)
            session.commit()
        return IndexedDocument(
            document_id=str(document_uuid), records=len(records), written=written
        )

    def records_to_embed(
        self,
        space: VectorSpace | uuid.UUID | str,
        *,
        document_id: uuid.UUID | str,
        records: Sequence[IndexRecord],
    ) -> list[IndexRecord]:
        """Drop records whose ``content_hash`` already matches (zero embed calls)."""
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
    ) -> int:
        """Delete documents whose polymorphic source no longer resolves."""
        canonical = self.resolve_space(space)
        with self._session_factory() as session:
            row = resolve_space_row(session, canonical)
            documents = list(
                session.execute(
                    select(
                        VectorDocument.id,
                        VectorDocument.kind,
                        VectorDocument.source_id,
                    )
                    .where(VectorDocument.space_id == row.id)
                    .limit(limit)
                )
            )
            stale = [
                document_id
                for document_id, kind, source_id in documents
                if not resolver(str(kind), str(source_id))
            ]
            for document_id in stale:
                self._backend.delete_document_index(session, canonical, str(document_id))
            if stale:
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
