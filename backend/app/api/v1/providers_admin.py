"""Admin provider routes (plan 218 §3.8): publishers, versions, applies.

The storage vocabulary is ``seed_*``; the product surface is "provider".
Every action is admin-only. Sync/apply never run implicitly; an apply needs an
approved version and takes the global ``provider_apply`` lock.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.providers import (
    AdoptIn,
    ApplyOut,
    DiscoverIn,
    DiscoverOut,
    PlanOut,
    ProbeOut,
    ProviderAdminDetailOut,
    ProviderAdminOut,
    ProviderCreateIn,
    ProviderUpdateIn,
    RejectIn,
    RepositoryImportIn,
    RepositoryImportOut,
    SyncReportOut,
    SyncRunOut,
    VersionOut,
)
from app.services.deps import get_current_user, require_admin
from app.services.seeds.provider_service import MAX_UPLOAD_BYTES, ProviderService

router = APIRouter(
    prefix="/admin/providers",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _service(db: AsyncSession) -> ProviderService:
    return ProviderService(db)


@router.get("", response_model=list[ProviderAdminOut])
async def list_providers(db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await _service(db).list_admin()


@router.post("/discover", response_model=DiscoverOut)
async def discover_provider(payload: DiscoverIn, db: AsyncSession = Depends(get_db)) -> dict:
    return await _service(db).discover(payload)


@router.post("/import", response_model=RepositoryImportOut, status_code=201)
async def import_provider_repository(
    payload: RepositoryImportIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Add one provider per pack of a repository index (idempotent)."""
    return await _service(db).import_repository(payload, actor=str(user.id))


@router.post("", response_model=ProviderAdminOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: ProviderCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    service = _service(db)
    source = await service.create(payload, actor=str(user.id))
    return await service.get_admin(source.id)


@router.get("/{source_id}", response_model=ProviderAdminDetailOut)
async def get_provider(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    return await _service(db).get_admin(source_id)


@router.patch("/{source_id}", response_model=ProviderAdminDetailOut)
async def update_provider(
    source_id: uuid.UUID,
    payload: ProviderUpdateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    service = _service(db)
    await service.update(source_id, payload, actor=str(user.id))
    return await service.get_admin(source_id)


@router.delete("/{source_id}")
async def delete_provider(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    return await _service(db).delete(source_id, actor=str(user.id))


@router.post("/{source_id}/sync", response_model=SyncReportOut)
async def sync_provider(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    return await _service(db).sync(source_id, actor=str(user.id))


@router.post("/{source_id}/upload", response_model=SyncReportOut)
async def upload_provider_pack(
    source_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "pack upload exceeds the 64 MB cap",
        )
    return await _service(db).upload(source_id, data, actor=str(user.id))


@router.get("/{source_id}/versions", response_model=list[VersionOut])
async def list_provider_versions(
    source_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    return await _service(db).versions(source_id)


@router.get("/{source_id}/versions/{version_id}/plan", response_model=PlanOut)
async def plan_provider_version(
    source_id: uuid.UUID, version_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    return await _service(db).plan(source_id, version_id)


@router.post("/{source_id}/versions/{version_id}/approve", response_model=VersionOut)
async def approve_provider_version(
    source_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    return await _service(db).approve(source_id, version_id, actor=str(user.id))


@router.post("/{source_id}/versions/{version_id}/reject", response_model=VersionOut)
async def reject_provider_version(
    source_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: RejectIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    return await _service(db).reject(
        source_id, version_id, reason=payload.reason, actor=str(user.id)
    )


@router.post("/{source_id}/versions/{version_id}/revoke", response_model=ApplyOut)
async def revoke_provider_version(
    source_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    return await _service(db).revoke(source_id, version_id, actor=str(user.id))


@router.post("/{source_id}/versions/{version_id}/apply", response_model=ApplyOut)
async def apply_provider_version(
    source_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    return await _service(db).apply(source_id, version_id, actor=str(user.id))


@router.post("/{source_id}/adopt", response_model=ApplyOut)
async def adopt_provider_version(
    source_id: uuid.UUID,
    payload: AdoptIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    return await _service(db).adopt(
        source_id,
        payload.version_id,
        seed_keys=payload.seed_keys,
        actor=str(user.id),
    )


@router.post("/{source_id}/items/{seed_key}/enable")
async def enable_provider_item(
    source_id: uuid.UUID, seed_key: str, db: AsyncSession = Depends(get_db)
) -> dict:
    enabled = await _service(db).set_item_enabled(source_id, seed_key, True)
    if not enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    return {"seed_key": seed_key, "enabled": True}


@router.post("/{source_id}/items/{seed_key}/disable")
async def disable_provider_item(
    source_id: uuid.UUID, seed_key: str, db: AsyncSession = Depends(get_db)
) -> dict:
    enabled = await _service(db).set_item_enabled(source_id, seed_key, False)
    if not enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    return {"seed_key": seed_key, "enabled": False}


@router.post("/{source_id}/items/{seed_key}/retire")
async def retire_provider_item(
    source_id: uuid.UUID, seed_key: str, db: AsyncSession = Depends(get_db)
) -> dict:
    retired = await _service(db).retire_item(source_id, seed_key)
    if not retired:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    return {"seed_key": seed_key, "retired": True}


@router.get("/{source_id}/sync-runs", response_model=list[SyncRunOut])
async def provider_sync_runs(
    source_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await _service(db).sync_runs(source_id, limit=limit)


@router.post("/{source_id}/endpoints/{seed_key}/probe", response_model=ProbeOut)
async def probe_provider_endpoint(
    source_id: uuid.UUID,
    seed_key: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    return await _service(db).probe(source_id, seed_key, actor=str(user.id))
