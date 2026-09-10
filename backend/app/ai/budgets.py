"""Generalized AI budgets — hard stops on token spend.

Every active budget matching the (task, user) context is enforced before
the gateway's attempt loop. ``ai_generations`` is the consumption ledger:
spend is summed from audit rows inside the budget's window, so budgets
can never drift from what was actually spent. A breach raises
``DomainError`` (the same quota-rejection contract as the rate limiter —
not audited, no generation happened).
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.models.ai_model import AIBudget, AIGeneration
from app.models.enums import AITaskType

WINDOWS = ("day", "month")


def window_start(window: str, now: Optional[datetime] = None) -> datetime:
    """UTC start of the active budget window."""
    now = now or datetime.now(timezone.utc)
    if window == "month":
        return datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if window == "day":
        return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    raise ValueError(f"unknown budget window: {window}")


def _matching_budgets(db: AsyncSession, task: AITaskType, user_id):
    """Active budgets whose scope covers this (task, user) call."""
    return (
        select(AIBudget)
        .where(
            AIBudget.is_active.is_(True),
            (AIBudget.task_type.is_(None)) | (AIBudget.task_type == task.value),
            (AIBudget.user_id.is_(None)) | (AIBudget.user_id == user_id),
        )
        .order_by(AIBudget.name)
    )


async def _consumed_since(db: AsyncSession, budget: AIBudget, start: datetime) -> int:
    """Tokens (in + out) spent inside the budget's scope since ``start``."""
    conditions = [
        AIGeneration.created_at >= start,
        AIGeneration.status == "ok",
    ]
    if budget.task_type is not None:
        conditions.append(AIGeneration.task_type == budget.task_type)
    if budget.user_id is not None:
        conditions.append(AIGeneration.user_id == budget.user_id)
    rows = await db.execute(
        select(
            func.coalesce(func.sum(AIGeneration.tokens_in), 0)
            + func.coalesce(func.sum(AIGeneration.tokens_out), 0)
        ).where(*conditions)
    )
    return int(rows.scalar() or 0)


async def enforce_budgets(db: AsyncSession, task: AITaskType, user_id=None) -> None:
    """Raise ``DomainError`` when any matching budget is exhausted."""
    rows = await db.execute(_matching_budgets(db, task, user_id))
    for budget in rows.scalars().all():
        try:
            start = window_start(budget.window)
        except ValueError:
            continue
        consumed = await _consumed_since(db, budget, start)
        if consumed >= budget.max_tokens:
            raise DomainError(
                f"AI budget '{budget.name}' reached "
                f"({consumed}/{budget.max_tokens} tokens this {budget.window}); "
                "an admin can raise or remove it in Settings → AI Configuration."
            )


async def usage_rollups(db: AsyncSession, window: str = "day") -> list[dict]:
    """Per-task token/call rollups from the audit ledger."""
    start = window_start(window)
    rows = await db.execute(
        select(
            AIGeneration.task_type,
            func.count(AIGeneration.id),
            func.coalesce(func.sum(AIGeneration.tokens_in), 0),
            func.coalesce(func.sum(AIGeneration.tokens_out), 0),
        )
        .where(AIGeneration.created_at >= start)
        .group_by(AIGeneration.task_type)
        .order_by(AIGeneration.task_type)
    )
    return [
        {
            "task_type": task_type,
            "calls": calls,
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
        }
        for task_type, calls, tokens_in, tokens_out in rows.all()
    ]
