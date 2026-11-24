"""Seed pack planner (plan 218 §3.6).

The planner diffs the effective source set against the applied catalog. The
winner per ``(entity_type, seed_key)`` is recomputed from the enabled,
approved versions (priority ascending); equal priority with different content
is a typed conflict that refuses the whole apply. Nothing here writes.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed_pack.archive import extract_pack_archive
from app.core.seed_pack.errors import PACK_ARCHIVE_MISSING, SeedPackError
from app.core.seed_pack.manifest import ParsedItem, ParsedPack, parse_pack
from app.core.seed_pack.store import SeedPackStore
from app.models.seed_model import (
    JobSourcePreset,
    MigrationArchive,
    ProviderEndpoint,
    SeedItemProvenance,
    SeedSource,
    SeedSourceVersion,
)

ENTITY_PRESET = "job_source_preset"
ENTITY_ENDPOINT = "provider_endpoint"
ENTITY_MODELS: Mapping[str, Any] = {
    ENTITY_PRESET: JobSourcePreset,
    ENTITY_ENDPOINT: ProviderEndpoint,
}
ITEM_ENTITY = {
    "ats_presets": ENTITY_PRESET,
    "endpoint_descriptors": ENTITY_ENDPOINT,
}

ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_NOOP = "noop"
ACTION_CONFLICT = "conflict"
ACTION_SKIP = "skip"
ACTION_OVERRIDE = "override"
ACTION_RETIRE = "retire"
ACTIONS = (
    ACTION_CREATE,
    ACTION_UPDATE,
    ACTION_NOOP,
    ACTION_CONFLICT,
    ACTION_SKIP,
    ACTION_OVERRIDE,
    ACTION_RETIRE,
)


@dataclass(frozen=True)
class PlannedItem:
    entity_type: str
    seed_key: str
    action: str
    payload: dict[str, Any]
    content_hash: str
    source_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None
    priority: int = 0
    current_id: uuid.UUID | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "seed_key": self.seed_key,
            "action": self.action,
            "content_hash": self.content_hash,
            "source_id": str(self.source_id) if self.source_id else None,
            "version_id": str(self.version_id) if self.version_id else None,
            "priority": self.priority,
            "current_id": str(self.current_id) if self.current_id else None,
            "reason": self.reason,
        }


@dataclass
class Plan:
    items: list[PlannedItem] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    candidate_source_id: uuid.UUID | None = None
    candidate_version_id: uuid.UUID | None = None

    @property
    def status(self) -> str:
        return "conflicted" if self.conflicts else "ok"

    @property
    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(ACTIONS, 0)
        for item in self.items:
            counts[item.action] = counts.get(item.action, 0) + 1
        return counts

    def by_action(self, action: str) -> list[PlannedItem]:
        return [item for item in self.items if item.action == action]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidate_source_id": str(self.candidate_source_id)
            if self.candidate_source_id
            else None,
            "candidate_version_id": (
                str(self.candidate_version_id) if self.candidate_version_id else None
            ),
            "counts": self.counts,
            "conflicts": self.conflicts,
            "items": [item.as_dict() for item in self.items],
        }


@dataclass(frozen=True)
class _Entry:
    source: SeedSource
    version: SeedSourceVersion
    parsed: ParsedPack


def _sort_key(source: SeedSource) -> tuple[int, float]:
    created = source.created_at.timestamp() if isinstance(source.created_at, datetime) else 0.0
    return (source.priority, created)


async def _files_for_version(
    db: AsyncSession,
    packs: SeedPackStore,
    source: SeedSource,
    version: SeedSourceVersion,
) -> dict[str, bytes]:
    data = packs.get(source.id, version.digest)
    if data is None and source.kind in ("git", "registry"):
        from app.services.seeds.service import ProviderSyncService

        await ProviderSyncService(db, packs=packs).sync(source, trigger="manual")
        data = packs.get(source.id, version.digest)
    if data is None and source.uri.startswith("migrated://"):
        archived = await db.scalar(
            select(MigrationArchive).where(
                MigrationArchive.key == f"seed-pack:{source.id}:{version.digest}"
            )
        )
        files = (archived.old_value or {}).get("files") if archived is not None else None
        if isinstance(files, dict):
            return {path: str(text).encode("utf-8") for path, text in files.items()}
    if data is None:
        raise SeedPackError(
            PACK_ARCHIVE_MISSING,
            f"no stored archive for {source.name} {version.digest}; sync the provider again",
        )
    return extract_pack_archive(data)


async def load_version(
    db: AsyncSession,
    packs: SeedPackStore,
    source: SeedSource,
    version: SeedSourceVersion,
    *,
    connectors: Mapping[str, Any] | None = None,
) -> ParsedPack:
    files = await _files_for_version(db, packs, source, version)
    return parse_pack(
        files,
        connectors=connectors,
        source_priority=source.priority,
        allow_unknown_formats=True,
    )


def _entity_for(item: ParsedItem) -> str | None:
    return ITEM_ENTITY.get(item.item_type)


async def build_plan(
    db: AsyncSession,
    packs: SeedPackStore,
    *,
    candidate: tuple[SeedSource, SeedSourceVersion] | None = None,
    connectors: Mapping[str, Any] | None = None,
    allow_pending: bool = False,
) -> Plan:
    """Recompute the effective source set and diff it against the catalog."""
    candidate_source_id = candidate[0].id if candidate else None
    candidate_version_id = candidate[1].id if candidate else None
    plan = Plan(
        candidate_source_id=candidate_source_id,
        candidate_version_id=candidate_version_id,
    )

    sources = (
        (await db.execute(select(SeedSource).where(SeedSource.enabled.is_(True)))).scalars().all()
    )
    entries: list[_Entry] = []
    seen_sources: set[uuid.UUID] = set()
    for source in sources:
        seen_sources.add(source.id)
        version: SeedSourceVersion | None
        if candidate is not None and source.id == candidate[0].id:
            version = candidate[1]
        elif source.current_version_id is not None:
            version = await db.get(SeedSourceVersion, source.current_version_id)
        else:
            version = None
        if version is None:
            continue
        is_candidate = candidate is not None and source.id == candidate[0].id
        if version.status != "approved" and not (is_candidate and allow_pending):
            continue
        entries.append(
            _Entry(
                source=source,
                version=version,
                parsed=await load_version(db, packs, source, version, connectors=connectors),
            )
        )
    if candidate is not None and candidate[0].id not in seen_sources:
        entries.append(
            _Entry(
                source=candidate[0],
                version=candidate[1],
                parsed=await load_version(
                    db, packs, candidate[0], candidate[1], connectors=connectors
                ),
            )
        )
    entries.sort(key=lambda entry: _sort_key(entry.source))

    winners: dict[tuple[str, str], tuple[_Entry, ParsedItem]] = {}
    losers: list[PlannedItem] = []
    for entry in entries:
        for item in entry.parsed.items:
            entity = _entity_for(item)
            if entity is None:
                continue
            key = (entity, item.seed_key)
            existing = winners.get(key)
            if existing is None:
                winners[key] = (entry, item)
                continue
            winner_entry, winner_item = existing
            if entry.source.priority > winner_entry.source.priority:
                winners[key] = (entry, item)
                losers.append(_skip_item(winner_entry, winner_item, "outranked"))
            elif entry.source.priority == winner_entry.source.priority:
                if item.content_hash == winner_item.content_hash:
                    losers.append(_skip_item(entry, item, "equal-priority duplicate"))
                else:
                    plan.conflicts.append(
                        {
                            "entity_type": entity,
                            "seed_key": item.seed_key,
                            "priority": entry.source.priority,
                            "source_ids": [
                                str(winner_entry.source.id),
                                str(entry.source.id),
                            ],
                            "content_hashes": [winner_item.content_hash, item.content_hash],
                        }
                    )
            else:
                losers.append(_skip_item(entry, item, "lower priority"))

    presets = {
        row.seed_key: row
        for row in (
            await db.execute(select(JobSourcePreset).where(JobSourcePreset.scope_key == "system"))
        )
        .scalars()
        .all()
    }
    endpoints = {
        row.seed_key: row
        for row in (
            await db.execute(select(ProviderEndpoint).where(ProviderEndpoint.scope_key == "system"))
        )
        .scalars()
        .all()
    }
    current: dict[tuple[str, str], Any] = {}
    current.update({(ENTITY_PRESET, key): row for key, row in presets.items()})
    current.update({(ENTITY_ENDPOINT, key): row for key, row in endpoints.items()})
    provenance = {
        (row.entity_type, row.entity_id): row
        for row in (await db.execute(select(SeedItemProvenance))).scalars().all()
    }

    for (entity, seed_key), (entry, item) in sorted(winners.items()):
        row = current.get((entity, seed_key))
        prov = provenance.get((entity, row.id)) if row is not None else None
        if row is None:
            action, reason = ACTION_CREATE, "new seed key"
        elif row.state == "overridden" or (prov is not None and prov.user_modified):
            action, reason = ACTION_OVERRIDE, "user-modified; explicit adoption required"
        elif row.state == "active" and prov is not None and prov.content_hash == item.content_hash:
            action, reason = ACTION_NOOP, "unchanged"
        else:
            action, reason = ACTION_UPDATE, "content changed"
        plan.items.append(
            PlannedItem(
                entity_type=entity,
                seed_key=seed_key,
                action=action,
                payload=item.payload,
                content_hash=item.content_hash,
                source_id=entry.source.id,
                version_id=entry.version.id,
                priority=entry.source.priority,
                current_id=row.id if row is not None else None,
                reason=reason,
            )
        )

    for (entity, seed_key), row in sorted(current.items()):
        if row.state != "active" or (entity, seed_key) in winners:
            continue
        prov = provenance.get((entity, row.id))
        plan.items.append(
            PlannedItem(
                entity_type=entity,
                seed_key=seed_key,
                action=ACTION_RETIRE,
                payload={},
                content_hash="",
                source_id=None,
                version_id=prov.source_version_id if prov else None,
                current_id=row.id,
                reason="no active approved source provides this key",
            )
        )

    plan.items.extend(losers)
    return plan


def _skip_item(entry: _Entry, item: ParsedItem, reason: str) -> PlannedItem:
    return PlannedItem(
        entity_type=_entity_for(item) or "",
        seed_key=item.seed_key,
        action=ACTION_SKIP,
        payload=item.payload,
        content_hash=item.content_hash,
        source_id=entry.source.id,
        version_id=entry.version.id,
        priority=entry.source.priority,
        reason=reason,
    )


__all__ = [
    "ACTIONS",
    "ACTION_CONFLICT",
    "ACTION_CREATE",
    "ACTION_NOOP",
    "ACTION_OVERRIDE",
    "ACTION_RETIRE",
    "ACTION_SKIP",
    "ACTION_UPDATE",
    "ENTITY_ENDPOINT",
    "ENTITY_MODELS",
    "ENTITY_PRESET",
    "Plan",
    "PlannedItem",
    "build_plan",
    "load_version",
]
