"""Plan 218: admin/user provider API (versions, apply, visibility)."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.core.seed_pack.archive import build_pack_archive
from app.core.seed_pack.manifest import parse_repo_index
from app.core.seed_pack.store import SeedPackStore
from app.models.seed_model import JobSourcePreset
from app.schemas.providers import DiscoverIn
from app.services.seeds.provider_service import ProviderService
from app.storage.object_storage import LocalObjectStore, StorageConfig
from tests.conftest import register_user
from tests.test_seed_sync_service import _files

ADMIN = "/api/v1/admin/providers"
USER = "/api/v1/providers"


def _store(tmp_path: Path) -> SeedPackStore:
    return SeedPackStore(
        LocalObjectStore(
            StorageConfig(
                backend="local",
                entrypoint="server",
                local_root=tmp_path / "uploads",
                max_object_mb=10,
            ).validate()
        )
    )


def _file_provider(**overrides) -> dict:
    payload = {
        "kind": "file",
        "name": "Test provider",
        "priority": 100,
        "trust_tier": "community",
        "refresh_minutes": 0,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


async def test_plan_preview_reports_a_missing_archive_instead_of_500(
    client, auth_headers, db, tmp_path, monkeypatch
):
    import uuid as uuid_module

    import app.services.seeds.provider_service as provider_module

    store = _store(tmp_path)
    monkeypatch.setattr(provider_module, "SeedPackStore", lambda: store)

    created = await client.post(ADMIN, headers=auth_headers, json=_file_provider())
    provider_id = created.json()["id"]
    uploaded = await client.post(
        f"{ADMIN}/{provider_id}/upload",
        headers=auth_headers,
        files={"file": ("pack.zip", build_pack_archive(_files()), "application/zip")},
    )
    version_id = uploaded.json()["version_id"]
    versions = await client.get(f"{ADMIN}/{provider_id}/versions", headers=auth_headers)
    digest = versions.json()[0]["digest"]
    store.delete(uuid_module.UUID(provider_id), digest)

    preview = await client.get(
        f"{ADMIN}/{provider_id}/versions/{version_id}/plan", headers=auth_headers
    )
    assert preview.status_code == 400, preview.text
    assert "PACK_ARCHIVE_MISSING" in preview.json()["detail"]
    assert "upload the pack again" in preview.json()["detail"]


async def test_admin_upload_approve_apply_and_user_view(
    client, auth_headers, db, tmp_path, monkeypatch
):
    import app.services.seeds.provider_service as provider_module

    store = _store(tmp_path)
    monkeypatch.setattr(provider_module, "SeedPackStore", lambda: store)

    created = await client.post(ADMIN, headers=auth_headers, json=_file_provider())
    assert created.status_code == 201, created.text
    provider_id = created.json()["id"]
    assert created.json()["current_version"] is None

    archive = build_pack_archive(_files())
    uploaded = await client.post(
        f"{ADMIN}/{provider_id}/upload",
        headers=auth_headers,
        files={"file": ("pack.zip", archive, "application/zip")},
    )
    assert uploaded.status_code == 200, uploaded.text
    report = uploaded.json()
    assert report["status"] == "ok"
    version_id = report["version_id"]

    versions = await client.get(f"{ADMIN}/{provider_id}/versions", headers=auth_headers)
    assert versions.status_code == 200
    assert versions.json()[0]["status"] == "pending"
    assert versions.json()[0]["pack_version"] == "1.0.0"

    preview = await client.get(
        f"{ADMIN}/{provider_id}/versions/{version_id}/plan", headers=auth_headers
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["counts"]["create"] == 1

    approved = await client.post(
        f"{ADMIN}/{provider_id}/versions/{version_id}/approve", headers=auth_headers
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    applied = await client.post(
        f"{ADMIN}/{provider_id}/versions/{version_id}/apply", headers=auth_headers
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert applied.json()["counts"]["create"] == 1

    listed = await client.get(USER, headers=auth_headers)
    assert listed.status_code == 200
    assert [entry["id"] for entry in listed.json()] == [provider_id]
    assert listed.json()[0]["pack_version"] == "1.0.0"
    assert listed.json()[0]["item_count"] == 0

    enabled = await client.post(
        f"{ADMIN}/{provider_id}/items/ats-preset:acme/enable", headers=auth_headers
    )
    assert enabled.status_code == 200
    detail = await client.get(f"{USER}/{provider_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert [preset["name"] for preset in detail.json()["presets"]] == ["Acme"]
    assert detail.json()["item_count"] == 1
    assert (await client.get(f"{USER}/{provider_id}/endpoints", headers=auth_headers)).json() == []

    runs = await client.get(f"{ADMIN}/{provider_id}/sync-runs", headers=auth_headers)
    assert runs.status_code == 200
    assert runs.json()[0]["status"] == "ok"

    disabled = await client.patch(
        f"{ADMIN}/{provider_id}", headers=auth_headers, json={"enabled": False}
    )
    assert disabled.status_code == 200
    assert (await client.get(USER, headers=auth_headers)).json() == []

    deleted = await client.delete(f"{ADMIN}/{provider_id}", headers=auth_headers)
    assert deleted.status_code == 200
    assert deleted.json()["retired"] is True
    preset = await db.scalar(select(JobSourcePreset))
    assert preset is not None and preset.state == "retired"


async def test_provider_routes_enforce_admin_and_auth(client, auth_headers):
    member_headers = await register_user(client, "member@example.com", "supersecret1")
    denied = await client.get(ADMIN, headers=member_headers)
    assert denied.status_code == 403
    assert (await client.get(USER, headers=member_headers)).status_code == 200
    assert (await client.get(USER)).status_code == 401


async def test_discover_reads_a_registry_index(db, tmp_path, monkeypatch):
    import app.services.seeds.provider_service as provider_module

    index = {
        "schemaVersion": 1,
        "kind": "career-seed-repo",
        "publisher": {"id": "test", "name": "Test"},
        "packs": [
            {
                "id": "test-pack",
                "path": "packs/test/test-pack",
                "manifest": "packs/test/test-pack/manifest.json",
                "itemTypes": ["ats_presets"],
                "license": "CC-BY-4.0",
                "version": "1.0.0",
                "digest": f"sha256:{'a' * 64}",
                "signature": None,
            }
        ],
    }
    parsed = parse_repo_index(json.dumps(index).encode())

    class _FakeRegistry:
        async def fetch_index(self, uri, *, etag=None):
            from app.services.seeds.registry_transport import IndexFetch

            return IndexFetch(index=parsed, etag="e1", base_url="https://seed.test", status=200)

    monkeypatch.setattr(provider_module, "RegistryTransport", _FakeRegistry)
    result = await ProviderService(db, packs=_store(tmp_path)).discover(
        DiscoverIn(kind="registry", uri="https://seed.test/repo")
    )
    assert result["kind"] == "registry"
    assert result["packs"][0]["id"] == "test-pack"
