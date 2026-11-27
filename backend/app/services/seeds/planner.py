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
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed_pack.archive import extract_pack_archive
from app.core.seed_pack.errors import (
    BANK_TRUST_DENIED,
    CATALOG_TRUST_DENIED,
    PACK_ARCHIVE_MISSING,
    PLAN_EMPTY,
    SeedPackError,
)
from app.core.seed_pack.manifest import (
    CATALOG_FORMATS,
    ParsedItem,
    ParsedPack,
    parse_pack,
)
from app.core.seed_pack.store import SeedPackStore
from app.models.seed_model import (
    JobSourcePreset,
    MigrationArchive,
    ProviderEndpoint,
    SeedItemProvenance,
    SeedSource,
    SeedSourceVersion,
)
from app.services.seeds.banks import (
    BANK_ENTITY_MODELS,
    BANK_ITEM_TYPES,
    ENTITY_ASSESSMENT_TEMPLATE,
    ENTITY_FORMATS,
    require_adapter,
    template_content_hash,
)
from app.services.seeds.banks import (
    ITEM_ENTITY as BANK_ITEM_ENTITY,
)
from app.services.seeds.banks import (
    load_current as load_bank_current,
)
from app.services.seeds.banks import (
    preview_fields as bank_preview_fields,
)
from app.services.seeds.catalog import (
    ENTITY_INTEREST,
    ENTITY_JOB_TYPE,
    natural_match,
)
from app.services.seeds.catalog import (
    ENTITY_MODELS as CATALOG_ENTITY_MODELS,
)
from app.services.seeds.catalog import (
    ITEM_ENTITY as CATALOG_ITEM_ENTITY,
)
from app.services.seeds.catalog import (
    load_current as load_catalog_current,
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
    **CATALOG_ITEM_ENTITY,
    **BANK_ITEM_ENTITY,
}
TRACKED_ENTITY_MODELS: Mapping[str, Any] = {
    **CATALOG_ENTITY_MODELS,
    **BANK_ENTITY_MODELS,
}
TRACKED_ITEM_TYPES = frozenset(CATALOG_ITEM_ENTITY) | BANK_ITEM_TYPES

ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_NOOP = "noop"
ACTION_CONFLICT = "conflict"
ACTION_SKIP = "skip"
ACTION_OVERRIDE = "override"
ACTION_RETIRE = "retire"
ACTION_DELETE = "delete"
ACTIONS = (
    ACTION_CREATE,
    ACTION_UPDATE,
    ACTION_NOOP,
    ACTION_CONFLICT,
    ACTION_SKIP,
    ACTION_OVERRIDE,
    ACTION_RETIRE,
    ACTION_DELETE,
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
    preview: dict[str, Any] | None = None

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
            "preview": self.preview,
        }


@dataclass
class Plan:
    items: list[PlannedItem] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
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
            "warnings": self.warnings,
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
        recovery = "upload the pack again" if source.kind == "file" else "sync the provider again"
        raise SeedPackError(
            PACK_ARCHIVE_MISSING,
            f"no stored archive for {source.name} {version.digest}; {recovery}",
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


def _guard_catalog_candidate(source: SeedSource, parsed: ParsedPack) -> None:
    """Type-check a candidate before any row is planned."""
    catalog_items = [item for item in parsed.items if item.item_type in CATALOG_ITEM_ENTITY]
    if catalog_items and source.trust_tier not in ("official", "operator"):
        raise SeedPackError(
            CATALOG_TRUST_DENIED,
            f"catalog packs require the official or operator trust tier, not {source.trust_tier!r}",
        )
    # Guard on the formats the pack declares, not only the items it parsed:
    # an empty bank file is still a bank pack (and may scope retirement), so
    # it must carry the trust tier and a registered adapter.
    bank_formats = [fmt for fmt in parsed.formats if fmt in BANK_ITEM_TYPES]
    if bank_formats and source.trust_tier not in ("official", "operator"):
        raise SeedPackError(
            BANK_TRUST_DENIED,
            f"bank packs require the official or operator trust tier, not {source.trust_tier!r}",
        )
    for fmt in bank_formats:
        require_adapter(fmt)
    if not parsed.items and any(fmt in CATALOG_FORMATS for fmt, _version in parsed.skipped_formats):
        raise SeedPackError(PLAN_EMPTY, "no catalog item could be read from this pack")


async def _provided_claims(
    db: AsyncSession,
    packs: SeedPackStore,
    connectors: Mapping[str, Any] | None,
    candidate: tuple[SeedSource, SeedSourceVersion] | None,
) -> set[tuple[str, str]]:
    """Keys provided by any approved current version, enabled or not (ADR-0056)."""
    claims: set[tuple[str, str]] = set()
    sources = (
        (await db.execute(select(SeedSource).where(SeedSource.current_version_id.is_not(None))))
        .scalars()
        .all()
    )
    for source in sources:
        if candidate is not None and source.id == candidate[0].id:
            continue
        version = await db.get(SeedSourceVersion, source.current_version_id)
        if version is None or version.status != "approved":
            continue
        parsed = await load_version(db, packs, source, version, connectors=connectors)
        claims.update(
            (ITEM_ENTITY[item.item_type], item.seed_key)
            for item in parsed.items
            if item.item_type in TRACKED_ITEM_TYPES
        )
    if candidate is not None and candidate[1].status == "approved":
        parsed = await load_version(db, packs, candidate[0], candidate[1], connectors=connectors)
        claims.update(
            (ITEM_ENTITY[item.item_type], item.seed_key)
            for item in parsed.items
            if item.item_type in TRACKED_ITEM_TYPES
        )
    return claims


def _apply_replaces(
    parsed: ParsedPack,
    winners: dict[tuple[str, str], tuple[_Entry, ParsedItem]],
    current: dict[tuple[str, str], Any],
    plan: Plan,
    renamed_old: set[tuple[str, str]],
) -> None:
    """Bind manifest-level `replaces` bodies to their single replacement item (ADR-0056)."""
    for body in parsed.manifest.replaces:
        old_rows = [
            (entity, key, row)
            for (entity, key), row in current.items()
            if entity in TRACKED_ENTITY_MODELS and key.split(":", 1)[1] == body
        ]
        if not old_rows:
            plan.warnings.append(
                {"code": "REPLACES_UNRESOLVED", "body": body, "detail": "no existing row"}
            )
            continue
        for entity, old_key, row in old_rows:
            prefix = old_key.split(":", 1)[0]
            candidates = [
                (key, item)
                for (winner_entity, key), (_entry, item) in winners.items()
                if winner_entity == entity and key.split(":", 1)[0] == prefix and key != old_key
            ]
            if len(candidates) != 1:
                plan.warnings.append(
                    {
                        "code": "REPLACES_AMBIGUOUS",
                        "body": body,
                        "detail": f"{len(candidates)} replacement candidates for {old_key}",
                    }
                )
                continue
            new_key, _item = candidates[0]
            current.setdefault((entity, new_key), row)
            renamed_old.add((entity, old_key))


async def _check_catalog_constraints(
    db: AsyncSession,
    winners: dict[tuple[str, str], tuple[_Entry, ParsedItem]],
    plan: Plan,
    current: dict[tuple[str, str], Any],
) -> None:
    """Plan-time title uniqueness and the RIASEC category law."""
    from app.core.job_titles import job_type_key
    from app.models.job_model import Job
    from app.seeds.metrics import CATEGORY_RIASEC

    titles: dict[str, str] = {}
    for (entity, seed_key), (_entry, item) in winners.items():
        if entity == ENTITY_JOB_TYPE:
            title_key = job_type_key(str(item.payload.get("title") or ""))[:200]
            if title_key:
                other = titles.get(title_key)
                if other is not None:
                    plan.conflicts.append(
                        {
                            "entity_type": entity,
                            "seed_key": seed_key,
                            "priority": 0,
                            "reason": f"duplicate job title with {other}",
                            "source_ids": [],
                            "content_hashes": [],
                        }
                    )
                else:
                    titles[title_key] = seed_key
                from sqlalchemy import and_, or_

                existing = (
                    (
                        await db.execute(
                            select(Job.id).where(
                                Job.title_key == title_key,
                                Job.status != "retired",
                                or_(
                                    and_(Job.seed_key.is_(None), Job.source != "seed"),
                                    Job.seed_key != seed_key,
                                ),
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if existing is not None:
                    plan.conflicts.append(
                        {
                            "entity_type": entity,
                            "seed_key": seed_key,
                            "priority": 0,
                            "reason": "job title collides with an existing job",
                            "source_ids": [],
                            "content_hashes": [],
                        }
                    )
        if entity == ENTITY_INTEREST:
            category = str(item.payload.get("category") or "")
            if category not in CATEGORY_RIASEC:
                plan.conflicts.append(
                    {
                        "entity_type": entity,
                        "seed_key": seed_key,
                        "priority": 0,
                        "reason": f"interest category {category!r} has no RIASEC anchor",
                        "source_ids": [],
                        "content_hashes": [],
                    }
                )
        if entity == ENTITY_JOB_TYPE:
            row = current.get((ENTITY_JOB_TYPE, seed_key))
            if row is not None:
                await _link_warnings(db, seed_key, row.id, item.payload, plan)


async def _link_warnings(
    db: AsyncSession,
    seed_key: str,
    job_id,
    payload: dict[str, Any],
    plan: Plan,
) -> None:
    """Non-seed links that already occupy a desired pair are kept, never replaced."""
    from app.models.job_model import JobSkill, JobTag
    from app.models.taxonomy_model import InterestTag, Skill

    for link in (
        (await db.execute(select(JobSkill).where(JobSkill.job_id == job_id))).scalars().all()
    ):
        if link.source == "seed":
            continue
        skill = await db.get(Skill, link.skill_id)
        if skill is not None and any(
            str(ref["skill_key"]) == skill.key for ref in payload.get("skills") or []
        ):
            plan.warnings.append(
                {
                    "code": "EDGE_OCCUPIED",
                    "entity_type": ENTITY_JOB_TYPE,
                    "seed_key": seed_key,
                    "detail": f"skill {skill.key} kept as {link.source}",
                }
            )
    for tag_link in (
        (await db.execute(select(JobTag).where(JobTag.job_id == job_id))).scalars().all()
    ):
        if tag_link.source == "seed":
            continue
        tag = await db.get(InterestTag, tag_link.interest_tag_id)
        if tag is not None and tag.key in {str(key) for key in payload.get("interests") or []}:
            plan.warnings.append(
                {
                    "code": "EDGE_OCCUPIED",
                    "entity_type": ENTITY_JOB_TYPE,
                    "seed_key": seed_key,
                    "detail": f"interest {tag.key} kept as {tag_link.source}",
                }
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

    candidate_parsed: ParsedPack | None = None
    if candidate is not None:
        candidate_parsed = await load_version(
            db, packs, candidate[0], candidate[1], connectors=connectors
        )
        _guard_catalog_candidate(candidate[0], candidate_parsed)

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
                parsed=(
                    cast(ParsedPack, candidate_parsed)
                    if candidate is not None and source.id == candidate[0].id
                    else await load_version(db, packs, source, version, connectors=connectors)
                ),
            )
        )
    if candidate is not None and candidate[0].id not in seen_sources:
        entries.append(
            _Entry(
                source=candidate[0],
                version=candidate[1],
                parsed=cast(ParsedPack, candidate_parsed),
            )
        )
    entries.sort(key=lambda entry: _sort_key(entry.source))
    bank_scope: set[str] = set()
    for entry in entries:
        bank_scope.update(fmt for fmt in entry.parsed.formats if fmt in BANK_ITEM_TYPES)

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
    catalog_current = await load_catalog_current(db)
    current.update(catalog_current)
    current.update(await load_bank_current(db))
    claimed = await _provided_claims(db, packs, connectors, candidate)
    claimed.update(key for key in winners if key[0] in TRACKED_ENTITY_MODELS)

    renamed_old: set[tuple[str, str]] = set()
    if candidate is not None and candidate_parsed is not None:
        _apply_replaces(candidate_parsed, winners, current, plan, renamed_old)

    await _check_catalog_constraints(db, winners, plan, current)

    for (entity, seed_key), (_entry, item) in sorted(winners.items()):
        if entity not in CATALOG_ENTITY_MODELS or (entity, seed_key) in current:
            continue
        adopted = await natural_match(db, entity, item.payload)
        if adopted is not None:
            current[(entity, seed_key)] = adopted

    for (entity, seed_key), (entry, item) in sorted(winners.items()):
        row = current.get((entity, seed_key))
        prov = provenance.get((entity, row.id)) if row is not None else None
        if row is None:
            action, reason = ACTION_CREATE, "new seed key"
        elif entity in CATALOG_ENTITY_MODELS:
            retired = getattr(row, "status", None) == "retired" or bool(
                getattr(row, "deprecated", False)
            )
            if getattr(row, "seed_key", None) != seed_key:
                action, reason = ACTION_UPDATE, "adopt existing seeded row"
            elif retired:
                action, reason = ACTION_UPDATE, "restore retired row"
            elif prov is not None and prov.user_modified:
                action, reason = ACTION_OVERRIDE, "user-modified; explicit adoption required"
            elif prov is not None and prov.content_hash == item.content_hash:
                action, reason = ACTION_NOOP, "unchanged"
            else:
                action, reason = ACTION_UPDATE, "content changed"
        elif entity in BANK_ENTITY_MODELS:
            if getattr(row, "seed_key", None) != seed_key:
                action, reason = ACTION_UPDATE, "adopt existing seeded row"
            elif getattr(row, "status", None) == "retired" or bool(
                getattr(row, "deprecated", False)
            ):
                action, reason = ACTION_UPDATE, "restore retired row"
            elif (
                entity == ENTITY_ASSESSMENT_TEMPLATE
                and getattr(row, "status", None) == "published"
                and getattr(row, "content_hash", None)
                and row.content_hash != template_content_hash(item.payload)
            ):
                plan.conflicts.append(
                    {
                        "entity_type": entity,
                        "seed_key": seed_key,
                        "priority": entry.source.priority,
                        "reason": "published template version is immutable; bump the version",
                        "source_ids": [str(entry.source.id)],
                        "content_hashes": [row.content_hash, item.content_hash],
                    }
                )
                continue
            elif prov is not None and prov.user_modified:
                action, reason = ACTION_OVERRIDE, "user-modified; explicit adoption required"
            elif prov is not None and prov.content_hash == item.content_hash:
                action, reason = ACTION_NOOP, "unchanged"
            else:
                action, reason = ACTION_UPDATE, "content changed"
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
                preview=(
                    bank_preview_fields(entity, item.payload)
                    if entity in BANK_ENTITY_MODELS
                    else None
                ),
            )
        )

    for (entity, seed_key), row in sorted(current.items()):
        if entity in TRACKED_ENTITY_MODELS:
            if (
                (entity, seed_key) in winners
                or (entity, seed_key) in claimed
                or (entity, seed_key) in renamed_old
            ):
                continue
            if getattr(row, "seed_key", None) is None:
                continue
            if entity in BANK_ENTITY_MODELS and ENTITY_FORMATS[entity] not in bank_scope:
                continue
            action = ACTION_DELETE if entity == "job_relation" else ACTION_RETIRE
            plan.items.append(
                PlannedItem(
                    entity_type=entity,
                    seed_key=seed_key,
                    action=action,
                    payload={},
                    content_hash="",
                    source_id=None,
                    version_id=None,
                    current_id=row.id,
                    reason="no approved source provides this key",
                    preview=(
                        bank_preview_fields(entity, {}, row)
                        if entity in BANK_ENTITY_MODELS
                        else None
                    ),
                )
            )
            continue
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
