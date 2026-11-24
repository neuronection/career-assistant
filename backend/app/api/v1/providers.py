"""User provider read surfaces (plan 218 §3.8).

The user sees published providers and their enabled/active catalog only:
no URI, sync error, policy document or version ledger. Follow/hide overlays
arrive with the visibility increment; nothing here creates a job source.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.providers import (
    UserEndpointOut,
    UserProviderDetailOut,
    UserProviderOut,
)
from app.services.deps import get_current_user
from app.services.seeds.provider_service import ProviderService

router = APIRouter(
    prefix="/providers",
    tags=["providers"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[UserProviderOut])
async def list_user_providers(db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await ProviderService(db).user_list()


@router.get("/{source_id}", response_model=UserProviderDetailOut)
async def get_user_provider(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    return await ProviderService(db).user_detail(source_id)


@router.get("/{source_id}/endpoints", response_model=list[UserEndpointOut])
async def get_user_provider_endpoints(
    source_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    return await ProviderService(db).user_endpoints(source_id)
