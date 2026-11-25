"""Boot provisioning for the seed-provider lane (plan 218).

Nothing ships as seed *content*: the only rows boot creates are the official
repository's disabled tiles (registered, pinned — enabling, syncing and
approving is an explicit admin act). A pack reaches an instance when an admin
adds a Git/index provider or uploads a pack zip. Startup never fetches, so the
official tiles come from a shipped index snapshot. Idempotent; safe to run on
every seed pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.seed_model import SeedSource

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
# other pack is added at runtime with POST /admin/providers/import or a zip
# upload.
OFFICIAL_PACKS: tuple[tuple[str, str], ...] = tuple(
    (str(pack["name"]), str(pack["path"])) for pack in _OFFICIAL["packs"]
)
OFFICIAL_SUBPATH = OFFICIAL_PACKS[0][1]


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


async def ensure_seed_providers(db: AsyncSession) -> dict[str, Any]:
    """Register/refresh the official provider tiles (idempotent)."""
    official = await _ensure_official(db)
    return {
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
