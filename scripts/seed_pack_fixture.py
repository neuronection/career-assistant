#!/usr/bin/env python
"""Install the released job-catalog pack from its pinned test fixture.

The app ships no catalog (plan 224): a fresh instance loads it from a seed
pack through the normal upload → approve → apply lane. Local development, the
demo seeder and the e2e smoke suite use this helper to drive that lane with
the fixture copy of the published pack, so they start from the curated
catalog without network access.

    python scripts/seed_pack_fixture.py

The run is idempotent: re-running syncs the same digest and the apply plans a
no-op once the pack is current.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

FIXTURE_PACK = (
    BACKEND
    / "tests"
    / "fixtures"
    / "seed_packs"
    / "packs"
    / "neuronection"
    / "job-catalog"
)
PROVIDER_NAME = "Fixture job catalog"


def _pack_files() -> dict[str, bytes]:
    if not (FIXTURE_PACK / "manifest.json").exists():
        raise SystemExit(f"fixture pack not found at {FIXTURE_PACK}")
    return {
        path.relative_to(FIXTURE_PACK).as_posix(): path.read_bytes()
        for path in sorted(FIXTURE_PACK.rglob("*.json"))
    }


async def install() -> dict:
    """Apply the fixture catalog pack and return the apply result."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.core.seed_pack.archive import build_pack_archive
    from app.core.seed_pack.errors import SeedPackError
    from app.models.seed_model import SeedSource, SeedSourceVersion
    from app.services.seeds.applier import SeedApplyService
    from app.services.seeds.service import ProviderSyncService

    files = _pack_files()
    async with AsyncSessionLocal() as db:
        source = (
            await db.execute(
                select(SeedSource).where(
                    SeedSource.name == PROVIDER_NAME, SeedSource.kind == "file"
                )
            )
        ).scalar_one_or_none()
        if source is None:
            source = SeedSource(
                name=PROVIDER_NAME,
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

        report = await ProviderSyncService(db).upload_file(
            source, build_pack_archive(files)
        )
        if report["status"] not in ("ok", "noop"):
            raise SystemExit(
                f"fixture pack sync failed: {report.get('code')} {report.get('message', '')}"
            )
        version = await db.get(SeedSourceVersion, uuid.UUID(str(report["version_id"])))
        assert version is not None
        service = SeedApplyService(db)
        if version.status == "pending":
            await service.approve(version)
        elif version.status != "approved":
            raise SystemExit(
                f"the fixture provider's version is {version.status!r}; "
                "revoke or remove it before reinstalling"
            )
        try:
            result = await service.apply(source, version)
        except SeedPackError as exc:
            raise SystemExit(f"fixture pack apply failed: {exc.code} {exc.detail}") from exc
        return result.as_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    result = asyncio.run(install())
    counts = ", ".join(f"{key}={value}" for key, value in sorted(result["counts"].items()))
    print(f"catalog fixture: {result['status']} ({counts})")
    return 0 if result["status"] in ("applied", "noop") else 1


if __name__ == "__main__":
    raise SystemExit(main())
