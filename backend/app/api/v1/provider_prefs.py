"""User provider follow/hide routes (plan 218 §3.12)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.provider_prefs import (
    ProviderSubscriptionIn,
    ProviderSubscriptionOut,
    SourcePrefIn,
    SourcePrefOut,
)
from app.services.deps import get_current_user
from app.services.seeds.prefs_service import ProviderPrefsService

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/provider-subscriptions", response_model=list[ProviderSubscriptionOut])
async def list_provider_subscriptions(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    return await ProviderPrefsService(db).list_subscriptions(user.id)


@router.put("/provider-subscriptions/{provider_id}", response_model=ProviderSubscriptionOut)
async def put_provider_subscription(
    provider_id: uuid.UUID,
    payload: ProviderSubscriptionIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await ProviderPrefsService(db).upsert_subscription(user.id, provider_id, payload)


@router.delete("/provider-subscriptions/{provider_id}")
async def delete_provider_subscription(
    provider_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    deleted = await ProviderPrefsService(db).delete_subscription(user.id, provider_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "subscription not found")
    return {"provider_id": str(provider_id), "deleted": True}


@router.get("/source-prefs", response_model=list[SourcePrefOut])
async def list_source_prefs(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    return await ProviderPrefsService(db).list_source_prefs(user.id)


@router.put("/source-prefs/{source_id}", response_model=SourcePrefOut)
async def put_source_pref(
    source_id: uuid.UUID,
    payload: SourcePrefIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await ProviderPrefsService(db).upsert_source_pref(user.id, source_id, payload)


@router.delete("/source-prefs/{source_id}")
async def delete_source_pref(
    source_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    deleted = await ProviderPrefsService(db).delete_source_pref(user.id, source_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source preference not found")
    return {"source_id": str(source_id), "deleted": True}
