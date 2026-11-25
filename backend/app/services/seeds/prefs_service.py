"""User provider subscriptions and source preferences (plan 218 §3.12)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.posting_model import JobSource
from app.models.seed_model import ProviderSubscription, SeedSource, SourcePref


def _provider_out(row: ProviderSubscription) -> dict:
    return {
        "id": str(row.id),
        "provider_id": str(row.seed_source_id),
        "enabled": row.enabled,
        "mode": row.mode,
        "collections": list(row.collections or []),
        "filters": dict(row.filters or {}),
    }


def _source_out(row: SourcePref) -> dict:
    return {
        "id": str(row.id),
        "source_id": str(row.job_source_id),
        "hidden": row.hidden,
        "priority": row.priority,
        "filters": dict(row.filters or {}),
    }


class ProviderPrefsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_subscriptions(self, user_id: uuid.UUID) -> list[dict]:
        rows = (
            (
                await self.db.execute(
                    select(ProviderSubscription)
                    .where(ProviderSubscription.user_id == user_id)
                    .order_by(ProviderSubscription.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [_provider_out(row) for row in rows]

    async def upsert_subscription(self, user_id: uuid.UUID, provider_id: uuid.UUID, data) -> dict:
        if await self.db.get(SeedSource, provider_id) is None:
            raise NotFoundError("provider not found")
        row = (
            await self.db.execute(
                select(ProviderSubscription).where(
                    ProviderSubscription.user_id == user_id,
                    ProviderSubscription.seed_source_id == provider_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProviderSubscription(user_id=user_id, seed_source_id=provider_id)
            self.db.add(row)
        row.enabled = data.enabled
        row.mode = data.mode
        row.collections = list(data.collections)
        row.filters = dict(data.filters)
        await self.db.commit()
        await self.db.refresh(row)
        return _provider_out(row)

    async def delete_subscription(self, user_id: uuid.UUID, provider_id: uuid.UUID) -> bool:
        row = (
            await self.db.execute(
                select(ProviderSubscription).where(
                    ProviderSubscription.user_id == user_id,
                    ProviderSubscription.seed_source_id == provider_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    async def list_source_prefs(self, user_id: uuid.UUID) -> list[dict]:
        rows = (
            (
                await self.db.execute(
                    select(SourcePref)
                    .where(SourcePref.user_id == user_id)
                    .order_by(SourcePref.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [_source_out(row) for row in rows]

    async def upsert_source_pref(self, user_id: uuid.UUID, source_id: uuid.UUID, data) -> dict:
        if await self.db.get(JobSource, source_id) is None:
            raise NotFoundError("source not found")
        row = (
            await self.db.execute(
                select(SourcePref).where(
                    SourcePref.user_id == user_id,
                    SourcePref.job_source_id == source_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = SourcePref(user_id=user_id, job_source_id=source_id)
            self.db.add(row)
        row.hidden = data.hidden
        row.priority = data.priority
        row.filters = dict(data.filters)
        await self.db.commit()
        await self.db.refresh(row)
        return _source_out(row)

    async def delete_source_pref(self, user_id: uuid.UUID, source_id: uuid.UUID) -> bool:
        row = (
            await self.db.execute(
                select(SourcePref).where(
                    SourcePref.user_id == user_id,
                    SourcePref.job_source_id == source_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True


__all__ = ["ProviderPrefsService"]
