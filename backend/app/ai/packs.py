"""Skill-pack resolution: latest published bank pack per
task. Packs are content overlays — the gateway appends their
instructions to the code-owned system prompt and pins the resolved
version on the audit row. Authoring is DB-level for now; user-authored
packs ride 37's import machinery later.
"""

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill_pack_model import AISkillPack


async def resolve_pack(
    db: AsyncSession, task_value: str, *, user_id: Optional[uuid.UUID] = None
) -> Optional[AISkillPack]:
    """The governing pack for a task: latest published version, bank
    scope (user-authored packs join in a later slice via 37's import)."""
    rows = await db.execute(
        select(AISkillPack)
        .where(
            AISkillPack.task == task_value,
            AISkillPack.status == "published",
            AISkillPack.author_key == "bank",
        )
        .order_by(AISkillPack.version.desc())
        .limit(1)
    )
    return rows.scalars().first()


def compose_system(system: str, pack: Optional[AISkillPack]) -> str:
    """Pack instructions appended — the code prompt stays authoritative
    for schema/validation framing; the pack steers tone and structure."""
    if pack is None:
        return system
    return (
        f"{system}\n\nSKILL PACK — {pack.title} (v{pack.version}):\n{pack.instructions}"
    )
