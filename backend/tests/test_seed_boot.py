"""Plan 218: bundled/official provider boot provisioning."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from app.core.seed_pack.store import SeedPackStore
from app.models.seed_model import JobSourcePreset, SeedSource, SeedSourceVersion
from app.services.seeds.applier import SeedApplyService
from app.services.seeds.boot import OFFICIAL_REF, ensure_seed_providers, load_official_index
from app.storage.object_storage import LocalObjectStore, StorageConfig


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


def test_the_official_index_snapshot_is_well_formed():
    index = load_official_index()
    assert index["schema"] == 1
    assert index["repository"].startswith("https://")
    assert index["ref"]
    publisher = index["publisher"]
    paths = [pack["path"] for pack in index["packs"]]
    assert paths and len(paths) == len(set(paths))
    for pack in index["packs"]:
        slug = pack["path"].rsplit("/", 1)[-1]
        assert pack["path"] == f"packs/{publisher['id']}/{slug}"
        assert pack["name"].strip()


async def test_boot_provisions_the_bundled_and_official_providers(db, tmp_path):
    store = _store(tmp_path)
    first = await ensure_seed_providers(db, packs=store)
    assert first["bundled"]["status"] == "applied"
    assert [entry["subpath"] for entry in first["official"]] == [
        "packs/neuronection/greece-ats",
        "packs/neuronection/remote-boards",
    ]
    assert all(entry["ref"] == OFFICIAL_REF for entry in first["official"])
    assert all(entry["enabled"] is False for entry in first["official"])

    bundled = await db.scalar(select(SeedSource).where(SeedSource.kind == "bundled"))
    assert bundled is not None
    assert bundled.current_version_id is not None
    version = await db.get(SeedSourceVersion, bundled.current_version_id)
    assert version is not None and version.status == "approved"
    presets = (await db.execute(select(JobSourcePreset))).scalars().all()
    assert len(presets) == 20
    assert all(preset.enabled for preset in presets)
    assert all(preset.state == "active" for preset in presets)

    official = (
        (await db.execute(select(SeedSource).where(SeedSource.trust_tier == "official")))
        .scalars()
        .all()
    )
    assert len(official) == 2
    assert all(source.kind == "git" and not source.enabled for source in official)
    assert all(source.uri.endswith("career-assistant-seeds.git") for source in official)
    assert {source.name for source in official} == {
        "Neuronection official — Greece",
        "Neuronection official — Remote boards",
    }

    second = await ensure_seed_providers(db, packs=store)
    assert second["bundled"]["status"] == "noop"
    assert await db.scalar(select(func.count()).select_from(SeedSource)) == 3
    assert await db.scalar(select(func.count()).select_from(JobSourcePreset)) == 20


async def test_boot_upgrades_the_legacy_single_official_tile(db, tmp_path):
    legacy = SeedSource(
        name="Neuronection official",
        kind="git",
        uri="https://github.com/neuronection/career-assistant-seeds.git",
        ref_spec="",
        subpath="packs/neuronection/greece-ats",
        priority=100,
        scope="system",
        trust_tier="official",
        refresh_minutes=0,
        enabled=False,
    )
    db.add(legacy)
    await db.commit()

    await ensure_seed_providers(db, packs=_store(tmp_path))

    await db.refresh(legacy)
    assert legacy.name == "Neuronection official — Greece"
    assert legacy.ref_spec == OFFICIAL_REF
    assert await db.scalar(select(func.count()).select_from(SeedSource)) == 3


async def test_plan_preview_heals_a_missing_bundled_archive(db, tmp_path):
    store = _store(tmp_path)
    await ensure_seed_providers(db, packs=store)
    bundled = await db.scalar(select(SeedSource).where(SeedSource.kind == "bundled"))
    assert bundled is not None and bundled.current_version_id is not None
    version = await db.get(SeedSourceVersion, bundled.current_version_id)
    assert version is not None

    store.delete(bundled.id, version.digest)
    assert not store.has(bundled.id, version.digest)

    plan = await SeedApplyService(db, packs=store).build_plan(bundled, version, allow_pending=True)
    assert plan.status == "ok"
    assert store.has(bundled.id, version.digest)
