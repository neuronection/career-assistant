"""Plan 218: bundled/official provider boot provisioning."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from app.core.seed_pack.store import SeedPackStore
from app.models.seed_model import JobSourcePreset, SeedSource, SeedSourceVersion
from app.services.seeds.boot import OFFICIAL_REF, ensure_seed_providers
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


async def test_boot_provisions_the_bundled_and_official_providers(db, tmp_path):
    store = _store(tmp_path)
    first = await ensure_seed_providers(db, packs=store)
    assert first["bundled"]["status"] == "applied"
    assert first["official"]["enabled"] is False
    assert first["official"]["ref"] == OFFICIAL_REF

    bundled = await db.scalar(select(SeedSource).where(SeedSource.kind == "bundled"))
    assert bundled is not None
    assert bundled.current_version_id is not None
    version = await db.get(SeedSourceVersion, bundled.current_version_id)
    assert version is not None and version.status == "approved"
    presets = (await db.execute(select(JobSourcePreset))).scalars().all()
    assert len(presets) == 20
    assert all(preset.enabled for preset in presets)
    assert all(preset.state == "active" for preset in presets)

    official = await db.scalar(select(SeedSource).where(SeedSource.trust_tier == "official"))
    assert official is not None
    assert official.kind == "git"
    assert official.enabled is False
    assert official.uri.endswith("career-assistant-seeds.git")
    assert official.subpath == "packs/neuronection/greece-ats"

    second = await ensure_seed_providers(db, packs=store)
    assert second["bundled"]["status"] == "noop"
    assert await db.scalar(select(func.count()).select_from(SeedSource)) == 2
    assert await db.scalar(select(func.count()).select_from(JobSourcePreset)) == 20
