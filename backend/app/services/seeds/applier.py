"""Seed pack applier and version lifecycle (plan 218 §3.5-3.6).

Approve/reject/revoke act on the version ledger; apply/replan write the
catalog through the planner's diff. Applies are serialized by the global
``provider_apply`` lock, write in one transaction, and keep
``source.current_version_id`` unchanged when anything fails. Retirement never
deletes a ``job_sources`` row — it records ``support_status='retired'``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.core.seed_pack.errors import (
    ENTITY_NOT_FOUND,
    VERSION_NOT_APPROVED,
    VERSION_STATE_INVALID,
    SeedPackError,
)
from app.core.seed_pack.store import SeedPackStore
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus, BackgroundJobType
from app.models.posting_model import JobSource
from app.models.seed_model import (
    JobSourcePreset,
    ProviderEndpoint,
    SeedDeferredRef,
    SeedImportRun,
    SeedImportRunItem,
    SeedItemProvenance,
    SeedSource,
    SeedSourceVersion,
)
from app.services.audit.provider import emit as audit_emit
from app.services.audit.provider import resource as audit_resource
from app.services.seeds.catalog import (
    ENTITY_MODELS as CATALOG_ENTITY_MODELS,
)
from app.services.seeds.catalog import (
    apply_career_path,
    apply_family,
    apply_interest,
    apply_job_type,
    apply_relation,
    apply_skill,
    job_side_effects,
)
from app.services.seeds.catalog import (
    retire as retire_catalog,
)
from app.services.seeds.catalog import (
    stage as catalog_stage,
)
from app.services.seeds.planner import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_RETIRE,
    ACTION_UPDATE,
    ENTITY_ENDPOINT,
    ENTITY_MODELS,
    ENTITY_PRESET,
    Plan,
    PlannedItem,
    build_plan,
)

APPLY_LOCK_KEY = "provider_apply"
APPLY_LOCK_JOB = BackgroundJobType.PROVIDER_APPLY.value
DEFERRED_MAX_ATTEMPTS = 10


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _actor_uuid(actor: str | uuid.UUID | None) -> uuid.UUID | None:
    if isinstance(actor, uuid.UUID):
        return actor
    try:
        return uuid.UUID(str(actor)) if actor else None
    except ValueError:
        return None


@dataclass
class ApplyResult:
    status: str
    plan: Plan
    run_id: uuid.UUID | None = None
    counts: dict[str, int] | None = None
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": str(self.run_id) if self.run_id else None,
            "counts": self.counts or self.plan.counts,
            "error": self.error,
            "plan": self.plan.as_dict(),
        }


def _preset_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    verified = payload.get("verified_at")
    return {
        "slug": payload["slug"],
        "name": payload["name"],
        "connector_key": payload["connector_key"],
        "platform": payload.get("platform") or "",
        "category": payload["category"],
        "country": payload.get("country"),
        "countries": list(payload.get("countries") or []),
        "regions": list(payload.get("regions") or []),
        "worldwide": bool(payload.get("worldwide")),
        "languages": list(payload.get("languages") or []),
        "work_modes": list(payload.get("work_modes") or []),
        "homepage": payload.get("homepage"),
        "openings": payload.get("openings"),
        "verified_at": date.fromisoformat(verified) if verified else None,
        "config": dict(payload.get("config") or {}),
    }


def _endpoint_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "label": payload["label"],
        "connector_key": payload["connector_key"],
        "platform": payload.get("platform") or "",
        "server": payload["server"],
        "method": payload.get("method") or "GET",
        "path": payload["path"],
        "auth": payload.get("auth") or "none",
        "params": list(payload.get("params") or []),
        "countries": list(payload.get("countries") or []),
        "regions": list(payload.get("regions") or []),
        "worldwide": bool(payload.get("worldwide")),
        "languages": list(payload.get("languages") or []),
        "docs_url": payload.get("docs_url"),
    }


class SeedApplyService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        packs: SeedPackStore | None = None,
        connectors: Mapping[str, Any] | None = None,
        side_effects: bool = True,
    ) -> None:
        self.db = db
        self.packs = packs or SeedPackStore()
        self.connectors = connectors
        # Test fixture packs apply catalog rows without the production
        # queue/fit side effects; the catalog adapters stay the same.
        self.side_effects = side_effects

    async def build_plan(
        self,
        source: SeedSource,
        version: SeedSourceVersion,
        *,
        allow_pending: bool = False,
    ) -> Plan:
        return await build_plan(
            self.db,
            self.packs,
            candidate=(source, version),
            connectors=self.connectors,
            allow_pending=allow_pending,
        )

    async def approve(
        self, version: SeedSourceVersion, *, actor: str | uuid.UUID = "system"
    ) -> SeedSourceVersion:
        if version.status != "pending":
            raise SeedPackError(VERSION_STATE_INVALID, f"cannot approve a {version.status} version")
        version.status = "approved"
        version.approved_by = _actor_uuid(actor)
        version.approved_at = _utcnow()
        await audit_emit(
            self.db,
            actor=actor,
            action="provider.version.approved",
            resource_ref=audit_resource(f"version:{version.id}", f"digest:{version.digest}"),
        )
        await self.db.commit()
        return version

    async def reject(
        self,
        version: SeedSourceVersion,
        *,
        reason: str = "",
        actor: str | uuid.UUID = "system",
    ) -> SeedSourceVersion:
        if version.status != "pending":
            raise SeedPackError(VERSION_STATE_INVALID, f"cannot reject a {version.status} version")
        version.status = "rejected"
        version.reason = reason[:2000]
        await audit_emit(
            self.db,
            actor=actor,
            action="provider.version.rejected",
            resource_ref=audit_resource(f"version:{version.id}", f"digest:{version.digest}"),
            outcome="error",
        )
        await self.db.commit()
        return version

    async def revoke(
        self,
        source: SeedSource,
        version: SeedSourceVersion,
        *,
        actor: str | uuid.UUID = "system",
    ) -> ApplyResult:
        if version.status != "approved":
            raise SeedPackError(VERSION_STATE_INVALID, f"cannot revoke a {version.status} version")
        version.status = "revoked"
        version.reason = "revoked"
        previous = (
            await self.db.execute(
                select(SeedSourceVersion)
                .where(
                    SeedSourceVersion.source_id == source.id,
                    SeedSourceVersion.status == "approved",
                    SeedSourceVersion.id != version.id,
                )
                .order_by(SeedSourceVersion.approved_at.desc().nullslast())
                .limit(1)
            )
        ).scalar_one_or_none()
        source.current_version_id = previous.id if previous is not None else None
        await audit_emit(
            self.db,
            actor=actor,
            action="provider.version.revoked",
            resource_ref=audit_resource(
                f"provider:{source.id}",
                f"version:{version.id}",
                f"restored:{previous.id}" if previous is not None else "restored:none",
            ),
            outcome="ok",
        )
        await self.db.commit()
        return await self.replan(source, actor=actor)

    async def apply(
        self,
        source: SeedSource,
        version: SeedSourceVersion,
        *,
        actor: str | uuid.UUID = "system",
        lock: bool = True,
        allow_pending: bool = False,
    ) -> ApplyResult:
        if version.status != "approved" and not allow_pending:
            raise SeedPackError(VERSION_NOT_APPROVED, f"version {version.id} is {version.status}")
        lock_id = await self._acquire_lock(source, version) if lock else None
        try:
            plan = await self.build_plan(source, version, allow_pending=allow_pending)
            result = await self._execute(
                plan,
                source=source,
                version=version,
                actor=actor,
                mode="apply",
                advance=True,
            )
            if lock_id is not None:
                await self._finish_lock(lock_id, result.status)
            return result
        except Exception as exc:
            await self.db.rollback()
            if lock_id is not None:
                await self._finish_lock(lock_id, "failed", str(exc))
            raise

    async def replan(
        self, source: SeedSource, *, actor: str | uuid.UUID = "system", lock: bool = True
    ) -> ApplyResult:
        lock_id = await self._acquire_lock(source, None) if lock else None
        try:
            plan = await build_plan(
                self.db, self.packs, connectors=self.connectors, allow_pending=False
            )
            result = await self._execute(
                plan, source=source, version=None, actor=actor, mode="reconcile", advance=False
            )
            if lock_id is not None:
                await self._finish_lock(lock_id, result.status)
            return result
        except Exception as exc:
            await self.db.rollback()
            if lock_id is not None:
                await self._finish_lock(lock_id, "failed", str(exc))
            raise

    async def adopt(
        self,
        source: SeedSource,
        version: SeedSourceVersion,
        *,
        seed_keys: list[str] | None = None,
        actor: str | uuid.UUID = "system",
    ) -> ApplyResult:
        wanted = set(seed_keys) if seed_keys else None
        for entity_type, model in ENTITY_MODELS.items():
            rows = cast(
                list[Any],
                (
                    await self.db.execute(
                        select(model).where(
                            model.scope_key == "system",
                            model.state == "overridden",
                        )
                    )
                )
                .scalars()
                .all(),
            )
            for row in rows:
                if wanted is not None and row.seed_key not in wanted:
                    continue
                row.state = "active"
                provenance = (
                    await self.db.execute(
                        select(SeedItemProvenance).where(
                            SeedItemProvenance.entity_type == entity_type,
                            SeedItemProvenance.entity_id == row.id,
                        )
                    )
                ).scalar_one_or_none()
                if provenance is not None:
                    provenance.user_modified = False
                    provenance.state = "active"
        for entity_type, model in CATALOG_ENTITY_MODELS.items():
            rows = cast(
                list[Any],
                (await self.db.execute(select(model).where(model.seed_key.is_not(None))))
                .scalars()
                .all(),
            )
            for row in rows:
                if wanted is not None and row.seed_key not in wanted:
                    continue
                provenance = (
                    await self.db.execute(
                        select(SeedItemProvenance).where(
                            SeedItemProvenance.entity_type == entity_type,
                            SeedItemProvenance.entity_id == row.id,
                        )
                    )
                ).scalar_one_or_none()
                if provenance is not None:
                    provenance.user_modified = False
                    provenance.state = "active"
        await self.db.commit()
        return await self.apply(source, version, actor=actor)

    async def set_enabled(
        self, entity_type: str, seed_key: str, enabled: bool, *, commit: bool = True
    ) -> bool:
        if entity_type != ENTITY_PRESET:
            raise SeedPackError(ENTITY_NOT_FOUND, "only presets have an enable overlay")
        row = (
            await self.db.execute(
                select(JobSourcePreset).where(
                    JobSourcePreset.scope_key == "system", JobSourcePreset.seed_key == seed_key
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        row.enabled = enabled
        if commit:
            await self.db.commit()
        return True

    async def retire_item(self, entity_type: str, seed_key: str, *, commit: bool = True) -> bool:
        model = ENTITY_MODELS.get(entity_type)
        if model is None:
            raise SeedPackError(ENTITY_NOT_FOUND, entity_type)
        row = (
            await self.db.execute(
                select(model).where(model.scope_key == "system", model.seed_key == seed_key)
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        row.state = "retired"
        if entity_type == ENTITY_PRESET:
            await self.db.execute(
                update(JobSource)
                .where(JobSource.seed_item_key == seed_key)
                .values(support_status="retired")
            )
        provenance = (
            await self.db.execute(
                select(SeedItemProvenance).where(
                    SeedItemProvenance.entity_type == entity_type,
                    SeedItemProvenance.entity_id == row.id,
                )
            )
        ).scalar_one_or_none()
        if provenance is not None:
            provenance.state = "retired"
        await audit_emit(
            self.db,
            actor="system",
            action="provider.item.retired",
            resource_ref=audit_resource(f"{entity_type}:{seed_key}"),
        )
        if commit:
            await self.db.commit()
        return True

    async def retry_deferred(
        self, *, version_id: uuid.UUID | None = None, commit: bool = True
    ) -> int:
        query = select(SeedDeferredRef).where(SeedDeferredRef.state == "pending")
        if version_id is not None:
            query = query.where(SeedDeferredRef.source_version_id == version_id)
        refs = (await self.db.execute(query)).scalars().all()
        landed = 0
        for ref in refs:
            payload = ref.payload or {}
            entity_type = str(payload.get("entity_type") or "")
            seed_key = str(payload.get("seed_key") or "")
            model = ENTITY_MODELS.get(entity_type)
            found = None
            if model is not None and seed_key:
                found = (
                    (
                        await self.db.execute(
                            select(model.id).where(
                                model.scope_key == "system", model.seed_key == seed_key
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
            if found is not None:
                ref.state = "landed"
                landed += 1
            else:
                ref.attempts += 1
                if ref.attempts >= DEFERRED_MAX_ATTEMPTS:
                    ref.state = "abandoned"
        if commit:
            await self.db.commit()
        return landed

    async def _acquire_lock(
        self, source: SeedSource, version: SeedSourceVersion | None
    ) -> uuid.UUID:
        job = BackgroundJob(
            job_type=APPLY_LOCK_JOB,
            status=BackgroundJobStatus.RUNNING.value,
            payload={
                "source_id": str(source.id),
                "version_id": str(version.id) if version is not None else None,
            },
            lock_key=APPLY_LOCK_KEY,
            attempts=1,
            max_attempts=2,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(job)
                await self.db.flush()
        except IntegrityError:
            raise ConflictError("another provider apply is running") from None
        await self.db.commit()
        return job.id

    async def _finish_lock(self, job_id: uuid.UUID, status: str, error: str = "") -> None:
        job = await self.db.get(BackgroundJob, job_id)
        if job is None:
            return
        job.status = (
            BackgroundJobStatus.SUCCEEDED.value
            if status in ("applied", "conflicted", "noop")
            else BackgroundJobStatus.FAILED.value
        )
        job.error = error[:2000] or None
        job.finished_at = _utcnow()
        job.lock_key = None
        await self.db.commit()

    async def _execute(
        self,
        plan: Plan,
        *,
        source: SeedSource,
        version: SeedSourceVersion | None,
        actor: str | uuid.UUID,
        mode: str,
        advance: bool,
    ) -> ApplyResult:
        started = _utcnow()
        source_id = source.id
        source_version_id = version.id if version is not None else None
        if plan.status == "conflicted":
            run = await self._record_run(
                source,
                version,
                plan,
                mode=mode,
                status="conflicted",
                error="equal-priority providers disagree",
                started=started,
            )
            await audit_emit(
                self.db,
                actor=actor,
                action="provider.apply.conflicted",
                resource_ref=audit_resource(
                    f"provider:{source.id}", f"version:{version.id}" if version else None
                ),
                outcome="error",
            )
            await self.db.commit()
            return ApplyResult(
                status="conflicted",
                plan=plan,
                run_id=run.id,
                counts=plan.counts,
                error="equal-priority providers disagree",
            )

        try:
            run = SeedImportRun(
                source_id=source.id,
                version_id=version.id if version is not None else None,
                mode=mode,
                status="applied",
                plan=plan.as_dict(),
                stats=plan.counts,
                started_at=started,
            )
            self.db.add(run)
            await self.db.flush()
            await self._record_items(run, plan)
            # An applied pack is the admin's choice: its presets start on and
            # the per-item switches remain the override.
            default_enabled = True
            changed_jobs: list[uuid.UUID] = []
            ordered = sorted(
                plan.items, key=lambda item: catalog_stage(item.action, item.entity_type)
            )
            for item in ordered:
                if item.action in (ACTION_CREATE, ACTION_UPDATE):
                    job_id = await self._apply_item(item, default_enabled=default_enabled)
                    if job_id is not None:
                        changed_jobs.append(job_id)
            for item in ordered:
                if item.action == ACTION_DELETE:
                    await self._delete_row(item)
            for item in ordered:
                if item.action == ACTION_RETIRE:
                    await self._retire_row(item)
            if self.side_effects:
                await job_side_effects(self.db, changed_jobs)
            if advance and version is not None:
                source.current_version_id = version.id
            await self.retry_deferred(
                version_id=version.id if version is not None else None, commit=False
            )
            run.finished_at = _utcnow()
            await audit_emit(
                self.db,
                actor=actor,
                action="provider.apply.ok",
                resource_ref=audit_resource(
                    f"provider:{source.id}",
                    f"version:{version.id}" if version else None,
                    f"run:{run.id}",
                ),
            )
            await self.db.commit()
            mutations = sum(
                plan.counts[action]
                for action in (ACTION_CREATE, ACTION_UPDATE, ACTION_DELETE, ACTION_RETIRE)
            )
            return ApplyResult(
                status="applied" if mutations else "noop",
                plan=plan,
                run_id=run.id,
                counts=plan.counts,
            )
        except Exception as exc:
            await self.db.rollback()
            failed = await self._record_failed_run(
                source_id, source_version_id, plan, mode, started, exc
            )
            return ApplyResult(
                status="failed",
                plan=plan,
                run_id=failed.id if failed is not None else None,
                counts=plan.counts,
                error=str(exc)[:500],
            )

    async def _record_run(
        self,
        source: SeedSource | uuid.UUID,
        version: SeedSourceVersion | uuid.UUID | None,
        plan: Plan,
        *,
        mode: str,
        status: str,
        error: str,
        started: datetime,
    ) -> SeedImportRun:
        run = SeedImportRun(
            source_id=source.id if isinstance(source, SeedSource) else source,
            version_id=(version.id if isinstance(version, SeedSourceVersion) else version),
            mode=mode,
            status=status,
            plan=plan.as_dict(),
            stats=plan.counts,
            error=error[:2000],
            started_at=started,
            finished_at=_utcnow(),
        )
        self.db.add(run)
        await self.db.flush()
        await self._record_items(run, plan)
        return run

    async def _record_items(self, run: SeedImportRun, plan: Plan) -> None:
        for item in plan.items:
            self.db.add(
                SeedImportRunItem(
                    run_id=run.id,
                    entity_type=item.entity_type,
                    seed_key=item.seed_key,
                    action=item.action,
                    detail=item.as_dict(),
                )
            )

    async def _record_failed_run(
        self,
        source_id: uuid.UUID,
        version_id: uuid.UUID | None,
        plan: Plan,
        mode: str,
        started: datetime,
        exc: Exception,
    ) -> SeedImportRun | None:
        try:
            run = await self._record_run(
                source_id,
                version_id,
                plan,
                mode=mode,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                started=started,
            )
            await audit_emit(
                self.db,
                actor="system",
                action="provider.apply.failed",
                resource_ref=audit_resource(f"provider:{source_id}", f"run:{run.id}"),
                outcome="error",
            )
            await self.db.commit()
            return run
        except Exception:
            await self.db.rollback()
            return None

    async def _apply_item(
        self, item: PlannedItem, *, default_enabled: bool = False
    ) -> uuid.UUID | None:
        now = _utcnow()
        if item.entity_type == ENTITY_PRESET:
            fields = _preset_fields(item.payload)
            preset: JobSourcePreset | None = (
                await self.db.get(JobSourcePreset, item.current_id) if item.current_id else None
            )
            if preset is None:
                preset = JobSourcePreset(
                    scope_key="system",
                    seed_key=item.seed_key,
                    enabled=default_enabled,
                    state="active",
                    seed_source_version_id=item.version_id,
                    **fields,
                )
                self.db.add(preset)
            else:
                for key, value in fields.items():
                    setattr(preset, key, value)
                preset.state = "active"
                preset.seed_source_version_id = item.version_id
            await self.db.flush()
            await self._upsert_provenance(ENTITY_PRESET, preset.id, item, now)
            return None
        if item.entity_type == ENTITY_ENDPOINT:
            fields = _endpoint_fields(item.payload)
            endpoint: ProviderEndpoint | None = (
                await self.db.get(ProviderEndpoint, item.current_id) if item.current_id else None
            )
            if endpoint is None:
                endpoint = ProviderEndpoint(
                    scope_key="system",
                    seed_key=item.seed_key,
                    state="active",
                    seed_source_version_id=item.version_id,
                    **fields,
                )
                self.db.add(endpoint)
            else:
                for key, value in fields.items():
                    setattr(endpoint, key, value)
                endpoint.state = "active"
                endpoint.seed_source_version_id = item.version_id
            await self.db.flush()
            await self._upsert_provenance(ENTITY_ENDPOINT, endpoint.id, item, now)
            return None
        if item.entity_type in CATALOG_ENTITY_MODELS:
            model = CATALOG_ENTITY_MODELS[item.entity_type]
            row = await self.db.get(model, item.current_id) if item.current_id else None
            seed_key = item.seed_key
            if item.entity_type == "job_family":
                row = await apply_family(self.db, item.payload, row, seed_key=seed_key)
            elif item.entity_type == "skill":
                row = await apply_skill(self.db, item.payload, row, seed_key=seed_key)
            elif item.entity_type == "interest_tag":
                row = await apply_interest(self.db, item.payload, row, seed_key=seed_key)
            elif item.entity_type == "job_type":
                row = await apply_job_type(
                    self.db, item.payload, row, seed_key=seed_key, version_id=item.version_id
                )
            elif item.entity_type == "job_relation":
                row = await apply_relation(self.db, item.payload, row, seed_key=seed_key)
            elif item.entity_type == "career_path":
                row = await apply_career_path(self.db, item.payload, row, seed_key=seed_key)
            else:  # pragma: no cover - registry is closed
                return None
            await self._upsert_provenance(item.entity_type, row.id, item, now)
            return row.id if item.entity_type == "job_type" else None
        return None

    async def _delete_row(self, item: PlannedItem) -> None:
        model = CATALOG_ENTITY_MODELS.get(item.entity_type)
        if model is None or item.current_id is None:
            return
        row = await self.db.get(model, item.current_id)
        if row is not None:
            await self.db.delete(row)
        provenance = (
            await self.db.execute(
                select(SeedItemProvenance).where(
                    SeedItemProvenance.entity_type == item.entity_type,
                    SeedItemProvenance.entity_id == item.current_id,
                )
            )
        ).scalar_one_or_none()
        if provenance is not None:
            await self.db.delete(provenance)
        await self.db.flush()

    async def _retire_row(self, item: PlannedItem) -> None:
        model = CATALOG_ENTITY_MODELS.get(item.entity_type) or ENTITY_MODELS.get(item.entity_type)
        if model is None or item.current_id is None:
            return
        row = await self.db.get(model, item.current_id)
        if row is None:
            return
        if item.entity_type in CATALOG_ENTITY_MODELS:
            await retire_catalog(self.db, item.entity_type, row)
        else:
            row.state = "retired"
        if item.entity_type == ENTITY_PRESET:
            await self.db.execute(
                update(JobSource)
                .where(JobSource.seed_item_key == item.seed_key)
                .values(support_status="retired")
            )
        provenance = (
            await self.db.execute(
                select(SeedItemProvenance).where(
                    SeedItemProvenance.entity_type == item.entity_type,
                    SeedItemProvenance.entity_id == row.id,
                )
            )
        ).scalar_one_or_none()
        if provenance is not None:
            provenance.state = "retired"

    async def _upsert_provenance(
        self, entity_type: str, entity_id: uuid.UUID, item: PlannedItem, now: datetime
    ) -> None:
        provenance = (
            await self.db.execute(
                select(SeedItemProvenance).where(
                    SeedItemProvenance.entity_type == entity_type,
                    SeedItemProvenance.entity_id == entity_id,
                )
            )
        ).scalar_one_or_none()
        if provenance is None:
            self.db.add(
                SeedItemProvenance(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    source_version_id=item.version_id,
                    seed_key=item.seed_key,
                    content_hash=item.content_hash,
                    state="active",
                    user_modified=False,
                    applied_at=now,
                )
            )
            return
        provenance.source_version_id = item.version_id
        provenance.seed_key = item.seed_key
        provenance.content_hash = item.content_hash
        provenance.state = "active"
        provenance.applied_at = now


__all__ = ["APPLY_LOCK_KEY", "ApplyResult", "SeedApplyService"]
