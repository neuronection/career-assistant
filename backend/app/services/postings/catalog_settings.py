"""Catalog mapping run controls (plan 185 S6.3): the two admin switches —
semantic rescue and job proposals — stored as ``app_settings`` rows (the
plan-184 KV precedent; DB-only config, no env vars). Effective on the NEXT
decision: ``decide_catalog`` and the proposal writer read them per call,
there is no process state to restart. Missing rows mean the shipped
default (both ON — the rescue only fires where the overlap threshold
missed, under a deterministic evidence gate; the proposal is admin-gated
anyway), so unconfigured deployments behave exactly as shipped."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings_model import AppSetting

SEMANTIC_RESCUE_KEY = "catalog.semantic_rescue"
JOB_PROPOSALS_KEY = "catalog.job_proposals"


async def _switch_enabled(db: AsyncSession, key: str, default: bool = True) -> bool:
    row = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = row.scalars().first()
    if setting is None:
        return default
    return bool((setting.value or {}).get("enabled", default))


async def semantic_rescue_enabled(db: AsyncSession) -> bool:
    return await _switch_enabled(db, SEMANTIC_RESCUE_KEY)


async def job_proposals_enabled(db: AsyncSession) -> bool:
    return await _switch_enabled(db, JOB_PROPOSALS_KEY)


async def set_switch(db: AsyncSession, key: str, enabled: bool) -> None:
    """Upsert one switch row (the locale-service pattern)."""
    row = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = row.scalars().first()
    if setting is None:
        db.add(AppSetting(key=key, value={"enabled": enabled}))
    else:
        setting.value = {"enabled": enabled}
    await db.commit()
