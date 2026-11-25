"""Content-addressed pack store (plan 218 §3.7).

Pack bytes live under ``seed-packs/<source_id>/<pack-digest>.zip`` through the
family object-storage seam. The key digest is the **pack digest** (canonical
manifest + item bytes), not the archive's own hash; every write and read
extracts the archive and recomputes that digest. A mismatch is
``DIGEST_DRIFT``, never a silent cache hit.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from app.core.seed_pack.archive import extract_pack_archive
from app.core.seed_pack.errors import DIGEST_DRIFT, SeedPackError
from app.core.seed_pack.manifest import compute_files_digest

if TYPE_CHECKING:
    from app.storage.object_storage import ObjectStore

PACK_PREFIX = "seed-packs"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def normalize_digest(value: str) -> str:
    digest = value[7:] if value.startswith("sha256:") else value
    if not _DIGEST.match(digest):
        raise SeedPackError(DIGEST_DRIFT, f"not a sha256 digest: {value[:80]!r}")
    return digest


def _archive_digest(data: bytes) -> str:
    files = extract_pack_archive(data)
    return compute_files_digest(files).split(":", 1)[1]


class SeedPackStore:
    """Store and retrieve pack archives by pack digest."""

    def __init__(self, store: ObjectStore | None = None) -> None:
        self._store = store

    @property
    def store(self) -> ObjectStore:
        if self._store is None:
            from app.storage.bootstrap import current_store

            self._store = current_store()
        return self._store

    def object_key(self, source_id: uuid.UUID | str, digest: str) -> str:
        return f"{PACK_PREFIX}/{source_id}/{normalize_digest(digest)}.zip"

    def put(self, source_id: uuid.UUID | str, digest: str, data: bytes) -> str:
        expected = normalize_digest(digest)
        actual = _archive_digest(data)
        if actual != expected:
            raise SeedPackError(DIGEST_DRIFT, f"archive hashes to {actual}, expected {expected}")
        key = self.object_key(source_id, expected)
        self.store.put(key, data, content_type="application/zip")
        return key

    def get(self, source_id: uuid.UUID | str, digest: str) -> bytes | None:
        expected = normalize_digest(digest)
        data = self.store.get(self.object_key(source_id, expected))
        if data is None:
            return None
        actual = _archive_digest(data)
        if actual != expected:
            raise SeedPackError(
                DIGEST_DRIFT, f"stored archive hashes to {actual}, expected {expected}"
            )
        return data

    def has(self, source_id: uuid.UUID | str, digest: str) -> bool:
        return self.store.exists(self.object_key(source_id, digest))

    def delete(self, source_id: uuid.UUID | str, digest: str) -> bool:
        return self.store.delete(self.object_key(source_id, digest))

    def gc_source(self, source_id: uuid.UUID | str) -> int:
        prefix = f"{PACK_PREFIX}/{source_id}"
        removed = 0
        for info in list(self.store.list(prefix=prefix)):
            if self.store.delete(info.key):
                removed += 1
        return removed


__all__ = ["PACK_PREFIX", "SeedPackStore", "normalize_digest"]
