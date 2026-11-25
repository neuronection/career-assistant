"""Plan 218: provider sync, pending versions, locks and notifications."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from app.core.errors import ValidationError
from app.core.seed_pack.archive import build_pack_archive
from app.core.seed_pack.errors import SeedPackError
from app.core.seed_pack.manifest import compute_files_digest, parse_repo_index, sha256_hex
from app.core.seed_pack.store import SeedPackStore
from app.models.background_job_model import BackgroundJob
from app.models.engagement_model import Notification, NotificationKind
from app.models.identity_model import AuditEvent
from app.models.schedule_model import Schedule
from app.models.seed_model import SeedSource, SeedSourceVersion, SeedSyncRun
from app.models.user_model import User
from app.services.scheduler.runner import KIND_TASKS, SchedulerService
from app.services.seeds.git_transport import GitPack
from app.services.seeds.registry_transport import IndexFetch
from app.services.seeds.service import (
    ProviderSyncService,
    enqueue_due_provider_syncs,
)
from app.storage.object_storage import LocalObjectStore, StorageConfig

PACK_PATH = "packs/test/test-pack"


class _RecruiteeConfig(BaseModel):
    company: str = Field(min_length=1, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


class _FakeConnector:
    key = "recruitee"
    domains = ("*.recruitee.com",)

    def validate_config(self, config: dict) -> dict:
        try:
            return _RecruiteeConfig.model_validate(config).model_dump(mode="json")
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc

    def manifest(self) -> dict:
        return {"domains": list(self.domains)}


CONNECTORS = {"recruitee": _FakeConnector()}


def _files(name: str = "Acme") -> dict[str, bytes]:
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
    return json.dumps(
        {
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
        },
        sort_keys=True,
    ).encode()


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


async def _source(db, **overrides) -> SeedSource:
    source = SeedSource(
        name=overrides.pop("name", "Test provider"),
        kind=overrides.pop("kind", "file"),
        uri=overrides.pop("uri", ""),
        priority=overrides.pop("priority", 100),
        trust_tier=overrides.pop("trust_tier", "community"),
        enabled=overrides.pop("enabled", True),
        refresh_minutes=overrides.pop("refresh_minutes", 60),
        **overrides,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


class _FakeGit:
    def __init__(self, files: dict[str, bytes], sha: str = "a" * 40):
        self.files = files
        self.sha = sha

    async def fetch(self, uri: str, ref: str, subpath: str = "") -> GitPack:
        return GitPack(files=self.files, commit_sha=self.sha)


class _FakeRegistry:
    def __init__(
        self,
        files: dict[str, bytes] | None = None,
        *,
        status: int = 200,
        digest: str | None = None,
        partial: bool = False,
    ):
        self.files = files or _files()
        self.status = status
        self.index = parse_repo_index(_index_bytes(self.files, digest=digest))
        self.partial = partial

    async def fetch_index(self, uri: str, *, etag: str | None = None) -> IndexFetch:
        return IndexFetch(
            index=self.index if self.status == 200 else None,
            etag="e1",
            base_url="https://seed.test/repo",
            status=self.status,
        )

    async def fetch_pack(self, base_url: str, indexed):
        if self.partial:
            raise SeedPackError("REGISTRY_PARTIAL", "item fetch failed")
        return self.files


def _service(db, tmp_path: Path, **kw) -> ProviderSyncService:
    return ProviderSyncService(
        db,
        packs=_store(tmp_path),
        connectors=CONNECTORS,
        bundled_root=tmp_path / "bundled",
        **kw,
    )


async def test_upload_registers_pending_and_is_idempotent(db, tmp_path):
    source = await _source(db, kind="file")
    service = _service(db, tmp_path)
    archive = build_pack_archive(_files())

    report = await service.upload_file(source, archive)
    assert report["status"] == "ok"
    version = await db.scalar(select(SeedSourceVersion))
    assert version is not None and version.status == "pending"
    assert version.digest == compute_files_digest(_files())
    await db.refresh(source)
    assert source.last_check_at is not None

    duplicate = await service.upload_file(source, archive)
    assert duplicate["status"] == "noop"
    assert len((await db.execute(select(SeedSourceVersion))).scalars().all()) == 1
    runs = (await db.execute(select(SeedSyncRun).order_by(SeedSyncRun.started_at))).scalars().all()
    assert [run.status for run in runs] == ["ok", "noop"]


async def test_a_reused_pack_version_is_quarantined(db, tmp_path):
    source = await _source(db, kind="file")
    service = _service(db, tmp_path)
    assert (await service.upload_file(source, build_pack_archive(_files("Acme"))))["status"] == "ok"

    report = await service.upload_file(source, build_pack_archive(_files("Acme Two")))
    assert report["status"] == "failed"
    assert report["code"] == "VERSION_REUSED"
    rejected = (
        (await db.execute(select(SeedSourceVersion).where(SeedSourceVersion.status == "rejected")))
        .scalars()
        .all()
    )
    assert len(rejected) == 1 and rejected[0].reason == "VERSION_REUSED"


async def test_bundled_pack_is_auto_approved(db, tmp_path):
    pack_dir = tmp_path / "bundled" / "pack"
    (pack_dir / "items/ats_presets").mkdir(parents=True)
    for relative, data in _files().items():
        target = pack_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    source = await _source(db, kind="bundled", subpath="pack", refresh_minutes=0)

    report = await _service(db, tmp_path).sync(source)
    assert report["status"] == "ok"
    version = await db.scalar(select(SeedSourceVersion))
    assert version is not None
    assert version.status == "approved"
    assert version.approved_at is not None


async def test_a_resync_restores_a_missing_archive(db, tmp_path):
    source = await _source(db, kind="file")
    store = _store(tmp_path)
    service = ProviderSyncService(
        db, packs=store, connectors=CONNECTORS, bundled_root=tmp_path / "bundled"
    )
    archive = build_pack_archive(_files())
    assert (await service.upload_file(source, archive))["status"] == "ok"
    version = await db.scalar(select(SeedSourceVersion))
    assert version is not None
    assert store.has(source.id, version.digest)

    store.delete(source.id, version.digest)
    assert not store.has(source.id, version.digest)

    repaired = await service.upload_file(source, archive)
    assert repaired["status"] == "noop"
    assert store.has(source.id, version.digest)


async def test_bundled_resync_restores_a_missing_archive(db, tmp_path):
    pack_dir = tmp_path / "bundled" / "pack"
    (pack_dir / "items/ats_presets").mkdir(parents=True)
    for relative, data in _files().items():
        target = pack_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    source = await _source(db, kind="bundled", subpath="pack", refresh_minutes=0)
    store = _store(tmp_path)
    service = ProviderSyncService(
        db, packs=store, connectors=CONNECTORS, bundled_root=tmp_path / "bundled"
    )
    assert (await service.sync(source))["status"] == "ok"
    version = await db.scalar(select(SeedSourceVersion))
    assert version is not None

    store.delete(source.id, version.digest)
    assert not store.has(source.id, version.digest)

    assert (await service.sync(source))["status"] == "noop"
    assert store.has(source.id, version.digest)


async def test_registry_sync_pending_noop_and_drift(db, tmp_path):
    source = await _source(db, kind="registry", uri="https://seed.test/repo", subpath=PACK_PATH)
    service = _service(db, tmp_path, registry=_FakeRegistry())

    report = await service.sync(source)
    assert report["status"] == "ok"
    assert report["etag"] == "e1"
    await db.refresh(source)
    assert source.policy["registry_etag"] == "e1"
    assert (await db.scalar(select(SeedSourceVersion))).status == "pending"

    unchanged = _service(db, tmp_path, registry=_FakeRegistry(status=304))
    assert (await unchanged.sync(source))["status"] == "noop"
    assert len((await db.execute(select(SeedSourceVersion))).scalars().all()) == 1

    drifted = _service(db, tmp_path, registry=_FakeRegistry(digest=f"sha256:{'0' * 64}"))
    report = await drifted.sync(source)
    assert report["status"] == "failed"
    assert report["code"] == "DIGEST_DRIFT"

    partial = _service(db, tmp_path, registry=_FakeRegistry(partial=True))
    report = await partial.sync(source)
    assert report["status"] == "partial"
    assert report["code"] == "REGISTRY_PARTIAL"


async def test_git_sync_records_the_commit(db, tmp_path):
    source = await _source(
        db,
        kind="git",
        uri="https://github.com/example/seeds.git",
        ref_spec="v1",
        subpath="pack",
    )
    report = await _service(db, tmp_path, git=_FakeGit(_files())).sync(source)
    assert report["status"] == "ok"
    assert report["commit_sha"] == "a" * 40
    version = await db.scalar(select(SeedSourceVersion))
    assert version is not None and version.commit_sha == "a" * 40


async def test_notifications_and_audit_trail(db, tmp_path, kinds):
    admin = User(email="provider-admin@example.com", is_admin=True, full_name="Admin")
    db.add(admin)
    await db.commit()
    source = await _source(db, kind="file")
    service = _service(db, tmp_path)
    await service.upload_file(source, build_pack_archive(_files()))
    first_count = await db.scalar(select(func.count()).select_from(Notification))
    await service.upload_file(source, build_pack_archive(_files()))
    assert await db.scalar(select(func.count()).select_from(Notification)) == first_count

    keys = (
        (
            await db.execute(
                select(NotificationKind.key)
                .join(Notification, Notification.kind_id == NotificationKind.id)
                .where(Notification.kind_id == NotificationKind.id)
            )
        )
        .scalars()
        .all()
    )
    assert "provider_update_available" in keys

    actions = (await db.execute(select(AuditEvent.action))).scalars().all()
    assert "provider.version.pending" in actions


async def test_due_sweep_respects_the_per_source_lock(db, tmp_path):
    source = await _source(db, kind="file", refresh_minutes=60, last_check_at=None)
    assert await enqueue_due_provider_syncs(db) == 1
    job = await db.scalar(select(BackgroundJob).where(BackgroundJob.job_type == "provider_sync"))
    assert job is not None
    assert job.lock_key == f"provider_sync:{source.id}"
    assert await enqueue_due_provider_syncs(db) == 0

    job.status = "succeeded"
    source.last_check_at = datetime.now(UTC) - timedelta(hours=2)
    await db.commit()
    assert await enqueue_due_provider_syncs(db) == 1

    job.status = "succeeded"
    source.last_check_at = datetime.now(UTC)
    await db.commit()
    assert await enqueue_due_provider_syncs(db) == 0


async def test_scheduler_provisions_the_provider_sync_tick(db):
    await SchedulerService(db).ensure_system_schedules()
    schedule = (
        await db.execute(select(Schedule).where(Schedule.kind == "system_provider_sync"))
    ).scalar_one()
    assert schedule.task == "provider_sync"
    assert schedule.trigger["params"]["every_minutes"] == 60
    assert schedule.misfire_policy == "asap"
    assert KIND_TASKS["system_provider_sync"] == "provider_sync"
