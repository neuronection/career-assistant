"""Plan 218: static-index registry transport over the guarded fetch seam."""

from __future__ import annotations

import json

import pytest

import app.services.seeds.registry_transport as registry_module
from app.core.seed_pack.errors import SeedPackError
from app.core.seed_pack.manifest import compute_files_digest, sha256_hex
from app.services.seeds.registry_transport import RegistryTransport

BASE = "https://seed.test/repo"
PACK_PATH = "packs/test/test-pack"
ITEM_PATH = f"{PACK_PATH}/items/ats_presets/acme.json"


def _pack_files(name: str = "Acme") -> dict[str, bytes]:
    envelope = {
        "metadata": {
            "item_type": "ats_presets",
            "format": "ats_presets",
            "format_version": 1,
            "dataset_vintage": "2026-11-24",
            "license": "CC-BY-4.0",
        },
        "items": [
            {
                "seed_key": "ats-preset:acme",
                "slug": "acme",
                "name": name,
                "connector_key": "recruitee",
                "platform": "Recruitee",
                "category": "ats",
                "country": "GR",
                "config": {"company": "acme"},
            }
        ],
    }
    data = json.dumps(envelope, sort_keys=True).encode()
    manifest = {
        "id": "test-pack",
        "schema_version": "1.0",
        "version": "1.0.0",
        "license": "CC-BY-4.0",
        "scope": "system",
        "priority": 100,
        "item_files": [{"path": "items/ats_presets/acme.json", "sha256": sha256_hex(data)}],
    }
    return {
        "manifest.json": json.dumps(manifest, sort_keys=True).encode(),
        "items/ats_presets/acme.json": data,
    }


def _index_bytes(files: dict[str, bytes], *, digest: str | None = None) -> bytes:
    index = {
        "schemaVersion": 1,
        "kind": "career-seed-repo",
        "publisher": {"id": "test", "name": "Test"},
        "packs": [
            {
                "id": "test-pack",
                "path": PACK_PATH,
                "manifest": f"{PACK_PATH}/manifest.json",
                "itemTypes": ["ats_presets"],
                "license": "CC-BY-4.0",
                "version": "1.0.0",
                "digest": digest or compute_files_digest(files),
                "signature": None,
            }
        ],
    }
    return json.dumps(index, sort_keys=True).encode()


class _Server:
    def __init__(self, files: dict[str, bytes], **overrides):
        self.files = files
        self.etag = "e1"
        self.overrides = overrides
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, url, *, headers=None, max_bytes=2_000_000):
        self.calls.append((url, dict(headers or {})))
        if url.endswith("seed-repo.json"):
            if (headers or {}).get("If-None-Match") == self.etag:
                return 304, {"etag": self.etag}, b"", url
            body = self.overrides.get("index", _index_bytes(self.files))
            return 200, {"etag": self.etag}, body, url
        relative = url.split(f"{BASE}/", 1)[1]
        if relative in self.overrides:
            return self.overrides[relative]
        key = relative[len(PACK_PATH) + 1 :] if relative.startswith(f"{PACK_PATH}/") else relative
        data = self.files.get(key)
        if data is None:
            return 404, {}, b"", url
        return 200, {}, data, url


@pytest.fixture
def server(monkeypatch):
    files = _pack_files()
    fake = _Server(files)
    monkeypatch.setattr(registry_module, "fetch_bytes", fake)
    return fake


async def test_fetch_index_and_pack(server):
    transport = RegistryTransport()
    fetched = await transport.fetch_index(BASE)
    assert fetched.status == 200
    assert fetched.etag == "e1"
    assert fetched.index is not None and fetched.index.packs[0].id == "test-pack"

    files = await transport.fetch_pack(fetched.base_url, fetched.index.packs[0])
    assert compute_files_digest(files) == compute_files_digest(_pack_files())


async def test_index_304_is_unchanged(server):
    transport = RegistryTransport()
    fetched = await transport.fetch_index(BASE, etag="e1")
    assert fetched.unchanged
    assert fetched.index is None


async def test_index_digest_and_item_digest_are_enforced(server):
    server.overrides["index"] = _index_bytes(_pack_files(), digest=f"sha256:{'0' * 64}")
    fetched = await RegistryTransport().fetch_index(BASE)
    assert fetched.index is not None
    assert fetched.index.packs[0].digest == f"sha256:{'0' * 64}"

    server.overrides[ITEM_PATH] = (200, {}, b"tampered", BASE)
    with pytest.raises(SeedPackError) as exc:
        await RegistryTransport().fetch_pack(fetched.base_url, fetched.index.packs[0])
    assert exc.value.code == "DIGEST_MISMATCH"


async def test_missing_item_is_a_partial(server):
    server.overrides[ITEM_PATH] = (404, {}, b"", BASE)
    fetched = await RegistryTransport().fetch_index(BASE)
    assert fetched.index is not None
    with pytest.raises(SeedPackError) as exc:
        await RegistryTransport().fetch_pack(fetched.base_url, fetched.index.packs[0])
    assert exc.value.code == "REGISTRY_PARTIAL"


async def test_non_https_is_refused(monkeypatch):
    with pytest.raises(SeedPackError) as exc:
        await RegistryTransport().fetch_index("http://seed.test/repo")
    assert exc.value.code == "REGISTRY_FETCH_FAILED"
