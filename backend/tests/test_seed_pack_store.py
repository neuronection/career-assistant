"""Plan 218: content-addressed pack store guards."""

from __future__ import annotations

import json
import uuid

import pytest

from app.core.seed_pack.archive import build_pack_archive
from app.core.seed_pack.errors import SeedPackError
from app.core.seed_pack.manifest import compute_files_digest, sha256_hex
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


def _files(name: str = "acme") -> dict[str, bytes]:
    item = {
        "seed_key": f"ats-preset:{name}",
        "slug": name,
        "name": name.title(),
        "connector_key": "recruitee",
        "platform": "Recruitee",
        "category": "ats",
        "country": "GR",
        "config": {"company": name},
    }
    envelope = {
        "metadata": {
            "item_type": "ats_presets",
            "format": "ats_presets",
            "format_version": 1,
            "dataset_vintage": "2026-11-24",
        },
        "items": [item],
    }
    item_bytes = json.dumps(envelope, sort_keys=True).encode()
    manifest = {
        "id": "test-pack",
        "schema_version": "1.0",
        "version": "1.0.0",
        "license": "CC-BY-4.0",
        "scope": "system",
        "priority": 100,
        "item_files": [{"path": "items/ats_presets/acme.json", "sha256": sha256_hex(item_bytes)}],
    }
    return {
        "manifest.json": json.dumps(manifest, sort_keys=True).encode(),
        "items/ats_presets/acme.json": item_bytes,
    }


def test_put_get_and_gc_roundtrip(tmp_path):
    packs = SeedPackStore(_object_store(tmp_path))
    source = uuid.uuid4()
    files = _files()
    archive = build_pack_archive(files)
    digest = compute_files_digest(files)

    key = packs.put(source, digest, archive)
    assert key.endswith(f"{digest[7:]}.zip")
    assert packs.get(source, digest) == archive
    assert packs.has(source, digest)
    assert packs.get(source, f"sha256:{'0' * 64}") is None
    assert packs.gc_source(source) == 1
    assert not packs.has(source, digest)


def test_put_refuses_an_archive_that_does_not_match_the_digest(tmp_path):
    packs = SeedPackStore(_object_store(tmp_path))
    with pytest.raises(SeedPackError) as exc:
        packs.put(uuid.uuid4(), f"sha256:{'0' * 64}", build_pack_archive(_files()))
    assert exc.value.code == "DIGEST_DRIFT"


def test_get_refuses_a_tampered_stored_archive(tmp_path):
    root = tmp_path / "uploads"
    packs = SeedPackStore(_object_store(tmp_path))
    source = uuid.uuid4()
    digest = compute_files_digest(_files())
    key = packs.put(source, digest, build_pack_archive(_files()))
    (root / key).write_bytes(build_pack_archive(_files("other")))

    with pytest.raises(SeedPackError) as exc:
        packs.get(source, digest)
    assert exc.value.code == "DIGEST_DRIFT"


def test_digest_normalization():
    raw = "a" * 64
    assert normalize_digest(f"sha256:{raw}") == raw
    assert normalize_digest(raw) == raw
    with pytest.raises(SeedPackError):
        normalize_digest("sha256:not-a-digest")
