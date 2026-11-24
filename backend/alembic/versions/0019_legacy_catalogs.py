"""Fold the plan-187 ATS catalogs into the seed-provider lane (plan 218).

`posting.sources.catalogs` (one `app_settings` row) held hand-imported
catalogs. This self-contained data migration synthesizes a v1 seed pack per
catalog, writes an approved `file` provider at priority 90, inserts the
catalog rows/provenance directly, and archives the exact v1 blob for the
downgrade. It imports no `app.*` modules: SQLAlchemy Core tables + stdlib only.

Invalid catalogs are quarantined (`rejected` version, no rows); the upgrade
never aborts. The synthesized pack files are also archived (`migration_archive`)
so the planner can replan a migrated provider without an object-store entry.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-25
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATALOG_SETTING_KEY = "posting.sources.catalogs"
LEGACY_PRIORITY = 90
LICENSES = {"Apache-2.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "MIT"}
_SEED_BODY = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,119}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")

_JSON = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")

app_settings = sa.table(
    "app_settings",
    sa.column("id", sa.Uuid(as_uuid=True)),
    sa.column("key", sa.String),
    sa.column("value", _JSON),
    sa.column("description", sa.String),
)
seed_sources = sa.table(
    "seed_sources",
    sa.column("id", sa.Uuid(as_uuid=True)),
    sa.column("name", sa.String),
    sa.column("kind", sa.String),
    sa.column("uri", sa.String),
    sa.column("ref_spec", sa.String),
    sa.column("subpath", sa.String),
    sa.column("priority", sa.Integer),
    sa.column("scope", sa.String),
    sa.column("trust_tier", sa.String),
    sa.column("refresh_minutes", sa.Integer),
    sa.column("enabled", sa.Boolean),
    sa.column("current_version_id", sa.Uuid(as_uuid=True)),
    sa.column("last_check_at", sa.DateTime(timezone=True)),
    sa.column("last_error", sa.Text),
    sa.column("policy", _JSON),
)
seed_source_versions = sa.table(
    "seed_source_versions",
    sa.column("id", sa.Uuid(as_uuid=True)),
    sa.column("source_id", sa.Uuid(as_uuid=True)),
    sa.column("commit_sha", sa.String),
    sa.column("etag", sa.String),
    sa.column("digest", sa.String),
    sa.column("manifest", _JSON),
    sa.column("pack_version", sa.String),
    sa.column("schema_version", sa.String),
    sa.column("vintage", sa.String),
    sa.column("status", sa.String),
    sa.column("reason", sa.Text),
    sa.column("contract_version", sa.String),
    sa.column("approved_by", sa.Uuid(as_uuid=True)),
    sa.column("approved_at", sa.DateTime(timezone=True)),
)
job_source_presets = sa.table(
    "job_source_presets",
    sa.column("id", sa.Uuid(as_uuid=True)),
    sa.column("scope_key", sa.String),
    sa.column("seed_key", sa.String),
    sa.column("slug", sa.String),
    sa.column("name", sa.String),
    sa.column("connector_key", sa.String),
    sa.column("platform", sa.String),
    sa.column("category", sa.String),
    sa.column("country", sa.String),
    sa.column("countries", _JSON),
    sa.column("regions", _JSON),
    sa.column("worldwide", sa.Boolean),
    sa.column("languages", _JSON),
    sa.column("work_modes", _JSON),
    sa.column("homepage", sa.String),
    sa.column("openings", sa.Integer),
    sa.column("verified_at", sa.Date),
    sa.column("config", _JSON),
    sa.column("enabled", sa.Boolean),
    sa.column("state", sa.String),
    sa.column("seed_source_version_id", sa.Uuid(as_uuid=True)),
)
provider_endpoints = sa.table(
    "provider_endpoints",
    sa.column("id", sa.Uuid(as_uuid=True)),
    sa.column("scope_key", sa.String),
    sa.column("seed_key", sa.String),
    sa.column("label", sa.String),
    sa.column("connector_key", sa.String),
    sa.column("platform", sa.String),
    sa.column("server", sa.String),
    sa.column("method", sa.String),
    sa.column("path", sa.String),
    sa.column("auth", sa.String),
    sa.column("params", _JSON),
    sa.column("countries", _JSON),
    sa.column("regions", _JSON),
    sa.column("worldwide", sa.Boolean),
    sa.column("languages", _JSON),
    sa.column("docs_url", sa.String),
    sa.column("state", sa.String),
    sa.column("seed_source_version_id", sa.Uuid(as_uuid=True)),
)
seed_item_provenance = sa.table(
    "seed_item_provenance",
    sa.column("id", sa.Uuid(as_uuid=True)),
    sa.column("entity_type", sa.String),
    sa.column("entity_id", sa.Uuid(as_uuid=True)),
    sa.column("source_version_id", sa.Uuid(as_uuid=True)),
    sa.column("seed_key", sa.String),
    sa.column("content_hash", sa.String),
    sa.column("state", sa.String),
    sa.column("user_modified", sa.Boolean),
    sa.column("applied_at", sa.DateTime(timezone=True)),
)
migration_archive = sa.table(
    "migration_archive",
    sa.column("id", sa.Uuid(as_uuid=True)),
    sa.column("key", sa.String),
    sa.column("old_value", _JSON),
)


class _InvalidCatalog(ValueError):
    pass


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _pack_digest(manifest: dict, files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    digest.update(_canonical(manifest))
    for entry in manifest["item_files"]:
        digest.update(b"\0")
        digest.update(entry["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[entry["path"]])
    return f"sha256:{digest.hexdigest()}"


def _safe(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", str(value).lower()).strip("-")
    return cleaned[:60] or _sha(str(value).encode())[:12]


def _seed_body(value: str) -> str:
    body = re.sub(r"[^a-z0-9._/-]+", "-", str(value).lower()).strip("-")
    if not _SEED_BODY.fullmatch(body):
        raise _InvalidCatalog(f"invalid seed-key body {value!r}")
    return body


def _date(value) -> date | None:
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[:10]):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _license(value) -> str:
    return value if isinstance(value, str) and value in LICENSES else "CC-BY-4.0"


def _preset_item(raw: dict) -> dict:
    slug = str(raw.get("slug") or "")
    if not _SLUG.fullmatch(slug):
        raise _InvalidCatalog(f"invalid preset slug {slug!r}")
    connector = str(raw.get("connectorKey") or "")
    if not connector:
        raise _InvalidCatalog(f"preset {slug} has no connectorKey")
    category = raw.get("category")
    if category not in ("ats", "remote"):
        raise _InvalidCatalog(f"preset {slug} has an invalid category")
    country = raw.get("country")
    if country is not None and not re.fullmatch(r"[A-Z]{2}", str(country)):
        raise _InvalidCatalog(f"preset {slug} has an invalid country")
    if category == "ats" and not country:
        raise _InvalidCatalog(f"preset {slug} is ats without a country")
    config = raw.get("config") or {}
    if not isinstance(config, dict):
        raise _InvalidCatalog(f"preset {slug} has a non-object config")
    item = {
        "seed_key": f"ats-preset:{slug}",
        "slug": slug,
        "name": str(raw.get("name") or slug)[:200],
        "connector_key": connector[:80],
        "platform": str(raw.get("provider") or "")[:80],
        "category": category,
        "config": {str(key)[:80]: str(value)[:500] for key, value in config.items()},
    }
    if country:
        item["country"] = str(country)
        item["countries"] = [str(country)]
    if category == "remote":
        item["worldwide"] = True
        item["languages"] = ["en"]
        item["work_modes"] = ["remote"]
    if isinstance(raw.get("openings"), int) and raw["openings"] >= 0:
        item["openings"] = raw["openings"]
    verified = _date(raw.get("verifiedAt"))
    if verified is not None:
        item["verified_at"] = verified.isoformat()
    return item


def _endpoint_item(raw: dict) -> dict | None:
    key = raw.get("id")
    if not key:
        return None
    body = _seed_body(key)
    connector = str(raw.get("connectorKey") or "")
    if not connector:
        raise _InvalidCatalog(f"endpoint {key} has no connectorKey")
    template = raw.get("urlTemplate")
    if not isinstance(template, str):
        return None
    parts = urlsplit(template)
    if parts.scheme != "https" or not parts.netloc:
        raise _InvalidCatalog(f"endpoint {key} is not https")
    path = parts.path or "/"
    if ".." in path:
        raise _InvalidCatalog(f"endpoint {key} has a traversal path")
    if parts.query:
        path = f"{path}?{parts.query}"
    countries = [
        str(value)
        for value in (raw.get("countries") or [])
        if re.fullmatch(r"[A-Z]{2}", str(value))
    ]
    docs = raw.get("docsUrl")
    return {
        "seed_key": f"endpoint:{body}",
        "label": str(raw.get("label") or key)[:200],
        "connector_key": connector[:80],
        "platform": "",
        "server": f"https://{parts.netloc}"[:400],
        "method": "GET",
        "path": path[:400],
        "auth": "none",
        "params": [],
        "countries": countries,
        "regions": [],
        "worldwide": False,
        "languages": [],
        "docs_url": str(docs) if isinstance(docs, str) and docs.startswith("https://") else None,
    }


def _archive(bind, key: str, value: dict) -> None:
    bind.execute(migration_archive.insert().values(id=uuid.uuid4(), key=key[:200], old_value=value))


def _quarantine(bind, catalog: dict, reason: str, now: datetime) -> None:
    catalog_id = _safe(str(catalog.get("id") or "unknown"))
    source_id = uuid.uuid5(uuid.NAMESPACE_URL, f"legacy-rejected:{catalog_id}")
    raw = _canonical(catalog)
    digest = f"sha256:{_sha(raw)}"
    bind.execute(
        seed_sources.insert().values(
            id=source_id,
            name=str(catalog.get("name") or f"Legacy catalog {catalog_id}")[:120],
            kind="file",
            uri=f"migrated://{catalog_id}",
            ref_spec="",
            subpath="",
            priority=LEGACY_PRIORITY,
            scope="system",
            trust_tier="operator",
            refresh_minutes=0,
            enabled=False,
            last_error=reason[:2000],
            policy={"migrated": True, "rejected": True},
        )
    )
    bind.execute(
        seed_source_versions.insert().values(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"legacy-rejected-version:{source_id}:{digest}"),
            source_id=source_id,
            commit_sha="",
            etag="",
            digest=digest,
            manifest={"legacy": catalog},
            pack_version="0.0.0",
            schema_version="1.0",
            status="rejected",
            reason=reason[:2000],
            contract_version="1.0",
            approved_at=None,
        )
    )
    _archive(bind, f"legacy-catalog:{catalog_id}", {"catalog": catalog, "rejected": reason})


def _fold_catalog(bind, catalog: dict, now: datetime) -> dict:
    if not isinstance(catalog, dict):
        raise _InvalidCatalog("catalog is not an object")
    catalog_id = _safe(str(catalog.get("id") or "catalog"))
    presets_raw = catalog.get("presets") or []
    providers_raw = catalog.get("providers") or []
    if not isinstance(presets_raw, list) or not isinstance(providers_raw, list):
        raise _InvalidCatalog("presets/providers must be arrays")
    presets = [_preset_item(item) for item in presets_raw if isinstance(item, dict)]
    if len(presets) != len(presets_raw):
        raise _InvalidCatalog("a preset is not an object")
    endpoints = [
        endpoint
        for endpoint in (_endpoint_item(item) for item in providers_raw if isinstance(item, dict))
        if endpoint is not None
    ]
    if not presets and not endpoints:
        raise _InvalidCatalog("catalog has no items")

    license_name = _license(catalog.get("license"))
    vintage = _date(catalog.get("updatedAt")) or now.date()
    files: dict[str, bytes] = {}
    item_files: list[dict] = []
    for fmt, items in (("ats_presets", presets), ("endpoint_descriptors", endpoints)):
        if not items:
            continue
        envelope = {
            "metadata": {
                "item_type": fmt,
                "format": fmt,
                "format_version": 1,
                "dataset_vintage": vintage.isoformat(),
                "license": license_name,
                "attribution": str(catalog.get("name") or catalog_id)[:300],
            },
            "items": items,
        }
        data = _canonical(envelope)
        path = f"items/{fmt}/legacy.json"
        files[path] = data
        item_files.append({"path": path, "sha256": _sha(data)})
    manifest = {
        "id": f"legacy-{catalog_id}"[:64],
        "schema_version": "1.0",
        "version": "0.0.1",
        "license": license_name,
        "scope": "system",
        "priority": LEGACY_PRIORITY,
        "description": f"Migrated from a stored ATS catalog ({catalog_id}).",
        "item_files": item_files,
    }
    digest = _pack_digest(manifest, files)
    source_id = uuid.uuid5(uuid.NAMESPACE_URL, f"legacy-source:{catalog_id}")
    version_id = uuid.uuid5(uuid.NAMESPACE_URL, f"legacy-version:{source_id}:{digest}")

    bind.execute(
        seed_sources.insert().values(
            id=source_id,
            name=str(catalog.get("name") or f"Legacy catalog {catalog_id}")[:120],
            kind="file",
            uri=f"migrated://{catalog_id}",
            ref_spec="",
            subpath="",
            priority=LEGACY_PRIORITY,
            scope="system",
            trust_tier="operator",
            refresh_minutes=0,
            enabled=True,
            current_version_id=None,
            last_error="",
            policy={"migrated": True},
        )
    )
    bind.execute(
        seed_source_versions.insert().values(
            id=version_id,
            source_id=source_id,
            commit_sha="",
            etag="",
            digest=digest,
            manifest=manifest,
            pack_version="0.0.1",
            schema_version="1.0",
            status="approved",
            reason="migrated from plan 187 admin import",
            contract_version="1.0",
            approved_at=now,
        )
    )
    bind.execute(
        sa.update(seed_sources)
        .where(seed_sources.c.id == source_id)
        .values(current_version_id=version_id)
    )
    for item in presets:
        entity_id = uuid.uuid5(uuid.NAMESPACE_URL, f"ats-preset:{item['slug']}")
        bind.execute(
            job_source_presets.insert().values(
                id=entity_id,
                scope_key="system",
                seed_key=item["seed_key"],
                slug=item["slug"],
                name=item["name"],
                connector_key=item["connector_key"],
                platform=item["platform"],
                category=item["category"],
                country=item.get("country"),
                countries=item.get("countries") or [],
                regions=[],
                worldwide=bool(item.get("worldwide")),
                languages=item.get("languages") or [],
                work_modes=item.get("work_modes") or [],
                homepage=None,
                openings=item.get("openings"),
                verified_at=_date(item.get("verified_at")),
                config=item.get("config") or {},
                enabled=True,
                state="active",
                seed_source_version_id=version_id,
            )
        )
        bind.execute(
            seed_item_provenance.insert().values(
                id=uuid.uuid4(),
                entity_type="job_source_preset",
                entity_id=entity_id,
                source_version_id=version_id,
                seed_key=item["seed_key"],
                content_hash=_sha(_canonical(item)),
                state="active",
                user_modified=False,
                applied_at=now,
            )
        )
    for item in endpoints:
        entity_id = uuid.uuid5(uuid.NAMESPACE_URL, f"endpoint:{item['seed_key'].split(':', 1)[1]}")
        bind.execute(
            provider_endpoints.insert().values(
                id=entity_id,
                scope_key="system",
                seed_key=item["seed_key"],
                label=item["label"],
                connector_key=item["connector_key"],
                platform=item["platform"],
                server=item["server"],
                method=item["method"],
                path=item["path"],
                auth=item["auth"],
                params=[],
                countries=item.get("countries") or [],
                regions=[],
                worldwide=False,
                languages=[],
                docs_url=item.get("docs_url"),
                state="active",
                seed_source_version_id=version_id,
            )
        )
        bind.execute(
            seed_item_provenance.insert().values(
                id=uuid.uuid4(),
                entity_type="provider_endpoint",
                entity_id=entity_id,
                source_version_id=version_id,
                seed_key=item["seed_key"],
                content_hash=_sha(_canonical(item)),
                state="active",
                user_modified=False,
                applied_at=now,
            )
        )
    _archive(
        bind,
        f"seed-pack:{source_id}:{digest}",
        {"files": {path: data.decode("utf-8") for path, data in files.items()}},
    )
    _archive(bind, f"legacy-catalog:{catalog_id}", {"catalog": catalog})
    return {"source_id": source_id, "digest": digest, "presets": len(presets)}


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.select(app_settings.c.value, app_settings.c.description).where(
            app_settings.c.key == CATALOG_SETTING_KEY
        )
    ).first()
    if row is None:
        return
    value, description = row[0], row[1]
    catalogs = value.get("catalogs") if isinstance(value, dict) else None
    now = datetime.now(UTC)
    _archive(
        bind,
        CATALOG_SETTING_KEY,
        {"value": value, "description": description},
    )
    if isinstance(catalogs, list):
        for catalog in catalogs:
            try:
                with bind.begin_nested():
                    _fold_catalog(bind, catalog, now)
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                try:
                    with bind.begin_nested():
                        _quarantine(bind, catalog if isinstance(catalog, dict) else {}, reason, now)
                except Exception:
                    pass
    bind.execute(sa.delete(app_settings).where(app_settings.c.key == CATALOG_SETTING_KEY))


def downgrade() -> None:
    bind = op.get_bind()
    archived = bind.execute(
        sa.select(migration_archive.c.old_value).where(
            migration_archive.c.key == CATALOG_SETTING_KEY
        )
    ).first()
    migrated_sources = [
        row[0]
        for row in bind.execute(
            sa.select(seed_sources.c.id).where(seed_sources.c.uri.like("migrated://%"))
        )
    ]
    for source_id in migrated_sources:
        version_ids = [
            row[0]
            for row in bind.execute(
                sa.select(seed_source_versions.c.id).where(
                    seed_source_versions.c.source_id == source_id
                )
            )
        ]
        if version_ids:
            preset_ids = [
                row[0]
                for row in bind.execute(
                    sa.select(job_source_presets.c.id).where(
                        job_source_presets.c.seed_source_version_id.in_(version_ids)
                    )
                )
            ]
            endpoint_ids = [
                row[0]
                for row in bind.execute(
                    sa.select(provider_endpoints.c.id).where(
                        provider_endpoints.c.seed_source_version_id.in_(version_ids)
                    )
                )
            ]
            if preset_ids:
                bind.execute(
                    sa.delete(seed_item_provenance).where(
                        seed_item_provenance.c.entity_id.in_(preset_ids)
                    )
                )
            if endpoint_ids:
                bind.execute(
                    sa.delete(seed_item_provenance).where(
                        seed_item_provenance.c.entity_id.in_(endpoint_ids)
                    )
                )
            bind.execute(
                sa.delete(job_source_presets).where(
                    job_source_presets.c.seed_source_version_id.in_(version_ids)
                )
            )
            bind.execute(
                sa.delete(provider_endpoints).where(
                    provider_endpoints.c.seed_source_version_id.in_(version_ids)
                )
            )
            bind.execute(
                sa.delete(seed_source_versions).where(seed_source_versions.c.id.in_(version_ids))
            )
        bind.execute(sa.delete(seed_sources).where(seed_sources.c.id == source_id))
    bind.execute(
        sa.delete(migration_archive).where(
            sa.or_(
                migration_archive.c.key == CATALOG_SETTING_KEY,
                migration_archive.c.key.like("legacy-catalog:%"),
                migration_archive.c.key.like("seed-pack:%"),
            )
        )
    )
    if archived is not None:
        old = archived[0] if isinstance(archived[0], dict) else {}
        bind.execute(sa.delete(app_settings).where(app_settings.c.key == CATALOG_SETTING_KEY))
        bind.execute(
            app_settings.insert().values(
                id=uuid.uuid4(),
                key=CATALOG_SETTING_KEY,
                value=old.get("value", {}),
                description=old.get("description"),
            )
        )
