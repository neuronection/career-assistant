"""Plan 218: official provider boot provisioning (no shipped seed content)."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.seed_model import JobSourcePreset, SeedSource
from app.services.seeds.boot import OFFICIAL_REF, ensure_seed_providers, load_official_index


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


async def test_boot_provisions_only_the_official_tiles(db):
    first = await ensure_seed_providers(db)
    assert [entry["subpath"] for entry in first["official"]] == [
        "packs/neuronection/greece-ats",
        "packs/neuronection/remote-boards",
        "packs/neuronection/job-catalog",
    ]
    assert all(entry["ref"] == OFFICIAL_REF for entry in first["official"])
    assert all(entry["enabled"] is False for entry in first["official"])

    official = (
        (await db.execute(select(SeedSource).where(SeedSource.trust_tier == "official")))
        .scalars()
        .all()
    )
    assert len(official) == 3
    assert all(source.kind == "git" and not source.enabled for source in official)
    assert all(source.uri.endswith("career-assistant-seeds.git") for source in official)
    assert {source.name for source in official} == {
        "Neuronection official — Greece",
        "Neuronection official — Remote boards",
        "Neuronection official — Job catalog",
    }

    # Nothing ships as catalog content: presets only appear after an admin
    # syncs, approves and applies a pack.
    assert await db.scalar(select(func.count()).select_from(JobSourcePreset)) == 0
    assert await db.scalar(select(func.count()).select_from(SeedSource)) == 3

    second = await ensure_seed_providers(db)
    assert await db.scalar(select(func.count()).select_from(SeedSource)) == 3
    assert [entry["subpath"] for entry in second["official"]] == [
        "packs/neuronection/greece-ats",
        "packs/neuronection/remote-boards",
        "packs/neuronection/job-catalog",
    ]


async def test_boot_upgrades_the_legacy_single_official_tile(db):
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

    await ensure_seed_providers(db)

    await db.refresh(legacy)
    assert legacy.name == "Neuronection official — Greece"
    assert legacy.ref_spec == OFFICIAL_REF
    assert await db.scalar(select(func.count()).select_from(SeedSource)) == 3
