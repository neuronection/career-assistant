"""Provider sync and immutable version registration (plan 218 §3.4-3.5).

Sync fetches a pack, validates it, stores the archive by content digest and
registers a ``pending`` version. It never approves, applies, enables or
creates a job source — those are explicit admin acts. The run ledger and the
per-source job lock make repeated ticks idempotent.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.seed_pack.archive import build_pack_archive, extract_pack_archive
from app.core.seed_pack.errors import (
    DIGEST_DRIFT,
    FILE_SOURCE_NO_CONTENT,
    PACK_AMBIGUOUS,
    PACK_NOT_FOUND,
    REGISTRY_PARTIAL,
    SOURCE_DISABLED,
    SOURCE_KIND_UNSUPPORTED,
    VERSION_REUSED,
    SeedPackError,
)
from app.core.seed_pack.manifest import (
    ParsedPack,
    RepoIndex,
    canonical_json,
    parse_pack,
)
from app.core.seed_pack.store import SeedPackStore
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobType
from app.models.seed_model import SeedSource, SeedSourceVersion, SeedSyncRun
from app.models.user_model import User
from app.services.audit.provider import emit as audit_emit
from app.services.audit.provider import resource as audit_resource
from app.services.notification_service import NotificationService
from app.services.seeds.git_transport import GitTransport
from app.services.seeds.registry_transport import RegistryTransport, normalize_index_url

logger = logging.getLogger(__name__)

PROVIDER_SYNC_JOB = BackgroundJobType.PROVIDER_SYNC.value
ACTIVE_JOB_STATUSES = ("queued", "running")
UPDATE_KIND = "provider_update_available"
FAILED_KIND = "provider_sync_failed"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Registration:
    version: SeedSourceVersion
    created: bool
    code: str | None = None
    bytes: int | None = None


@dataclass(frozen=True)
class SyncReport:
    status: str
    code: str | None = None
    message: str = ""
    digest: str | None = None
    version_id: str | None = None
    http_status: int | None = None
    etag: str = ""
    commit_sha: str = ""
    bytes: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "digest": self.digest,
            "version_id": self.version_id,
            "http_status": self.http_status,
            "etag": self.etag,
            "commit_sha": self.commit_sha,
            "bytes": self.bytes,
        }


class ProviderSyncService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        packs: SeedPackStore | None = None,
        git: GitTransport | None = None,
        registry: RegistryTransport | None = None,
        connectors: Mapping[str, Any] | None = None,
    ) -> None:
        self.db = db
        self.packs = packs or SeedPackStore()
        self.git = git or GitTransport()
        self.registry = registry or RegistryTransport()
        self.connectors = connectors

    async def sync_by_id(
        self, source_id: uuid.UUID | str, *, trigger: str = "manual", actor: str = "system"
    ) -> dict[str, Any]:
        try:
            key = uuid.UUID(str(source_id))
        except ValueError:
            return SyncReport(status="failed", code=PACK_NOT_FOUND).as_dict()
        source = await self.db.get(SeedSource, key)
        if source is None:
            return SyncReport(status="failed", code=PACK_NOT_FOUND).as_dict()
        return await self.sync(source, trigger=trigger, actor=actor)

    async def sync(
        self, source: SeedSource, *, trigger: str = "manual", actor: str = "system"
    ) -> dict[str, Any]:
        if trigger not in ("manual", "scheduled"):
            trigger = "manual"
        if trigger == "scheduled" and not source.enabled:
            return SyncReport(status="noop", code=SOURCE_DISABLED).as_dict()

        started = _utcnow()
        run = SeedSyncRun(
            source_id=source.id,
            trigger=trigger,
            status="running",
            started_at=started,
            etag="",
            commit_sha="",
            error="",
        )
        self.db.add(run)
        await self.db.commit()

        report = SyncReport(status="failed")
        try:
            if source.kind == "git":
                report = await self._sync_git(source)
            elif source.kind == "registry":
                report = await self._sync_registry(source)
            elif source.kind == "file":
                report = SyncReport(
                    status="failed",
                    code=FILE_SOURCE_NO_CONTENT,
                    message="file providers sync through an upload",
                )
            else:
                report = SyncReport(status="failed", code=SOURCE_KIND_UNSUPPORTED)
        except SeedPackError as exc:
            status = "partial" if exc.code == REGISTRY_PARTIAL else "failed"
            report = SyncReport(status=status, code=exc.code, message=exc.detail)
        except Exception as exc:
            logger.warning("provider sync failed for %s", source.id, exc_info=True)
            report = SyncReport(status="failed", message=f"{type(exc).__name__}: {exc}"[:500])

        await self._finish_run(source, run, report)
        await audit_emit(
            self.db,
            actor=actor,
            action=f"provider.sync.{report.status}"
            if report.status in ("ok", "noop", "failed", "partial")
            else "provider.sync.failed",
            resource_ref=audit_resource(
                f"provider:{source.id}",
                f"version:{report.version_id}" if report.version_id else None,
            ),
            outcome="error" if report.status == "failed" else "ok",
        )
        await self.db.commit()
        if report.status in ("failed", "partial"):
            await self._notify_failure(source, report)
        return report.as_dict()

    async def _sync_git(self, source: SeedSource) -> SyncReport:
        pack = await self.git.fetch(source.uri, source.ref_spec, source.subpath)
        parsed = self._parse(pack.files, source)
        registration = await self._register(
            source, parsed, status="pending", commit_sha=pack.commit_sha
        )
        return self._report(registration, parsed, commit_sha=pack.commit_sha)

    async def _sync_registry(self, source: SeedSource) -> SyncReport:
        etag = str((source.policy or {}).get("registry_etag") or "")
        fetched = await self.registry.fetch_index(source.uri, etag=etag or None)
        if fetched.unchanged:
            return SyncReport(status="noop", http_status=304, etag=fetched.etag)
        assert fetched.index is not None
        indexed = self._select_pack(source, fetched.index)
        files = await self.registry.fetch_pack(fetched.base_url, indexed)
        parsed = self._parse(files, source)
        if parsed.digest != indexed.digest:
            raise SeedPackError(
                DIGEST_DRIFT,
                f"index digest {indexed.digest} does not match the fetched pack {parsed.digest}",
            )
        source.policy = {
            **(source.policy or {}),
            "registry_etag": fetched.etag,
            "index_url": normalize_index_url(source.uri),
        }
        flag_modified(source, "policy")
        registration = await self._register(source, parsed, status="pending", etag=fetched.etag)
        return self._report(registration, parsed, etag=fetched.etag, http_status=fetched.status)

    async def upload_file(
        self, source: SeedSource, data: bytes, *, actor: str = "system"
    ) -> dict[str, Any]:
        """Register an uploaded pack (the file provider's sync surface)."""
        if not data:
            return SyncReport(status="failed", code=FILE_SOURCE_NO_CONTENT).as_dict()
        started = _utcnow()
        run = SeedSyncRun(
            source_id=source.id,
            trigger="manual",
            status="running",
            started_at=started,
            etag="",
            commit_sha="",
            error="",
        )
        self.db.add(run)
        await self.db.commit()
        report = SyncReport(status="failed")
        try:
            files = extract_pack_archive(data)
            parsed = self._parse(files, source)
            registration = await self._register(source, parsed, status="pending")
            report = self._report(registration, parsed, archive=data)
        except SeedPackError as exc:
            report = SyncReport(status="failed", code=exc.code, message=exc.detail)
        await self._finish_run(source, run, report)
        if report.status in ("failed", "partial"):
            await self._notify_failure(source, report)
        return report.as_dict()

    def _parse(self, files: Mapping[str, bytes], source: SeedSource) -> ParsedPack:
        return parse_pack(
            files,
            connectors=self.connectors,
            source_priority=source.priority,
            allow_unknown_formats=True,
        )

    def _select_pack(self, source: SeedSource, index: RepoIndex):
        wanted = (source.subpath or "").strip().strip("/")
        packs = index.packs
        if wanted:
            matches = [
                pack
                for pack in packs
                if pack.path == wanted or pack.id == wanted or pack.path.endswith(f"/{wanted}")
            ]
        else:
            matches = list(packs)
        if not matches:
            raise SeedPackError(PACK_NOT_FOUND, wanted or "no pack selected")
        if len(matches) > 1:
            raise SeedPackError(PACK_AMBIGUOUS, f"{len(matches)} packs match {wanted!r}")
        return matches[0]

    def _archive_bytes(self, parsed: ParsedPack, archive: bytes | None = None) -> bytes:
        return archive or build_pack_archive(
            {**parsed.item_files, "manifest.json": canonical_json(parsed.manifest_raw)}
        )

    def _ensure_archive(
        self, source: SeedSource, parsed: ParsedPack, *, archive: bytes | None = None
    ) -> int:
        """Store the parsed pack when its archive is absent (self-healing sync).

        A version row and its content-addressed archive can drift apart — a
        profile swap, a restored database or an object store that moved leaves
        the row without bytes. Syncing the provider again is the documented
        recovery path, so an already-registered digest still re-stores the
        archive instead of returning a silent no-op that cannot be recovered.
        """
        if self.packs.has(source.id, parsed.digest):
            return 0
        archived = self._archive_bytes(parsed, archive)
        self.packs.put(source.id, parsed.digest, archived)
        logger.warning(
            "restored the missing archive for provider %s version %s",
            source.id,
            parsed.digest,
        )
        return len(archived)

    async def _register(
        self,
        source: SeedSource,
        parsed: ParsedPack,
        *,
        status: str,
        commit_sha: str = "",
        etag: str = "",
        archive: bytes | None = None,
    ) -> Registration:
        existing = (
            await self.db.execute(
                select(SeedSourceVersion).where(
                    SeedSourceVersion.source_id == source.id,
                    SeedSourceVersion.digest == parsed.digest,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            restored = self._ensure_archive(source, parsed, archive=archive)
            return Registration(version=existing, created=False, bytes=restored or None)

        archived = self._archive_bytes(parsed, archive)
        self.packs.put(source.id, parsed.digest, archived)
        archived_size = len(archived)

        reused = (
            (
                await self.db.execute(
                    select(SeedSourceVersion.id).where(
                        SeedSourceVersion.source_id == source.id,
                        SeedSourceVersion.pack_version == parsed.manifest.version,
                        SeedSourceVersion.digest != parsed.digest,
                    )
                )
            )
            .scalars()
            .first()
        )
        version_status = "rejected" if reused is not None else status
        reason = VERSION_REUSED if reused is not None else ""
        version = SeedSourceVersion(
            source_id=source.id,
            commit_sha=commit_sha,
            etag=etag,
            digest=parsed.digest,
            manifest=parsed.manifest_raw,
            pack_version=parsed.manifest.version,
            schema_version=parsed.manifest.schema_version,
            status=version_status,
            reason=reason,
            contract_version="1.0",
            approved_at=_utcnow() if version_status == "approved" else None,
        )
        self.db.add(version)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            existing = (
                await self.db.execute(
                    select(SeedSourceVersion).where(
                        SeedSourceVersion.source_id == source.id,
                        SeedSourceVersion.digest == parsed.digest,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return Registration(version=existing, created=False)
            raise

        if version_status == "rejected":
            await audit_emit(
                self.db,
                actor="system",
                action="provider.version.rejected",
                resource_ref=audit_resource(
                    f"provider:{source.id}", f"version:{version.id}", f"digest:{parsed.digest}"
                ),
                outcome="error",
            )
            await self.db.commit()
            return Registration(
                version=version, created=True, code=VERSION_REUSED, bytes=archived_size
            )
        if version_status == "pending":
            await audit_emit(
                self.db,
                actor="system",
                action="provider.version.pending",
                resource_ref=audit_resource(
                    f"provider:{source.id}", f"version:{version.id}", f"digest:{parsed.digest}"
                ),
            )
            await self.db.commit()
            await self._notify_update(source, version)
        return Registration(version=version, created=True, bytes=archived_size)

    def _report(
        self,
        registration: Registration,
        parsed: ParsedPack,
        *,
        etag: str = "",
        commit_sha: str = "",
        http_status: int | None = None,
        archive: bytes | None = None,
    ) -> SyncReport:
        if registration.code == VERSION_REUSED:
            return SyncReport(
                status="failed",
                code=VERSION_REUSED,
                message="the pack version was reused with different content",
                digest=parsed.digest,
                version_id=str(registration.version.id),
                etag=etag,
                commit_sha=commit_sha,
                http_status=http_status,
            )
        status = "ok" if registration.created else "noop"
        return SyncReport(
            status=status,
            digest=parsed.digest,
            version_id=str(registration.version.id),
            etag=etag,
            commit_sha=commit_sha,
            http_status=http_status,
            bytes=registration.bytes or (len(archive) if archive else None),
        )

    async def _finish_run(self, source: SeedSource, run: SeedSyncRun, report: SyncReport) -> None:
        now = _utcnow()
        run.status = (
            report.status if report.status in ("ok", "noop", "failed", "partial") else "failed"
        )
        run.error = ""
        if report.code:
            run.error = f"{report.code}: {report.message}"[:2000]
        elif report.message:
            run.error = report.message[:2000]
        run.http_status = report.http_status
        run.etag = report.etag
        run.commit_sha = report.commit_sha
        run.bytes = report.bytes
        run.version_id = uuid.UUID(report.version_id) if report.version_id else None
        run.finished_at = now
        source.last_check_at = now
        source.last_error = run.error if report.status in ("failed", "partial") else ""
        await self.db.commit()

    async def _admin_ids(self) -> list[uuid.UUID]:
        return list(
            (await self.db.execute(select(User.id).where(User.is_admin.is_(True)))).scalars().all()
        )[:50]

    async def _notify_update(self, source: SeedSource, version: SeedSourceVersion) -> None:
        admins = await self._admin_ids()
        for user_id in admins:
            await NotificationService(self.db).emit(
                UPDATE_KIND,
                [user_id],
                title=f"Provider update available: {source.name}",
                body=(
                    f"{version.pack_version} is pending approval "
                    f"({version.digest[:12]}…). Review and approve it in Tools → Sources."
                ),
                payload={
                    "provider_id": str(source.id),
                    "version_id": str(version.id),
                    "link": "/settings/tools?section=sources",
                },
                source_ref={"provider_id": str(source.id)},
                dedup_key=f"{UPDATE_KIND}:{source.id}:{version.id}:{user_id}",
                dedup_ttl_days=7,
                max_per_day=10,
            )
        await self.db.commit()

    async def _notify_failure(self, source: SeedSource, report: SyncReport) -> None:
        admins = await self._admin_ids()
        detail = report.message or report.code or "sync failed"
        for user_id in admins:
            await NotificationService(self.db).emit(
                FAILED_KIND,
                [user_id],
                title=f"Provider sync failed: {source.name}",
                body=f"{detail[:400]} — last check {_utcnow():%Y-%m-%d %H:%M} UTC.",
                payload={
                    "provider_id": str(source.id),
                    "code": report.code,
                    "link": "/settings/tools?section=sources",
                },
                source_ref={"provider_id": str(source.id)},
                dedup_key=f"{FAILED_KIND}:{source.id}:{user_id}",
                dedup_ttl_days=1,
                max_per_day=3,
                severity="warning",
            )
        await self.db.commit()


async def enqueue_source_sync(
    db: AsyncSession, source: SeedSource, *, trigger: str = "manual"
) -> BackgroundJob | None:
    """Queue one provider sync under the per-source lock (idempotent)."""
    lock = f"provider_sync:{source.id}"
    active = (
        (
            await db.execute(
                select(BackgroundJob.id).where(
                    BackgroundJob.lock_key == lock,
                    BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
                )
            )
        )
        .scalars()
        .first()
    )
    if active is not None:
        return None
    job = BackgroundJob(
        job_type=PROVIDER_SYNC_JOB,
        payload={"source_id": str(source.id), "trigger": trigger},
        lock_key=lock,
        max_attempts=1,
    )
    try:
        async with db.begin_nested():
            db.add(job)
            await db.flush()
    except IntegrityError:
        return None
    await db.commit()
    return job


async def enqueue_due_provider_syncs(db: AsyncSession, *, now: datetime | None = None) -> int:
    """The scheduler tick: queue every enabled provider whose refresh is due."""
    moment = now or _utcnow()
    sources = (
        (
            await db.execute(
                select(SeedSource).where(
                    SeedSource.enabled.is_(True), SeedSource.refresh_minutes > 0
                )
            )
        )
        .scalars()
        .all()
    )
    queued = 0
    for source in sources:
        if source.last_check_at is not None:
            due_at = source.last_check_at + timedelta(minutes=source.refresh_minutes)
            if due_at > moment:
                continue
        if await enqueue_source_sync(db, source, trigger="scheduled") is not None:
            queued += 1
    return queued


__all__ = [
    "ProviderSyncService",
    "Registration",
    "SyncReport",
    "enqueue_due_provider_syncs",
    "enqueue_source_sync",
]
