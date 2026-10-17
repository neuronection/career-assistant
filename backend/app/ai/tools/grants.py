"""Per-user state-changing tool grants (D20 — the tools catalog toggle).

A ``state-changing`` registry tool executes only while the user holds an
explicit grant row (default-off posture: no row ⇒ inert, with a typed
model-visible error saying where to enable it). The toggle lives in the
tools catalog — the consent/settings surface — and rides the REST
surface only: grant state is user-authored data the model can never
write. ``destructive`` tools are rejected here by construction (never
grant-bypassable); ``read-only`` tools need no grant.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools.base import ToolRiskClass
from app.ai.tools.registry import get_tool
from app.core.errors import ValidationError
from app.models.tool_grant_model import UserToolGrant


async def has_grant(db: AsyncSession, user_id: uuid.UUID, tool_key: str) -> bool:
    row = (
        (
            await db.execute(
                select(UserToolGrant).where(
                    UserToolGrant.user_id == user_id,
                    UserToolGrant.tool_key == tool_key,
                )
            )
        )
        .scalars()
        .first()
    )
    return row is not None


async def granted_keys(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    rows = (
        (await db.execute(select(UserToolGrant.tool_key).where(UserToolGrant.user_id == user_id)))
        .scalars()
        .all()
    )
    return set(rows)


async def grant(db: AsyncSession, user_id: uuid.UUID, tool_key: str) -> None:
    """Enable one state-changing tool for one user (idempotent)."""
    tool = get_tool(tool_key)
    if tool.effective_risk_class is not ToolRiskClass.STATE_CHANGING:
        raise ValidationError(
            f"Tool {tool_key} is {tool.effective_risk_class.value} — only "
            "state-changing tools are grantable (destructive tools confirm "
            "every call and are never grant-bypassable)"
        )
    if await has_grant(db, user_id, tool.key):
        return
    db.add(UserToolGrant(user_id=user_id, tool_key=tool.key))
    await db.commit()


async def revoke(db: AsyncSession, user_id: uuid.UUID, tool_key: str) -> bool:
    """Remove the grant (the toggle off); True when a row was removed."""
    row = (
        (
            await db.execute(
                select(UserToolGrant).where(
                    UserToolGrant.user_id == user_id,
                    UserToolGrant.tool_key == tool_key,
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True
