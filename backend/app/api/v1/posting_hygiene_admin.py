"""Admin posting-hygiene console (plan 212 S2.2).

One admin-only namespace over ``hygiene_service``: list cross-source
duplicate proposals, re-run the deterministic scan, merge a pair or clear
a merge (the undo). No model call and no "scam" verdict.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.deps import require_admin
from app.services.postings import hygiene_service

router = APIRouter(
    prefix="/admin/posting-hygiene",
    tags=["posting-hygiene"],
    dependencies=[Depends(require_admin)],
)


class MergeIn(BaseModel):
    duplicate_id: uuid.UUID
    canonical_id: uuid.UUID


class ClearIn(BaseModel):
    posting_id: uuid.UUID


@router.get("")
async def hygiene_overview(db: AsyncSession = Depends(get_db)) -> dict:
    return await hygiene_service.overview(db)


@router.post("/scan")
async def hygiene_scan(db: AsyncSession = Depends(get_db)) -> dict:
    return await hygiene_service.scan_duplicates(db)


@router.post("/merge")
async def hygiene_merge(data: MergeIn, db: AsyncSession = Depends(get_db)) -> dict:
    posting = await hygiene_service.merge_duplicate(db, data.duplicate_id, data.canonical_id)
    return {"id": str(posting.id), "duplicate_of_id": str(posting.duplicate_of_id or "")}


@router.post("/clear")
async def hygiene_clear(data: ClearIn, db: AsyncSession = Depends(get_db)) -> dict:
    posting = await hygiene_service.clear_duplicate(db, data.posting_id)
    return {"id": str(posting.id), "duplicate_of_id": None}
