"""Provider administration and user read surfaces (plan 218 §3.8).

The service maps the ``seed_*`` storage onto the product's "provider"
vocabulary: admin CRUD, sync/upload, the version ledger actions, planner
preview and apply, per-item enable/retire, discovery and the admin endpoint
probe. The user surface is read-only and excludes URIs, errors and policy —
the follow/hide overlays are the next increment.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.seed_pack.errors import SeedPackError
from app.core.seed_pack.manifest import (
    endpoint_in_connector_domains,
    parse_repo_index,
)
from app.core.seed_pack.store import SeedPackStore
from app.models.seed_model import (
    JobSourcePreset,
    ProviderEndpoint,
    SeedSource,
    SeedSourceVersion,
    SeedSyncRun,
)
from app.services.audit.provider import emit as audit_emit
from app.services.audit.provider import resource as audit_resource
from app.services.integrations.webfetch import WebFetchBlocked, fetch_bytes
from app.services.seeds.applier import SeedApplyService
from app.services.seeds.git_transport import (
    GitTransport,
    validate_public_git_uri,
    validate_subpath,
)
from app.services.seeds.planner import ENTITY_PRESET
from app.services.seeds.registry_transport import RegistryTransport, normalize_index_url
from app.services.seeds.service import ProviderSyncService

MAX_UPLOAD_BYTES = 64 * 1024 * 1024


def _identifier(value: uuid.UUID | str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise NotFoundError(f"{label} not found") from exc


def _version_summary(version: SeedSourceVersion) -> dict[str, Any]:
    return {
        "id": str(version.id),
        "pack_version": version.pack_version,
        "status": version.status,
        "digest": version.digest,
        "commit_sha": version.commit_sha,
        "created_at": version.created_at,
        "approved_at": version.approved_at,
    }


def _version_out(version: SeedSourceVersion) -> dict[str, Any]:
    return {
        **_version_summary(version),
        "source_id": str(version.source_id),
        "etag": version.etag,
        "schema_version": version.schema_version,
        "reason": version.reason,
        "contract_version": version.contract_version,
    }


def _sync_run(row: SeedSyncRun) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "trigger": row.trigger,
        "status": row.status,
        "http_status": row.http_status,
        "etag": row.etag,
        "bytes": row.bytes,
        "commit_sha": row.commit_sha,
        "version_id": str(row.version_id) if row.version_id else None,
        "error": row.error,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def _preset_payload(row: JobSourcePreset) -> dict[str, Any]:
    return {
        "seed_key": row.seed_key,
        "slug": row.slug,
        "name": row.name,
        "connector_key": row.connector_key,
        "platform": row.platform,
        "category": row.category,
        "country": row.country,
        "countries": list(row.countries or []),
        "regions": list(row.regions or []),
        "worldwide": row.worldwide,
        "languages": list(row.languages or []),
        "work_modes": list(row.work_modes or []),
        "homepage": row.homepage,
        "openings": row.openings,
        "verified_at": row.verified_at,
        "config": dict(row.config or {}),
    }


def _preset_admin(row: JobSourcePreset) -> dict[str, Any]:
    return {
        **_preset_payload(row),
        "enabled": row.enabled,
        "state": row.state,
        "seed_source_version_id": (
            str(row.seed_source_version_id) if row.seed_source_version_id else None
        ),
        "updated_at": row.updated_at,
    }


def _endpoint_payload(row: ProviderEndpoint) -> dict[str, Any]:
    return {
        "seed_key": row.seed_key,
        "label": row.label,
        "connector_key": row.connector_key,
        "platform": row.platform,
        "server": row.server,
        "method": row.method,
        "path": row.path,
        "auth": row.auth,
        "params": list(row.params or []),
        "countries": list(row.countries or []),
        "regions": list(row.regions or []),
        "worldwide": row.worldwide,
        "languages": list(row.languages or []),
        "docs_url": row.docs_url,
    }


def _endpoint_admin(row: ProviderEndpoint) -> dict[str, Any]:
    return {
        **_endpoint_payload(row),
        "state": row.state,
        "seed_source_version_id": (
            str(row.seed_source_version_id) if row.seed_source_version_id else None
        ),
        "updated_at": row.updated_at,
    }


class ProviderService:
    def __init__(self, db: AsyncSession, *, packs: SeedPackStore | None = None) -> None:
        self.db = db
        self.packs = packs or SeedPackStore()

    # ------------------------------------------------------------- sources

    async def _source(self, source_id: uuid.UUID | str) -> SeedSource:
        source = await self.db.get(SeedSource, _identifier(source_id, "provider"))
        if source is None:
            raise NotFoundError("provider not found")
        return source

    async def _version(self, source: SeedSource, version_id: uuid.UUID | str) -> SeedSourceVersion:
        version = await self.db.get(SeedSourceVersion, _identifier(version_id, "version"))
        if version is None or version.source_id != source.id:
            raise NotFoundError("version not found")
        return version

    async def _versions_for(self, source: SeedSource) -> list[SeedSourceVersion]:
        return list(
            (
                await self.db.execute(
                    select(SeedSourceVersion)
                    .where(SeedSourceVersion.source_id == source.id)
                    .order_by(SeedSourceVersion.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

    async def _item_counts(self, version_id: uuid.UUID | None) -> dict[str, int]:
        if version_id is None:
            return {"presets": 0, "endpoints": 0}
        presets = await self.db.scalar(
            select(func.count())
            .select_from(JobSourcePreset)
            .where(JobSourcePreset.seed_source_version_id == version_id)
        )
        endpoints = await self.db.scalar(
            select(func.count())
            .select_from(ProviderEndpoint)
            .where(ProviderEndpoint.seed_source_version_id == version_id)
        )
        return {"presets": int(presets or 0), "endpoints": int(endpoints or 0)}

    async def _provider_admin(
        self, source: SeedSource, versions: list[SeedSourceVersion]
    ) -> dict[str, Any]:
        current = next(
            (version for version in versions if version.id == source.current_version_id), None
        )
        latest = versions[0] if versions else None
        counts = await self._item_counts(current.id if current is not None else None)
        return {
            "id": str(source.id),
            "name": source.name,
            "kind": source.kind,
            "uri": source.uri,
            "ref": source.ref_spec,
            "subpath": source.subpath,
            "priority": source.priority,
            "scope": source.scope,
            "trust_tier": source.trust_tier,
            "refresh_minutes": source.refresh_minutes,
            "enabled": source.enabled,
            "current_version": _version_summary(current) if current is not None else None,
            "latest_version": _version_summary(latest) if latest is not None else None,
            "pending_count": sum(1 for version in versions if version.status == "pending"),
            "item_counts": counts,
            "last_check_at": source.last_check_at,
            "last_error": source.last_error,
            "policy": dict(source.policy or {}),
        }

    async def list_admin(self) -> list[dict[str, Any]]:
        sources = list(
            (
                await self.db.execute(
                    select(SeedSource).order_by(SeedSource.priority, SeedSource.name)
                )
            )
            .scalars()
            .all()
        )
        by_source: dict[uuid.UUID, list[SeedSourceVersion]] = defaultdict(list)
        for version in (
            (
                await self.db.execute(
                    select(SeedSourceVersion).order_by(SeedSourceVersion.created_at.desc())
                )
            )
            .scalars()
            .all()
        ):
            by_source[version.source_id].append(version)
        return [
            await self._provider_admin(source, by_source.get(source.id, [])) for source in sources
        ]

    async def get_admin(self, source_id: uuid.UUID | str) -> dict[str, Any]:
        source = await self._source(source_id)
        versions = await self._versions_for(source)
        detail = await self._provider_admin(source, versions)
        current_id = source.current_version_id
        presets = (
            (
                await self.db.execute(
                    select(JobSourcePreset)
                    .where(JobSourcePreset.seed_source_version_id == current_id)
                    .order_by(JobSourcePreset.name)
                )
            )
            .scalars()
            .all()
            if current_id is not None
            else []
        )
        endpoints = (
            (
                await self.db.execute(
                    select(ProviderEndpoint)
                    .where(ProviderEndpoint.seed_source_version_id == current_id)
                    .order_by(ProviderEndpoint.label)
                )
            )
            .scalars()
            .all()
            if current_id is not None
            else []
        )
        detail["versions"] = [_version_summary(version) for version in versions]
        detail["presets"] = [_preset_admin(row) for row in presets]
        detail["endpoints"] = [_endpoint_admin(row) for row in endpoints]
        return detail

    async def create(self, data: Any, *, actor: str | uuid.UUID = "system") -> SeedSource:
        if data.kind == "git":
            try:
                validate_public_git_uri(data.uri)
                validate_subpath(data.subpath)
            except SeedPackError as exc:
                raise ValidationError(f"{exc.code}: {exc.detail}") from exc
            if not (data.ref or "").strip():
                raise ValidationError("a git provider requires a pinned ref (tag or commit)")
        elif data.kind == "registry":
            try:
                normalize_index_url(data.uri)
                validate_subpath(data.subpath)
            except SeedPackError as exc:
                raise ValidationError(f"{exc.code}: {exc.detail}") from exc
        source = SeedSource(
            name=data.name,
            kind=data.kind,
            uri=data.uri,
            ref_spec=data.ref,
            subpath=data.subpath,
            priority=data.priority,
            scope="system",
            trust_tier=data.trust_tier,
            refresh_minutes=data.refresh_minutes,
            enabled=data.enabled,
        )
        self.db.add(source)
        await self.db.flush()
        await audit_emit(
            self.db,
            actor=actor,
            action="provider.source.created",
            resource_ref=audit_resource(f"provider:{source.id}", f"kind:{source.kind}"),
        )
        await self.db.commit()
        await self.db.refresh(source)
        return source

    async def update(
        self, source_id: uuid.UUID | str, data: Any, *, actor: str | uuid.UUID = "system"
    ) -> SeedSource:
        source = await self._source(source_id)
        if data.name is not None:
            source.name = data.name
        if data.priority is not None:
            source.priority = data.priority
        if data.trust_tier is not None:
            source.trust_tier = data.trust_tier
        if data.refresh_minutes is not None:
            source.refresh_minutes = data.refresh_minutes
        if data.enabled is not None:
            source.enabled = data.enabled
        if data.ref is not None:
            source.ref_spec = data.ref
        if data.subpath is not None:
            try:
                validate_subpath(data.subpath)
            except SeedPackError as exc:
                raise ValidationError(f"{exc.code}: {exc.detail}") from exc
            source.subpath = data.subpath
        await audit_emit(
            self.db,
            actor=actor,
            action="provider.source.updated",
            resource_ref=audit_resource(f"provider:{source.id}"),
        )
        await self.db.commit()
        await self.db.refresh(source)
        return source

    async def delete(
        self, source_id: uuid.UUID | str, *, actor: str | uuid.UUID = "system"
    ) -> dict[str, Any]:
        source = await self._source(source_id)
        source.enabled = False
        source.current_version_id = None
        source.last_error = "retired by admin"
        await audit_emit(
            self.db,
            actor=actor,
            action="provider.source.retired",
            resource_ref=audit_resource(f"provider:{source.id}"),
        )
        await self.db.commit()
        try:
            result = await SeedApplyService(self.db, packs=self.packs).replan(source, actor=actor)
            return {"id": str(source.id), "retired": True, "replan": result.as_dict()}
        except Exception as exc:
            return {"id": str(source.id), "retired": True, "replan_error": str(exc)[:500]}

    # --------------------------------------------------------------- sync

    async def sync(
        self, source_id: uuid.UUID | str, *, actor: str | uuid.UUID = "system"
    ) -> dict[str, Any]:
        source = await self._source(source_id)
        return await ProviderSyncService(self.db, packs=self.packs).sync(
            source, trigger="manual", actor=str(actor)
        )

    async def upload(
        self,
        source_id: uuid.UUID | str,
        data: bytes,
        *,
        actor: str | uuid.UUID = "system",
    ) -> dict[str, Any]:
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValidationError("pack upload exceeds the 64 MB cap")
        source = await self._source(source_id)
        if source.kind != "file":
            raise ValidationError("only a file provider accepts an upload")
        return await ProviderSyncService(self.db, packs=self.packs).upload_file(
            source, data, actor=str(actor)
        )

    async def versions(self, source_id: uuid.UUID | str) -> list[dict[str, Any]]:
        source = await self._source(source_id)
        return [_version_out(version) for version in await self._versions_for(source)]

    async def approve(
        self, source_id: uuid.UUID | str, version_id: uuid.UUID | str, *, actor: str
    ) -> dict[str, Any]:
        source = await self._source(source_id)
        version = await self._version(source, version_id)
        await SeedApplyService(self.db, packs=self.packs).approve(version, actor=actor)
        return _version_out(version)

    async def reject(
        self,
        source_id: uuid.UUID | str,
        version_id: uuid.UUID | str,
        *,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        source = await self._source(source_id)
        version = await self._version(source, version_id)
        await SeedApplyService(self.db, packs=self.packs).reject(
            version, reason=reason, actor=actor
        )
        return _version_out(version)

    async def revoke(
        self, source_id: uuid.UUID | str, version_id: uuid.UUID | str, *, actor: str
    ) -> dict[str, Any]:
        source = await self._source(source_id)
        version = await self._version(source, version_id)
        result = await SeedApplyService(self.db, packs=self.packs).revoke(
            source, version, actor=actor
        )
        return result.as_dict()

    async def plan(self, source_id: uuid.UUID | str, version_id: uuid.UUID | str) -> dict[str, Any]:
        source = await self._source(source_id)
        version = await self._version(source, version_id)
        plan = await SeedApplyService(self.db, packs=self.packs).build_plan(
            source, version, allow_pending=True
        )
        return plan.as_dict()

    async def apply(
        self, source_id: uuid.UUID | str, version_id: uuid.UUID | str, *, actor: str
    ) -> dict[str, Any]:
        source = await self._source(source_id)
        version = await self._version(source, version_id)
        result = await SeedApplyService(self.db, packs=self.packs).apply(
            source, version, actor=actor
        )
        return result.as_dict()

    async def adopt(
        self,
        source_id: uuid.UUID | str,
        version_id: uuid.UUID | str,
        *,
        seed_keys: list[str] | None,
        actor: str,
    ) -> dict[str, Any]:
        source = await self._source(source_id)
        version = await self._version(source, version_id)
        result = await SeedApplyService(self.db, packs=self.packs).adopt(
            source, version, seed_keys=seed_keys, actor=actor
        )
        return result.as_dict()

    async def set_item_enabled(
        self, source_id: uuid.UUID | str, seed_key: str, enabled: bool
    ) -> bool:
        await self._source(source_id)
        try:
            return await SeedApplyService(self.db, packs=self.packs).set_enabled(
                ENTITY_PRESET, seed_key, enabled
            )
        except SeedPackError as exc:
            raise ValidationError(f"{exc.code}: {exc.detail}") from exc

    async def retire_item(self, source_id: uuid.UUID | str, seed_key: str) -> bool:
        await self._source(source_id)
        try:
            return await SeedApplyService(self.db, packs=self.packs).retire_item(
                ENTITY_PRESET, seed_key
            )
        except SeedPackError as exc:
            raise ValidationError(f"{exc.code}: {exc.detail}") from exc

    async def sync_runs(
        self, source_id: uuid.UUID | str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        source = await self._source(source_id)
        rows = (
            (
                await self.db.execute(
                    select(SeedSyncRun)
                    .where(SeedSyncRun.source_id == source.id)
                    .order_by(SeedSyncRun.started_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [_sync_run(row) for row in rows]

    # ---------------------------------------------------------- discovery

    async def discover(self, data: Any) -> dict[str, Any]:
        try:
            if data.kind == "git":
                raw, _commit = await GitTransport().discover(data.uri, data.ref)
                index = parse_repo_index(raw)
            else:
                fetched = await RegistryTransport().fetch_index(data.uri)
                if fetched.index is None:
                    raise ValidationError("the index answered 304 (no ETag was sent)")
                index = fetched.index
        except SeedPackError as exc:
            raise ValidationError(f"{exc.code}: {exc.detail}") from exc
        return {
            "kind": data.kind,
            "publisher": index.publisher.model_dump(mode="json"),
            "packs": [pack.model_dump(mode="json") for pack in index.packs],
        }

    async def probe(
        self, source_id: uuid.UUID | str, seed_key: str, *, actor: str
    ) -> dict[str, Any]:
        await self._source(source_id)
        endpoint = (
            await self.db.execute(
                select(ProviderEndpoint).where(ProviderEndpoint.seed_key == seed_key)
            )
        ).scalar_one_or_none()
        if endpoint is None:
            raise NotFoundError("endpoint not found")
        if "{" in endpoint.server or "{" in endpoint.path:
            raise ValidationError("endpoint has unresolved parameters; it cannot be probed")
        from app.extensions.registry import iter_connectors

        connector = next(
            (item for item in iter_connectors() if item.key == endpoint.connector_key), None
        )
        if connector is None or not endpoint_in_connector_domains(connector, endpoint.server):
            raise ValidationError("endpoint is outside its connector's declared domains")
        url = endpoint.server.rstrip("/") + endpoint.path
        started = time.perf_counter()
        try:
            status, headers, _body, _final = await fetch_bytes(url, max_bytes=64 * 1024)
        except WebFetchBlocked as exc:
            raise ValidationError(str(exc)) from exc
        elapsed = int((time.perf_counter() - started) * 1000)
        await audit_emit(
            self.db,
            actor=actor,
            action="provider.endpoint.probe",
            resource_ref=audit_resource(f"provider:{source_id}", f"endpoint:{seed_key}"),
            outcome="ok" if 200 <= status < 400 else "error",
        )
        await self.db.commit()
        return {
            "status": status,
            "elapsed_ms": elapsed,
            "content_type": str(headers.get("content-type", "")).split(";")[0],
        }

    # ---------------------------------------------------------- user view

    async def _user_version(self, source: SeedSource) -> SeedSourceVersion | None:
        if not source.enabled or source.current_version_id is None:
            return None
        version = await self.db.get(SeedSourceVersion, source.current_version_id)
        return version if version is not None and version.status == "approved" else None

    async def user_list(self) -> list[dict[str, Any]]:
        sources = list(
            (
                await self.db.execute(
                    select(SeedSource)
                    .where(SeedSource.enabled.is_(True), SeedSource.current_version_id.is_not(None))
                    .order_by(SeedSource.priority, SeedSource.name)
                )
            )
            .scalars()
            .all()
        )
        items: list[dict[str, Any]] = []
        for source in sources:
            version = await self._user_version(source)
            if version is None:
                continue
            presets = await self.db.scalar(
                select(func.count())
                .select_from(JobSourcePreset)
                .where(
                    JobSourcePreset.seed_source_version_id == version.id,
                    JobSourcePreset.state == "active",
                    JobSourcePreset.enabled.is_(True),
                )
            )
            endpoints = await self.db.scalar(
                select(func.count())
                .select_from(ProviderEndpoint)
                .where(
                    ProviderEndpoint.seed_source_version_id == version.id,
                    ProviderEndpoint.state == "active",
                )
            )
            items.append(
                {
                    "id": str(source.id),
                    "name": source.name,
                    "kind": source.kind,
                    "trust_tier": source.trust_tier,
                    "priority": source.priority,
                    "pack_version": version.pack_version,
                    "item_count": int((presets or 0) + (endpoints or 0)),
                    "last_check_at": source.last_check_at,
                }
            )
        return items

    async def user_detail(self, source_id: uuid.UUID | str) -> dict[str, Any]:
        source = await self._source(source_id)
        version = await self._user_version(source)
        if version is None:
            raise NotFoundError("provider not found")
        presets = (
            (
                await self.db.execute(
                    select(JobSourcePreset)
                    .where(
                        JobSourcePreset.seed_source_version_id == version.id,
                        JobSourcePreset.state == "active",
                        JobSourcePreset.enabled.is_(True),
                    )
                    .order_by(JobSourcePreset.name)
                )
            )
            .scalars()
            .all()
        )
        endpoints = (
            (
                await self.db.execute(
                    select(ProviderEndpoint)
                    .where(
                        ProviderEndpoint.seed_source_version_id == version.id,
                        ProviderEndpoint.state == "active",
                    )
                    .order_by(ProviderEndpoint.label)
                )
            )
            .scalars()
            .all()
        )
        return {
            "id": str(source.id),
            "name": source.name,
            "kind": source.kind,
            "trust_tier": source.trust_tier,
            "priority": source.priority,
            "pack_version": version.pack_version,
            "item_count": len(presets) + len(endpoints),
            "last_check_at": source.last_check_at,
            "presets": [_preset_payload(row) for row in presets],
            "endpoints": [_endpoint_payload(row) for row in endpoints],
        }

    async def user_endpoints(self, source_id: uuid.UUID | str) -> list[dict[str, Any]]:
        source = await self._source(source_id)
        version = await self._user_version(source)
        if version is None:
            raise NotFoundError("provider not found")
        rows = (
            (
                await self.db.execute(
                    select(ProviderEndpoint)
                    .where(
                        ProviderEndpoint.seed_source_version_id == version.id,
                        ProviderEndpoint.state == "active",
                    )
                    .order_by(ProviderEndpoint.label)
                )
            )
            .scalars()
            .all()
        )
        return [_endpoint_payload(row) for row in rows]


__all__ = ["MAX_UPLOAD_BYTES", "ProviderService"]
