"""Content-addressed pack store (plan 218 §3.7).

Pack bytes live under ``seed-packs/<source_id>/<sha256>.zip`` through the
family object-storage seam. Every write and read re-hashes the bytes against
the claimed digest: a mismatch is ``DIGEST_DRIFT``, never a silent cache hit.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from app.core.seed_pack.errors import DIGEST_DRIFT, SeedPackError
from app.core.seed_pack.manifest import sha256_hex

if TYPE_CHECKING:
    from app.storage.object_storage import ObjectStore

PACK_PREFIX = "seed-packs"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def normalize_digest(value: str) -> str:
    digest = value[7:] if value.startswith("sha256:") else value
    if not _DIGEST.match(digest):
        raise SeedPackError(DIGEST_DRIFT, f"not a sha256 digest: {value[:80]!r}")
    return digest


class SeedPackStore:
    """Store and retrieve pack archives by content digest."""

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
        actual = sha256_hex(data)
        if actual != expected:
            raise SeedPackError(DIGEST_DRIFT, f"bytes hash to {actual}, expected {expected}")
        key = self.object_key(source_id, expected)
        self.store.put(key, data, content_type="application/zip")
        return key

    def get(self, source_id: uuid.UUID | str, digest: str) -> bytes | None:
        expected = normalize_digest(digest)
        data = self.store.get(self.object_key(source_id, expected))
        if data is None:
            return None
        actual = sha256_hex(data)
        if actual != expected:
            raise SeedPackError(DIGEST_DRIFT, f"stored bytes hash to {actual}, expected {expected}")
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
