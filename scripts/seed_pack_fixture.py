#!/usr/bin/env python
"""Install the released reference-banks and job-catalog packs from fixtures.

The app ships no catalog and no reference bank: a fresh instance loads both
from seed packs through the normal upload → approve → apply lane. Local
development, the demo seeder and the e2e smoke suite use this helper to drive
that lane with the fixture copies of the published packs, so they start from
the curated data without network access.

    python scripts/seed_pack_fixture.py

The reference banks are applied first: the catalog carries interest tags and
its planner needs the published category anchors. Each run is idempotent:
re-running syncs the same digest and the apply plans a no-op once the pack is
current.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

PACKS_ROOT = BACKEND / "tests" / "fixtures" / "seed_packs" / "packs" / "neuronection"


@dataclass(frozen=True)
class FixturePack:
    """One published pack's fixture copy and the provider row it installs as."""

    directory: str
    provider_name: str


REFERENCE_BANKS = FixturePack("reference-banks", "Fixture reference banks")
JOB_CATALOG = FixturePack("job-catalog", "Fixture job catalog")
INSTALL_ORDER = (REFERENCE_BANKS, JOB_CATALOG)


def _pack_files(pack: FixturePack) -> dict[str, bytes]:
    root = PACKS_ROOT / pack.directory
    if not (root / "manifest.json").exists():
        raise SystemExit(f"fixture pack not found at {root}")
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*.json"))
    }


async def _sync_pack(db, pack: FixturePack):
    """Upload (or restore) one fixture pack and return its approved version."""
    from sqlalchemy import select

    from app.core.seed_pack.archive import build_pack_archive
    from app.models.seed_model import SeedSource, SeedSourceVersion
    from app.services.seeds.applier import SeedApplyService
    from app.services.seeds.service import ProviderSyncService

    files = _pack_files(pack)
    source = (
        await db.execute(
            select(SeedSource).where(
                SeedSource.name == pack.provider_name, SeedSource.kind == "file"
            )
        )
    ).scalar_one_or_none()
    if source is None:
        source = SeedSource(
            name=pack.provider_name,
            kind="file",
            uri="",
            priority=100,
            trust_tier="operator",
            enabled=True,
            refresh_minutes=0,
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)

    report = await ProviderSyncService(db).upload_file(source, build_pack_archive(files))
    if report["status"] not in ("ok", "noop"):
        raise SystemExit(
            f"fixture pack sync failed: {report.get('code')} {report.get('message', '')}"
        )
    version = await db.get(SeedSourceVersion, uuid.UUID(str(report["version_id"])))
    assert version is not None
    if version.status == "pending":
        await SeedApplyService(db).approve(version)
    elif version.status != "approved":
        raise SystemExit(
            f"the fixture provider's version is {version.status!r}; "
            "revoke or remove it before reinstalling"
        )
    return source, version


async def _apply_pack(db, source, version) -> dict:
    from app.core.seed_pack.errors import SeedPackError
    from app.services.seeds.applier import SeedApplyService

    try:
        result = await SeedApplyService(db).apply(source, version)
    except SeedPackError as exc:
        raise SystemExit(f"fixture pack apply failed: {exc.code} {exc.detail}") from exc
    return result.as_dict()


async def install() -> dict:
    """Sync every fixture pack, then apply the banks before the catalog."""
    from app.core.database import AsyncSessionLocal

    results: list[tuple[str, dict]] = []
    async with AsyncSessionLocal() as db:
        prepared = [(pack, await _sync_pack(db, pack)) for pack in INSTALL_ORDER]
        for pack, (source, version) in prepared:
            results.append((pack.directory, await _apply_pack(db, source, version)))
    return {"packs": [{"name": name, **result} for name, result in results]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    result = asyncio.run(install())
    ok = True
    for pack in result["packs"]:
        counts = ", ".join(f"{key}={value}" for key, value in sorted(pack["counts"].items()))
        print(f"{pack['name']} fixture: {pack['status']} ({counts})")
        ok = ok and pack["status"] in ("applied", "noop")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
