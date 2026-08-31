"""AI target resolver: maps a free-text job title onto catalog families +
skills (AITaskType.TARGET_RESOLVE, audited). Deterministic alias/trigram
matching runs first; this fallback may only return existing taxonomy keys —
never free-text labels (plan-21 discipline)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.provider import ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType
from pydantic import BaseModel, Field


class TargetResolution(BaseModel):
    family_keys: list[str] = Field(default_factory=list, max_length=6)
    skill_keys: list[str] = Field(default_factory=list, max_length=15)


def _mock_resolve(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    query = str(ctx.get("query") or "").lower()
    families = [f for f in (ctx.get("family_keys") or []) if f in query]
    if not families:
        families = (ctx.get("family_keys") or [])[:1]
    skills = [s for s in (ctx.get("skill_keys") or []) if s in query]
    return {"family_keys": families[:3], "skill_keys": skills[:10]}


register_mock_fixture(AITaskType.TARGET_RESOLVE, _mock_resolve)


async def resolve_target(
    db: AsyncSession,
    user_id,
    query: str,
    family_keys: list[str],
    skill_keys: list[str],
) -> TargetResolution:
    """Fallback resolver — validated against the provided key universe."""
    result = await ainvoke_structured(
        db,
        AITaskType.TARGET_RESOLVE,
        TargetResolution,
        system=(
            "You map a free-text job title onto career catalog families and "
            "skills. Return only keys that appear verbatim in the provided "
            "lists — never invent keys, never return free-text labels."
        ),
        user=context_json(
            {
                "query": query,
                "family_keys": family_keys,
                "skill_keys": skill_keys,
            }
        ),
        user_id=user_id,
    )
    known_families = set(family_keys)
    known_skills = set(skill_keys)
    return TargetResolution(
        family_keys=[k for k in result.family_keys if k in known_families],
        skill_keys=[k for k in result.skill_keys if k in known_skills],
    )
