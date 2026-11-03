"""Catalog mapping run controls (plan 185 S6.3): the job-proposal switch,
stored as an ``app_settings`` row (the plan-184 KV precedent; DB-only
config, no env vars). Effective on the NEXT decision:
``job_proposal_service`` reads it per call, there is no process state to
restart. A missing row means the shipped default (ON — the proposal is
admin-gated anyway), so unconfigured deployments behave exactly as
shipped."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings_model import AppSetting

JOB_PROPOSALS_KEY = "catalog.job_proposals"
#: Plan 185's semantic-rescue switch, restored on the family vector store
#: (plan 50 P2a). Absent row = shipped default ON: the rescue only fires where
#: the deterministic overlap missed, under the shared-skill gate, and any
#: embedding failure degrades to the overlap-only decision.
SEMANTIC_RESCUE_KEY = "catalog.semantic_rescue"


async def _switch_enabled(db: AsyncSession, key: str, default: bool = True) -> bool:
    row = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = row.scalars().first()
    if setting is None:
        return default
    return bool((setting.value or {}).get("enabled", default))


async def job_proposals_enabled(db: AsyncSession) -> bool:
    return await _switch_enabled(db, JOB_PROPOSALS_KEY)


async def semantic_rescue_enabled(db: AsyncSession) -> bool:
    """The plan-185 rescue switch (default ON), read per decision."""
    return await _switch_enabled(db, SEMANTIC_RESCUE_KEY)


async def set_switch(db: AsyncSession, key: str, enabled: bool) -> None:
    """Upsert one switch row (the locale-service pattern)."""
    row = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = row.scalars().first()
    if setting is None:
        db.add(AppSetting(key=key, value={"enabled": enabled}))
    else:
        setting.value = {"enabled": enabled}
    await db.commit()
