"""Boot provisioning for the seed-provider lane (plan 218).

Two providers exist without an admin click: the local bundled pack (the 20
baseline presets, auto-approved and applied when its digest changes) and the
official git provider tile (registered, disabled, pinned — enabling/checking
is an explicit admin act). Idempotent; safe to run on every seed pass.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed_pack.store import SeedPackStore
from app.models.seed_model import SeedSource, SeedSourceVersion
from app.services.seeds.applier import SeedApplyService
from app.services.seeds.service import ProviderSyncService

logger = logging.getLogger(__name__)

BUNDLED_SOURCE_NAME = "Bundled presets"
BUNDLED_SUBPATH = ""
BUNDLED_PRIORITY = 0

OFFICIAL_SOURCE_NAME = "Neuronection official"
OFFICIAL_REPO = "https://github.com/neuronection/career-assistant-seeds.git"
OFFICIAL_REF = "v2026.11.25.2"
OFFICIAL_SUBPATH = "packs/neuronection/greece-ats"
OFFICIAL_PRIORITY = 100


async def _ensure_bundled(db: AsyncSession, packs: SeedPackStore) -> dict[str, Any]:
    source = (
        await db.execute(
            select(SeedSource).where(
                SeedSource.kind == "bundled",
                SeedSource.name == BUNDLED_SOURCE_NAME,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        source = SeedSource(
            name=BUNDLED_SOURCE_NAME,
            kind="bundled",
            uri="",
            subpath=BUNDLED_SUBPATH,
            priority=BUNDLED_PRIORITY,
            scope="system",
            trust_tier="local",
            refresh_minutes=0,
            enabled=True,
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)

    report = await ProviderSyncService(db, packs=packs).sync(
        source, trigger="manual", actor="system"
    )
    await db.refresh(source)
    version = (
        await db.execute(
            select(SeedSourceVersion)
            .where(
                SeedSourceVersion.source_id == source.id,
                SeedSourceVersion.status == "approved",
            )
            .order_by(SeedSourceVersion.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if version is None:
        logger.warning("bundled provider has no approved version: %s", report.get("message"))
        return {"source_id": str(source.id), "status": "failed", "report": report}

    if source.current_version_id != version.id:
        result = await SeedApplyService(db, packs=packs).apply(source, version, actor="system")
        return {
            "source_id": str(source.id),
            "version_id": str(version.id),
            "status": result.status,
            "counts": result.counts,
        }
    return {
        "source_id": str(source.id),
        "version_id": str(version.id),
        "status": report.get("status", "noop"),
    }


async def _ensure_official(db: AsyncSession) -> SeedSource:
    source = (
        await db.execute(
            select(SeedSource).where(
                SeedSource.kind == "git",
                SeedSource.trust_tier == "official",
                SeedSource.subpath == OFFICIAL_SUBPATH,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        source = SeedSource(
            name=OFFICIAL_SOURCE_NAME,
            kind="git",
            uri=OFFICIAL_REPO,
            ref_spec=OFFICIAL_REF,
            subpath=OFFICIAL_SUBPATH,
            priority=OFFICIAL_PRIORITY,
            scope="system",
            trust_tier="official",
            refresh_minutes=0,
            enabled=False,
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
    elif not source.ref_spec:
        source.ref_spec = OFFICIAL_REF
        await db.commit()
    return source


async def ensure_seed_providers(
    db: AsyncSession, *, packs: SeedPackStore | None = None
) -> dict[str, Any]:
    """Create/refresh the bundled and official providers (idempotent)."""
    store = packs or SeedPackStore()
    bundled = await _ensure_bundled(db, store)
    official = await _ensure_official(db)
    return {
        "bundled": bundled,
        "official": {
            "source_id": str(official.id),
            "ref": official.ref_spec,
            "enabled": official.enabled,
        },
    }


__all__ = [
    "BUNDLED_PRIORITY",
    "BUNDLED_SOURCE_NAME",
    "OFFICIAL_PRIORITY",
    "OFFICIAL_REF",
    "OFFICIAL_REPO",
    "OFFICIAL_SOURCE_NAME",
    "OFFICIAL_SUBPATH",
    "ensure_seed_providers",
]
