"""Plan 218: content-addressed pack store guards."""

from __future__ import annotations

import uuid

import pytest

from app.core.seed_pack.errors import SeedPackError
from app.core.seed_pack.manifest import sha256_hex
from app.core.seed_pack.store import SeedPackStore, normalize_digest
from app.storage.object_storage import LocalObjectStore, StorageConfig


def _object_store(tmp_path):
    return LocalObjectStore(
        StorageConfig(
            backend="local",
            entrypoint="server",
            local_root=tmp_path / "uploads",
            max_object_mb=10,
        ).validate()
    )


def test_put_get_and_gc_roundtrip(tmp_path):
    packs = SeedPackStore(_object_store(tmp_path))
    source = uuid.uuid4()
    data = b"PK\x03\x04payload"
    digest = f"sha256:{sha256_hex(data)}"

    key = packs.put(source, digest, data)
    assert key.endswith(f"{digest[7:]}.zip")
    assert packs.get(source, digest) == data
    assert packs.has(source, digest)
    assert packs.get(source, f"sha256:{'0' * 64}") is None
    assert packs.gc_source(source) == 1
    assert not packs.has(source, digest)


def test_put_refuses_bytes_that_do_not_match_the_digest(tmp_path):
    packs = SeedPackStore(_object_store(tmp_path))
    with pytest.raises(SeedPackError) as exc:
        packs.put(uuid.uuid4(), f"sha256:{'0' * 64}", b"payload")
    assert exc.value.code == "DIGEST_DRIFT"


def test_get_refuses_tampered_stored_bytes(tmp_path):
    root = tmp_path / "uploads"
    packs = SeedPackStore(_object_store(tmp_path))
    source = uuid.uuid4()
    data = b"PK\x03\x04payload"
    digest = f"sha256:{sha256_hex(data)}"
    key = packs.put(source, digest, data)
    (root / key).write_bytes(b"tampered")

    with pytest.raises(SeedPackError) as exc:
        packs.get(source, digest)
    assert exc.value.code == "DIGEST_DRIFT"


def test_digest_normalization():
    raw = "a" * 64
    assert normalize_digest(f"sha256:{raw}") == raw
    assert normalize_digest(raw) == raw
    with pytest.raises(SeedPackError):
        normalize_digest("sha256:not-a-digest")
