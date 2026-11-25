"""Plan 218: planner/applier — approve, apply, conflicts, retire, provenance."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from app.core.errors import ConflictError, ValidationError
from app.core.seed_pack.archive import build_pack_archive
from app.core.seed_pack.errors import SeedPackError
from app.core.seed_pack.manifest import compute_files_digest, sha256_hex
from app.core.seed_pack.store import SeedPackStore
from app.models.background_job_model import BackgroundJob
from app.models.posting_model import JobSource
from app.models.seed_model import (
    JobSourcePreset,
    ProviderEndpoint,
    SeedDeferredRef,
    SeedImportRun,
    SeedImportRunItem,
    SeedItemProvenance,
    SeedSource,
    SeedSourceVersion,
)
from app.services.seeds.applier import SeedApplyService
from app.services.seeds.planner import ENTITY_ENDPOINT, ENTITY_PRESET
from app.storage.object_storage import LocalObjectStore, StorageConfig

KEY = "ats-preset:acme"
ENDPOINT_KEY = "endpoint:acme"


class _RecruiteeConfig(BaseModel):
    company: str = Field(min_length=1, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


class _Recruitee:
    key = "recruitee"
    domains = ("*.recruitee.com",)

    def validate_config(self, config: dict) -> dict:
        try:
            return _RecruiteeConfig.model_validate(config).model_dump(mode="json")
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc

    def manifest(self) -> dict:
        return {"domains": list(self.domains)}


class _AtsApi:
    key = "ats_api"
    domains = ("boards-api.greenhouse.io",)

    def validate_config(self, config: dict) -> dict:
        return {}

    def manifest(self) -> dict:
        return {"domains": list(self.domains)}


CONNECTORS = {"recruitee": _Recruitee(), "ats_api": _AtsApi()}


def _assemble(
    item_type: str, envelope: dict, version: str, priority: int = 100
) -> dict[str, bytes]:
    data = json.dumps(envelope, sort_keys=True).encode()
    path = f"items/{item_type}/acme.json"
    manifest = {
        "id": "test-pack",
        "schema_version": "1.0",
        "version": version,
        "license": "CC-BY-4.0",
        "scope": "system",
        "priority": priority,
        "item_files": [{"path": path, "sha256": sha256_hex(data)}],
    }
    return {"manifest.json": json.dumps(manifest, sort_keys=True).encode(), path: data}


def _preset_pack(
    name: str = "Acme",
    version: str = "1.0.0",
    *,
    items: list | None = None,
    priority: int = 100,
) -> dict[str, bytes]:
    preset_items = (
        [
            {
                "seed_key": KEY,
                "slug": "acme",
                "name": name,
                "connector_key": "recruitee",
                "platform": "Recruitee",
                "category": "ats",
                "country": "GR",
                "config": {"company": "acme"},
            }
        ]
        if items is None
        else items
    )
    envelope = {
        "metadata": {
            "item_type": "ats_presets",
            "format": "ats_presets",
            "format_version": 1,
            "dataset_vintage": "2026-11-24",
            "license": "CC-BY-4.0",
        },
        "items": preset_items,
    }
    return _assemble("ats_presets", envelope, version, priority)


def _endpoint_pack(version: str = "1.0.0") -> dict[str, bytes]:
    envelope = {
        "metadata": {
            "item_type": "endpoint_descriptors",
            "format": "endpoint_descriptors",
            "format_version": 1,
            "dataset_vintage": "2026-11-24",
            "license": "CC-BY-4.0",
        },
        "items": [
            {
                "seed_key": ENDPOINT_KEY,
                "label": "Acme jobs",
                "connector_key": "ats_api",
                "server": "https://boards-api.greenhouse.io",
                "method": "GET",
                "path": "/v1/boards/{org}/jobs",
                "auth": "none",
                "params": [{"name": "org", "required": True}],
            }
        ],
    }
    return _assemble("endpoint_descriptors", envelope, version)


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


async def _source(
    db, *, priority: int = 100, enabled: bool = True, kind: str = "file"
) -> SeedSource:
    source = SeedSource(
        name=f"Provider {uuid.uuid4().hex[:6]}",
        kind=kind,
        uri="",
        priority=priority,
        enabled=enabled,
        refresh_minutes=0,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def _version(
    db,
    store: SeedPackStore,
    source: SeedSource,
    files: dict[str, bytes],
    *,
    status: str = "approved",
    pack_version: str = "1.0.0",
) -> SeedSourceVersion:
    digest = compute_files_digest(files)
    store.put(source.id, digest, build_pack_archive(files))
    version = SeedSourceVersion(
        source_id=source.id,
        digest=digest,
        manifest=json.loads(files["manifest.json"]),
        pack_version=pack_version,
        schema_version="1.0",
        status=status,
        approved_at=datetime.now(UTC) if status == "approved" else None,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    return version


def _service(db, store: SeedPackStore) -> SeedApplyService:
    return SeedApplyService(db, packs=store, connectors=CONNECTORS)


async def _apply(db, store, source, version):
    return await _service(db, store).apply(source, version)


async def test_apply_creates_rows_provenance_and_advances_pointer(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    files = _preset_pack()
    version = await _version(db, store, source, files)

    result = await _apply(db, store, source, version)
    assert result.status == "applied"
    assert result.counts["create"] == 1

    preset = await db.scalar(select(JobSourcePreset))
    assert preset is not None
    assert preset.name == "Acme"
    assert preset.enabled is False
    assert preset.state == "active"
    assert preset.seed_source_version_id == version.id

    provenance = await db.scalar(select(SeedItemProvenance))
    assert provenance is not None
    assert provenance.entity_type == ENTITY_PRESET
    assert provenance.source_version_id == version.id
    assert provenance.state == "active"
    assert provenance.content_hash

    await db.refresh(source)
    assert source.current_version_id == version.id
    run = await db.scalar(select(SeedImportRun))
    assert run is not None and run.status == "applied" and run.mode == "apply"
    assert await db.scalar(select(func.count()).select_from(SeedImportRunItem)) == 1

    again = await _apply(db, store, source, version)
    assert again.status == "noop"
    assert again.counts["noop"] == 1
    assert await db.scalar(select(func.count()).select_from(JobSourcePreset)) == 1


async def test_update_changes_content_and_keeps_the_enable_overlay(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    v1 = await _version(db, store, source, _preset_pack("Acme", "1.0.0"))
    await _apply(db, store, source, v1)
    preset = await db.scalar(select(JobSourcePreset))
    preset.enabled = True
    await db.commit()

    v2 = await _version(db, store, source, _preset_pack("Acme Two", "2.0.0"))
    result = await _apply(db, store, source, v2)
    assert result.counts["update"] == 1
    await db.refresh(preset)
    assert preset.name == "Acme Two"
    assert preset.enabled is True
    await db.refresh(source)
    assert source.current_version_id == v2.id


async def test_equal_priority_conflict_refuses_every_write(db, tmp_path):
    store = _store(tmp_path)
    a = await _source(db, priority=100)
    va = await _version(db, store, a, _preset_pack("Alpha", "1.0.0"))
    await _apply(db, store, a, va)

    b = await _source(db, priority=100)
    vb = await _version(db, store, b, _preset_pack("Beta", "1.0.0"))
    b.current_version_id = vb.id
    await db.commit()

    result = await _apply(db, store, b, vb)
    assert result.status == "conflicted"
    assert result.counts.get("conflict", 0) == 0
    preset = await db.scalar(select(JobSourcePreset))
    assert preset.name == "Alpha"
    run = await db.scalar(select(SeedImportRun).where(SeedImportRun.status == "conflicted"))
    assert run is not None


async def test_higher_priority_wins_and_the_loser_is_recorded(db, tmp_path):
    store = _store(tmp_path)
    low = await _source(db, priority=100)
    v_low = await _version(db, store, low, _preset_pack("Low", "1.0.0"))
    await _apply(db, store, low, v_low)

    high = await _source(db, priority=150)
    v_high = await _version(db, store, high, _preset_pack("High", "1.0.0", priority=150))
    high.current_version_id = v_high.id
    await db.commit()

    result = await _apply(db, store, high, v_high)
    assert result.counts["update"] == 1
    assert result.counts["skip"] == 1
    preset = await db.scalar(select(JobSourcePreset))
    assert preset.name == "High"
    skipped = await db.scalar(select(SeedImportRunItem).where(SeedImportRunItem.action == "skip"))
    assert skipped is not None and skipped.seed_key == KEY


async def test_retire_then_revoke_restores_the_previous_version(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    v1 = await _version(db, store, source, _preset_pack("Acme", "1.0.0"))
    await _apply(db, store, source, v1)
    job_source = JobSource(key="acme", connector_key="recruitee", seed_item_key=KEY)
    db.add(job_source)
    await db.commit()

    v2 = await _version(db, store, source, _preset_pack("ignored", "2.0.0", items=[]))
    retired = await _apply(db, store, source, v2)
    assert retired.counts["retire"] == 1
    preset = await db.scalar(select(JobSourcePreset))
    assert preset.state == "retired"
    await db.refresh(job_source)
    assert job_source.support_status == "retired"

    service = _service(db, store)
    restored = await service.revoke(source, v2)
    assert restored.status in ("applied", "noop")
    await db.refresh(preset)
    assert preset.state == "active"
    assert preset.name == "Acme"
    await db.refresh(source)
    assert source.current_version_id == v1.id


async def test_partial_failure_keeps_the_pointer(db, tmp_path, monkeypatch):
    store = _store(tmp_path)
    source = await _source(db)
    version = await _version(db, store, source, _preset_pack())

    async def boom(self, item):
        raise RuntimeError("writer exploded")

    monkeypatch.setattr(SeedApplyService, "_apply_item", boom)
    result = await _apply(db, store, source, version)
    assert result.status == "failed"
    await db.refresh(source)
    assert source.current_version_id is None
    assert await db.scalar(select(func.count()).select_from(JobSourcePreset)) == 0
    failed = await db.scalar(select(SeedImportRun).where(SeedImportRun.status == "failed"))
    assert failed is not None


async def test_digest_drift_between_approve_and_apply(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    files = _preset_pack()
    version = await _version(db, store, source, files)
    key = store.object_key(source.id, version.digest)
    (tmp_path / "uploads" / key).write_bytes(build_pack_archive(_preset_pack("Other")))

    with pytest.raises(SeedPackError) as exc:
        await _apply(db, store, source, version)
    assert exc.value.code == "DIGEST_DRIFT"
    await db.refresh(source)
    assert source.current_version_id is None


async def test_overridden_rows_require_explicit_adoption(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    v1 = await _version(db, store, source, _preset_pack("Acme", "1.0.0"))
    await _apply(db, store, source, v1)
    preset = await db.scalar(select(JobSourcePreset))
    provenance = await db.scalar(select(SeedItemProvenance))
    preset.state = "overridden"
    provenance.user_modified = True
    await db.commit()

    v2 = await _version(db, store, source, _preset_pack("Acme Two", "2.0.0"))
    held = await _apply(db, store, source, v2)
    assert held.counts["override"] == 1
    await db.refresh(preset)
    assert preset.name == "Acme"

    adopted = await _service(db, store).adopt(source, v2)
    assert adopted.counts["update"] == 1
    await db.refresh(preset)
    assert preset.name == "Acme Two"
    await db.refresh(provenance)
    assert provenance.user_modified is False


async def test_deferred_references_land_on_apply(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    version = await _version(db, store, source, _preset_pack())
    ref = SeedDeferredRef(
        source_version_id=version.id,
        payload={"entity_type": ENTITY_PRESET, "seed_key": KEY},
        state="pending",
    )
    db.add(ref)
    await db.commit()

    await _apply(db, store, source, version)
    await db.refresh(ref)
    assert ref.state == "landed"


async def test_enable_overlay_and_manual_retire(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    version = await _version(db, store, source, _preset_pack())
    await _apply(db, store, source, version)
    service = _service(db, store)

    assert await service.set_enabled(ENTITY_PRESET, KEY, True) is True
    preset = await db.scalar(select(JobSourcePreset))
    assert preset.enabled is True

    job_source = JobSource(key="acme", connector_key="recruitee", seed_item_key=KEY)
    db.add(job_source)
    await db.commit()
    assert await service.retire_item(ENTITY_PRESET, KEY) is True
    await db.refresh(preset)
    assert preset.state == "retired"
    await db.refresh(job_source)
    assert job_source.support_status == "retired"


async def test_approve_reject_and_revoke_transitions(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    pending = await _version(db, store, source, _preset_pack(), status="pending")
    service = _service(db, store)

    await service.approve(pending)
    assert pending.status == "approved"
    with pytest.raises(SeedPackError):
        await service.approve(pending)
    with pytest.raises(SeedPackError):
        await service.reject(pending)

    other = await _version(db, store, source, _preset_pack("Other", "2.0.0"), status="pending")
    await service.reject(other, reason="not wanted")
    assert other.status == "rejected" and other.reason == "not wanted"

    await service.revoke(source, pending)
    assert pending.status == "revoked"
    await db.refresh(source)
    assert source.current_version_id is None


async def test_global_apply_lock_refuses_a_second_writer(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    version = await _version(db, store, source, _preset_pack())
    db.add(
        BackgroundJob(
            job_type="provider_apply",
            status="running",
            lock_key="provider_apply",
        )
    )
    await db.commit()

    with pytest.raises(ConflictError):
        await _apply(db, store, source, version)


async def test_endpoint_descriptors_apply(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    version = await _version(db, store, source, _endpoint_pack())
    result = await _apply(db, store, source, version)
    assert result.counts["create"] == 1

    endpoint = await db.scalar(select(ProviderEndpoint))
    assert endpoint is not None
    assert endpoint.server == "https://boards-api.greenhouse.io"
    assert endpoint.auth == "none"
    provenance = await db.scalar(
        select(SeedItemProvenance).where(SeedItemProvenance.entity_type == ENTITY_ENDPOINT)
    )
    assert provenance is not None
