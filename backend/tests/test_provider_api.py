"""Plan 218: admin/user provider API (versions, apply, visibility)."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.core.seed_pack.archive import build_pack_archive
from app.core.seed_pack.manifest import parse_repo_index
from app.core.seed_pack.store import SeedPackStore
from app.models.job_model import Job
from app.models.seed_model import JobSourcePreset, SeedItemProvenance
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


async def test_import_repository_adds_every_pack_once(client, auth_headers, db, monkeypatch):
    import app.services.seeds.provider_service as provider_module

    index = {
        "schemaVersion": 1,
        "kind": "career-seed-repo",
        "publisher": {"id": "example", "name": "Example"},
        "packs": [
            {
                "id": "example-one",
                "path": "packs/example/one",
                "manifest": "packs/example/one/manifest.json",
                "itemTypes": ["ats_presets"],
                "license": "CC-BY-4.0",
                "version": "1.0.0",
                "digest": f"sha256:{'a' * 64}",
                "signature": None,
            },
            {
                "id": "example-two",
                "path": "packs/example/two",
                "manifest": "packs/example/two/manifest.json",
                "itemTypes": ["endpoint_descriptors"],
                "license": "CC-BY-4.0",
                "version": "1.0.0",
                "digest": f"sha256:{'b' * 64}",
                "signature": None,
            },
        ],
    }

    class _FakeGit:
        async def discover(self, uri, ref):
            return json.dumps(index).encode(), "c" * 40

    monkeypatch.setattr(provider_module, "GitTransport", _FakeGit)
    payload = {
        "kind": "git",
        "uri": "https://github.com/example/seeds.git",
        "ref": "v1",
        "priority": 40,
        "trust_tier": "operator",
    }

    first = await client.post(f"{ADMIN}/import", headers=auth_headers, json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["publisher"]["name"] == "Example"
    assert [pack["created"] for pack in first.json()["packs"]] == [True, True]
    assert [pack["name"] for pack in first.json()["packs"]] == [
        "Example — one",
        "Example — two",
    ]

    again = await client.post(f"{ADMIN}/import", headers=auth_headers, json=payload)
    assert again.status_code == 201, again.text
    assert [pack["created"] for pack in again.json()["packs"]] == [False, False]

    listed = await client.get(ADMIN, headers=auth_headers)
    assert {row["subpath"] for row in listed.json()} == {
        "packs/example/one",
        "packs/example/two",
    }
    assert {row["priority"] for row in listed.json()} == {40}


async def test_import_repository_requires_a_pinned_ref(client, auth_headers):
    response = await client.post(
        f"{ADMIN}/import",
        headers=auth_headers,
        json={"kind": "git", "uri": "https://github.com/example/seeds.git"},
    )
    assert response.status_code == 400
    assert "pinned ref" in response.json()["detail"]


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
    # An applied pack is the admin's choice: its presets start enabled.
    assert listed.json()[0]["item_count"] == 1

    disabled_item = await client.post(
        f"{ADMIN}/{provider_id}/items/ats-preset:acme/disable", headers=auth_headers
    )
    assert disabled_item.status_code == 200
    detail = await client.get(f"{USER}/{provider_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["presets"] == []
    assert detail.json()["item_count"] == 0

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


CATALOG_PACK = (
    Path(__file__).parent / "fixtures" / "seed_packs" / "packs" / "neuronection" / "job-catalog"
)
CATALOG_ITEM_COUNTS = {
    "families": 19,
    "jobs": 45,
    "relations": 40,
    "paths": 8,
    "skills": 32,
    "interests": 46,
}


def _catalog_files() -> dict[str, bytes]:
    return {
        path.relative_to(CATALOG_PACK).as_posix(): path.read_bytes()
        for path in sorted(CATALOG_PACK.rglob("*.json"))
    }


async def test_admin_detail_reports_catalog_counts_and_edit_state(
    client, auth_headers, db, tmp_path, monkeypatch
):
    import app.services.seeds.provider_service as provider_module
    from app.services.seeds.catalog import mark_user_modified

    store = _store(tmp_path)
    monkeypatch.setattr(provider_module, "SeedPackStore", lambda: store)

    created = await client.post(
        ADMIN, headers=auth_headers, json=_file_provider(trust_tier="operator")
    )
    provider_id = created.json()["id"]
    uploaded = await client.post(
        f"{ADMIN}/{provider_id}/upload",
        headers=auth_headers,
        files={"file": ("catalog.zip", build_pack_archive(_catalog_files()), "application/zip")},
    )
    assert uploaded.status_code == 200, uploaded.text
    version_id = uploaded.json()["version_id"]
    await client.post(f"{ADMIN}/{provider_id}/versions/{version_id}/approve", headers=auth_headers)
    applied = await client.post(
        f"{ADMIN}/{provider_id}/versions/{version_id}/apply", headers=auth_headers
    )
    assert applied.status_code == 200, applied.text

    detail = await client.get(f"{ADMIN}/{provider_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert {key: body["item_counts"][key] for key in CATALOG_ITEM_COUNTS} == CATALOG_ITEM_COUNTS
    catalog = {entry["entity_type"]: entry for entry in body["catalog"]}
    assert set(catalog) == {
        "job_family",
        "job_type",
        "job_relation",
        "career_path",
        "skill",
        "interest_tag",
    }
    assert catalog["job_type"] == {
        "entity_type": "job_type",
        "active": 45,
        "retired": 0,
        "user_modified": 0,
    }
    listed = (await client.get(ADMIN, headers=auth_headers)).json()
    assert listed[0]["item_counts"]["jobs"] == 45

    jobs = (await db.execute(select(Job).order_by(Job.code))).scalars().all()
    retired = await db.scalar(
        select(SeedItemProvenance).where(
            SeedItemProvenance.entity_type == "job_type",
            SeedItemProvenance.entity_id == jobs[0].id,
        )
    )
    assert retired is not None
    retired.state = "retired"
    await mark_user_modified(db, "job_type", jobs[1].id)
    await db.commit()

    body = (await client.get(f"{ADMIN}/{provider_id}", headers=auth_headers)).json()
    assert body["item_counts"]["jobs"] == 44
    catalog = {entry["entity_type"]: entry for entry in body["catalog"]}
    assert catalog["job_type"] == {
        "entity_type": "job_type",
        "active": 44,
        "retired": 1,
        "user_modified": 1,
    }


async def test_a_preset_only_provider_reports_no_catalog_groups(
    client, auth_headers, db, tmp_path, monkeypatch
):
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
    await client.post(f"{ADMIN}/{provider_id}/versions/{version_id}/approve", headers=auth_headers)
    await client.post(f"{ADMIN}/{provider_id}/versions/{version_id}/apply", headers=auth_headers)
    body = (await client.get(f"{ADMIN}/{provider_id}", headers=auth_headers)).json()
    assert body["catalog"] == []
    assert body["item_counts"]["jobs"] == 0


async def test_official_catalog_install_syncs_applies_and_enables(
    client, auth_headers, db, tmp_path, monkeypatch
):
    import app.services.seeds.provider_service as provider_module
    from app.core.seed_pack.archive import build_pack_archive
    from app.core.seed_pack.manifest import compute_files_digest
    from app.models.seed_model import SeedSource, SeedSourceVersion
    from app.services.seeds.service import ProviderSyncService
    from tests.seed_pack_fixture import catalog_pack_files, fixture_store

    store = fixture_store(tmp_path)
    monkeypatch.setattr(provider_module, "SeedPackStore", lambda: store)

    files = catalog_pack_files()
    digest = compute_files_digest(files)
    source = SeedSource(
        name="Neuronection official — Job catalog",
        kind="git",
        uri="https://github.com/neuronection/career-assistant-seeds.git",
        ref_spec="v2026.11.25.3",
        subpath="packs/neuronection/job-catalog",
        priority=100,
        trust_tier="official",
        enabled=False,
        refresh_minutes=0,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    store.put(source.id, digest, build_pack_archive(files))
    version = SeedSourceVersion(
        source_id=source.id,
        digest=digest,
        manifest=json.loads(files["manifest.json"]),
        pack_version="1.0.0",
        schema_version="1.0",
        status="pending",
    )
    db.add(version)
    await db.commit()

    async def fake_sync(self, source_arg, *, trigger="manual", actor="system"):
        return {"status": "noop", "version_id": str(version.id), "code": None, "message": ""}

    monkeypatch.setattr(ProviderSyncService, "sync", fake_sync)

    response = await client.post(f"{ADMIN}/{source.id}/install", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "applied"
    assert body["counts"]["create"] > 0
    assert await db.scalar(select(Job)) is not None
    enabled = await db.scalar(select(SeedSource.enabled).where(SeedSource.id == source.id))
    assert enabled is True


async def test_one_click_install_is_reserved_for_official_tiles(client, auth_headers):
    created = await client.post(ADMIN, headers=auth_headers, json=_file_provider())
    response = await client.post(f"{ADMIN}/{created.json()['id']}/install", headers=auth_headers)
    assert response.status_code == 400
    assert "official" in response.json()["detail"]
