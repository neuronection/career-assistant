"""Document bytes through the family object-storage contract (ADR-0057).

`DocumentStorage` is career's one seam between the domain rows and the
deployed backend: local on desktop/self-host, `s3`/`azure_blob` under a
cloud profile. The database stores an opaque *key* (`documents.object_key`)
— never a path. Rows written before the contract carry no key; the facade
dual-reads the legacy `<upload_dir>/<id><ext>` file when the object is
absent (self-host/desktop), so an upgrade keeps every existing document.

Synchronous methods are the primitives; the `a*` variants are the async
bridge used by routes, services and background jobs (`anyio.to_thread`), so
provider latency never blocks the event loop. `app/storage/bootstrap.py`
owns the process store.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import anyio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document_model import Document
from app.storage.bootstrap import current_store
from app.storage.object_storage import (
    BACKEND_LOCAL,
    ObjectInfo,
    ObjectNotFound,
    ObjectStore,
    filename_extension,
    join_key,
    tenant_key,
)
from app.storage.object_storage import (
    materialize as materialize_object,
)

CHUNK_SIZE = 64 * 1024


def document_key(
    user_id: uuid.UUID | str, document_id: uuid.UUID | str, filename: str | None
) -> str:
    """`tenants/<user>/documents/<document-id><ext>` (server-generated)."""
    extension = filename_extension(filename or "")
    return tenant_key(str(user_id), "documents", str(document_id), extension)


def page_key(user_id: uuid.UUID | str, document_id: uuid.UUID | str, index: int) -> str:
    """`tenants/<user>/cv_pages/<document-id>-p<index>.png`."""
    return tenant_key(str(user_id), "cv_pages", f"{document_id}-p{index}", "png")


def export_key(user_id: uuid.UUID | str, job_id: uuid.UUID | str) -> str:
    """`tenants/<user>/exports/<job-id>.zip`."""
    return tenant_key(str(user_id), "exports", str(job_id), "zip")


def legacy_document_path(document: Document, root: Path | str | None = None) -> Path:
    """The pre-contract `<upload_dir>/<id><ext>` location.

    ``root`` lets the migration CLI use its own resolved upload root instead
    of the process-global Settings (a one-shot tool may run with a staging
    root); the facade passes ``None`` and keeps the runtime setting.
    """
    base = Path(root) if root is not None else Path(settings.upload_root)
    suffix = Path(document.filename).suffix or ".bin"
    return base / f"{document.id}{suffix}"


def legacy_page_path(
    document_id: uuid.UUID | str, index: int, root: Path | str | None = None
) -> Path:
    base = Path(root) if root is not None else Path(settings.upload_root)
    return base / "derived" / str(document_id) / f"page-{index}.png"


def _legacy_source(document: Document) -> Path:
    return legacy_document_path(document)


def _legacy_page(document_id: uuid.UUID | str, index: int) -> Path:
    return legacy_page_path(document_id, index)


def _modified_at(raw: object) -> datetime | None:
    """Parse the contract's backend-shaped `last_modified` (epoch or ISO)."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromtimestamp(int(text), tz=UTC)
    except (TypeError, ValueError, OSError):
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _file_chunks(path: Path, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            yield chunk


@contextmanager
def _private_copy(path: Path, suffix: str = ".bin") -> Iterator[Path]:
    """Yield a private ``0600`` temp copy of a durable local file."""
    descriptor, name = tempfile.mkstemp(prefix="career-legacy-", suffix=suffix)
    target = Path(name)
    try:
        os.chmod(target, 0o600)
        with os.fdopen(descriptor, "wb") as out, path.open("rb") as source:
            shutil.copyfileobj(source, out, CHUNK_SIZE)
        yield target
    finally:
        target.unlink(missing_ok=True)


class DocumentStorage:
    """The document/export byte API over one `ObjectStore`."""

    def __init__(self, store: ObjectStore | None = None) -> None:
        self._store = store

    @property
    def store(self) -> ObjectStore:
        return self._store if self._store is not None else current_store()

    @property
    def backend(self) -> str:
        return self.store.backend

    @property
    def is_local(self) -> bool:
        return self.backend == BACKEND_LOCAL

    # ------------------------------------------------------------------ keys

    def object_key(self, document: Document) -> str:
        """The row's object key, falling back to its deterministic builder."""
        return document.object_key or document_key(document.user_id, document.id, document.filename)

    def page_key(self, document: Document, index: int) -> str:
        return page_key(document.user_id, document.id, index)

    def page_prefix(self, document: Document) -> str:
        """The listing prefix shared by every rendered page of one document.

        Deletion enumerates this prefix instead of trusting `page_count` /
        `extraction`: a PROCESSING or failed run can own page objects while
        both counters still say zero.
        """
        return tenant_key(str(document.user_id), "cv_pages", f"{document.id}-p")

    def page_keys(self, document: Document) -> list[str]:
        """Every stored page key for one document, enumerated from the store.

        Local `list` takes a directory prefix, cloud adapters take a string
        prefix, so list the (existing) category directory and filter by the
        document's `<id>-p` prefix — the portable form of both.
        """
        category = join_key("tenants", str(document.user_id), "cv_pages")
        prefix = self.page_prefix(document)
        return [info.key for info in self.store.list(category) if info.key.startswith(prefix)]

    # -------------------------------------------------------------- documents

    def put_document(self, document: Document, data: bytes) -> str:
        """Write the original upload and return its key (caller persists it)."""
        key = document_key(document.user_id, document.id, document.filename)
        self.store.put(key, data, content_type=document.mime or None)
        return key

    def read(self, document: Document) -> bytes | None:
        """Object key first, then the legacy local file (dual-read)."""
        data = self.store.get(self.object_key(document))
        if data is not None:
            return data
        if not self.is_local:
            return None
        legacy = _legacy_source(document)
        return legacy.read_bytes() if legacy.is_file() else None

    def stream(self, document: Document, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
        """Chunked bytes from the object, else the legacy local file."""
        key = self.object_key(document)
        if self.store.stat(key) is not None:
            return self.store.stream(key, chunk_size=chunk_size)
        if self.is_local:
            legacy = _legacy_source(document)
            if legacy.is_file():
                return _file_chunks(legacy, chunk_size)
        raise ObjectNotFound(key)

    def exists(self, document: Document) -> bool:
        if self.store.stat(self.object_key(document)) is not None:
            return True
        return self.is_local and _legacy_source(document).is_file()

    @contextmanager
    def materialize(self, document: Document) -> Iterator[Path]:
        """A private `0600` temp file for a path-taking processor."""
        key = self.object_key(document)
        if self.store.stat(key) is not None:
            with materialize_object(self.store, key) as path:
                yield path
            return
        if self.is_local:
            legacy = _legacy_source(document)
            if legacy.is_file():
                with _private_copy(legacy, Path(document.filename).suffix or ".bin") as path:
                    yield path
                return
        raise ObjectNotFound(key)

    def delete(self, document: Document, *, object_shared: bool = False) -> None:
        """Remove every derived page and (unless shared) the source object.

        Pages are enumerated from their key prefix, never from row counters:
        a PROCESSING or failed document can own rendered pages while
        `page_count` is still 0 and `extraction` is still null.

        `object_shared` says another `documents` row references the same
        object key (a copied row); the bytes then survive this row's delete.
        A per-document key never collides by construction, but deleting a
        shared object would corrupt the other row.
        """
        for key in self.page_keys(document):
            self.store.delete(key)
        if not object_shared:
            self.store.delete(self.object_key(document))
        if not self.is_local:
            return
        if not object_shared:
            legacy = _legacy_source(document)
            if legacy.is_file():
                legacy.unlink(missing_ok=True)
        derived = _legacy_page(document.id, 0).parent
        if derived.is_dir():
            shutil.rmtree(derived, ignore_errors=True)

    # ------------------------------------------------------------------ pages

    def put_page(self, document: Document, index: int, data: bytes) -> str:
        key = self.page_key(document, index)
        self.store.put(key, data, content_type="image/png")
        return key

    def read_page(self, document: Document, index: int) -> bytes | None:
        data = self.store.get(self.page_key(document, index))
        if data is not None:
            return data
        if not self.is_local:
            return None
        legacy = _legacy_page(document.id, index)
        return legacy.read_bytes() if legacy.is_file() else None

    # ---------------------------------------------------------------- exports

    def put_export(self, user_id: uuid.UUID, job_id: uuid.UUID, data: bytes) -> str:
        key = export_key(user_id, job_id)
        self.store.put(key, data, content_type="application/zip")
        return key

    def stat_key(self, key: str) -> ObjectInfo | None:
        return self.store.stat(key)

    def read_key(self, key: str) -> bytes | None:
        return self.store.get(key)

    def stream_key(self, key: str, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
        return self.store.stream(key, chunk_size=chunk_size)

    def delete_key(self, key: str) -> bool:
        return self.store.delete(key)

    def purge_exports(self, max_age_days: int = 7) -> int:
        """Delete export objects past the retention window."""
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        removed = 0
        for info in self.store.list("tenants"):
            if "/exports/" not in info.key:
                continue
            modified = _modified_at(info.last_modified)
            if modified is not None and modified < cutoff and self.store.delete(info.key):
                removed += 1
        return removed

    # ----------------------------------------------------------- async bridge

    async def aput_document(self, document: Document, data: bytes) -> str:
        return await anyio.to_thread.run_sync(self.put_document, document, data)

    async def aread(self, document: Document) -> bytes | None:
        return await anyio.to_thread.run_sync(self.read, document)

    async def astream(
        self, document: Document, chunk_size: int = CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        iterator = await anyio.to_thread.run_sync(
            partial(self.stream, document, chunk_size=chunk_size)
        )
        try:
            while True:
                chunk = await anyio.to_thread.run_sync(next, iterator, None)
                if chunk is None:
                    return
                yield chunk
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                await anyio.to_thread.run_sync(close)

    async def aexists(self, document: Document) -> bool:
        return await anyio.to_thread.run_sync(self.exists, document)

    async def adelete(self, document: Document, db: AsyncSession | None = None) -> None:
        shared = False
        if db is not None:
            key = self.object_key(document)
            count = await db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.object_key == key, Document.id != document.id)
            )
            shared = bool(count)
        await anyio.to_thread.run_sync(partial(self.delete, document, object_shared=shared))

    @asynccontextmanager
    async def amaterialize(self, document: Document) -> AsyncIterator[Path]:
        manager = self.materialize(document)
        path = await anyio.to_thread.run_sync(manager.__enter__)
        try:
            yield path
        finally:
            await anyio.to_thread.run_sync(manager.__exit__, None, None, None)

    async def aput_page(self, document: Document, index: int, data: bytes) -> str:
        return await anyio.to_thread.run_sync(self.put_page, document, index, data)

    async def aread_page(self, document: Document, index: int) -> bytes | None:
        return await anyio.to_thread.run_sync(self.read_page, document, index)

    async def aput_export(self, user_id: uuid.UUID, job_id: uuid.UUID, data: bytes) -> str:
        return await anyio.to_thread.run_sync(self.put_export, user_id, job_id, data)

    async def astat_key(self, key: str):
        return await anyio.to_thread.run_sync(self.stat_key, key)

    async def aread_key(self, key: str) -> bytes | None:
        return await anyio.to_thread.run_sync(self.read_key, key)

    async def astream_key(self, key: str, chunk_size: int = CHUNK_SIZE) -> AsyncIterator[bytes]:
        iterator = await anyio.to_thread.run_sync(
            partial(self.stream_key, key, chunk_size=chunk_size)
        )
        try:
            while True:
                chunk = await anyio.to_thread.run_sync(next, iterator, None)
                if chunk is None:
                    return
                yield chunk
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                await anyio.to_thread.run_sync(close)

    async def apurge_exports(self, max_age_days: int = 7) -> int:
        return await anyio.to_thread.run_sync(self.purge_exports, max_age_days)


async def chain_first(first: bytes, rest: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Re-yield a prefetched first chunk, then the rest of a stream."""
    try:
        yield first
        async for chunk in rest:
            yield chunk
    finally:
        close = getattr(rest, "aclose", None)
        if close is not None:
            await close()


def document_storage() -> DocumentStorage:
    """The process `DocumentStorage` (an app boot already built the store)."""
    return DocumentStorage()
