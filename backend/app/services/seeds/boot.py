"""Boot provisioning for the seed-provider lane (plan 218).

Two providers exist without an admin click: the local bundled pack (the 20
baseline presets, auto-approved and applied when its digest changes) and the
official git provider tile (registered, disabled, pinned — enabling/checking
is an explicit admin act). Idempotent; safe to run on every seed pass.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
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
OFFICIAL_INDEX_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "seed_packs" / "official" / "index.json"
)


def load_official_index() -> dict[str, Any]:
    """The pinned snapshot of the official repository's index (shipped as data).

    Startup never fetches, so boot cannot read ``seed-repo.json`` from the
    remote repository. ``scripts/sync_official_index.py`` regenerates this
    snapshot when the pin moves; adding an official pack is then a data
    change, not a code change.
    """
    return json.loads(OFFICIAL_INDEX_PATH.read_text(encoding="utf-8"))


_OFFICIAL = load_official_index()
OFFICIAL_REPO = str(_OFFICIAL["repository"])
OFFICIAL_REF = str(_OFFICIAL["ref"])
OFFICIAL_PRIORITY = 100
# One provider owns one pack (a version is one pack digest), so a repository
# that publishes several packs gets one disabled official tile per pack. Any
# other pack is added at runtime with POST /admin/providers/import.
OFFICIAL_PACKS: tuple[tuple[str, str], ...] = tuple(
    (str(pack["name"]), str(pack["path"])) for pack in _OFFICIAL["packs"]
)
OFFICIAL_SUBPATH = OFFICIAL_PACKS[0][1]


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


async def _ensure_official(db: AsyncSession) -> list[SeedSource]:
    """Register one disabled tile per official pack (idempotent)."""
    sources: list[SeedSource] = []
    for name, subpath in OFFICIAL_PACKS:
        source = (
            await db.execute(
                select(SeedSource).where(
                    SeedSource.kind == "git",
                    SeedSource.trust_tier == "official",
                    SeedSource.subpath == subpath,
                )
            )
        ).scalar_one_or_none()
        if source is None:
            source = SeedSource(
                name=name,
                kind="git",
                uri=OFFICIAL_REPO,
                ref_spec=OFFICIAL_REF,
                subpath=subpath,
                priority=OFFICIAL_PRIORITY,
                scope="system",
                trust_tier="official",
                refresh_minutes=0,
                enabled=False,
            )
            db.add(source)
            await db.commit()
            await db.refresh(source)
        else:
            if not source.ref_spec:
                source.ref_spec = OFFICIAL_REF
            if source.name == OFFICIAL_SOURCE_NAME:
                # the pre-multi-pack tile carried the generic name
                source.name = name
            await db.commit()
        sources.append(source)
    return sources


async def ensure_seed_providers(
    db: AsyncSession, *, packs: SeedPackStore | None = None
) -> dict[str, Any]:
    """Create/refresh the bundled and official providers (idempotent)."""
    store = packs or SeedPackStore()
    bundled = await _ensure_bundled(db, store)
    official = await _ensure_official(db)
    return {
        "bundled": bundled,
        "official": [
            {
                "source_id": str(source.id),
                "ref": source.ref_spec,
                "subpath": source.subpath,
                "enabled": source.enabled,
            }
            for source in official
        ],
    }


__all__ = [
    "BUNDLED_PRIORITY",
    "BUNDLED_SOURCE_NAME",
    "OFFICIAL_INDEX_PATH",
    "OFFICIAL_PACKS",
    "OFFICIAL_PRIORITY",
    "OFFICIAL_REF",
    "OFFICIAL_REPO",
    "OFFICIAL_SOURCE_NAME",
    "OFFICIAL_SUBPATH",
    "ensure_seed_providers",
    "load_official_index",
]
