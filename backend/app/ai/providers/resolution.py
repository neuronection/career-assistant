"""Task→model resolution: USER assignment > SYSTEM assignment (task) >
'default' assignment (same scope order). AI configuration lives exclusively
in the database (managed via Settings → AI Configuration) — there are no
env-var AI settings.

In development/test, when nothing is configured, a system-scope mock
provider is auto-provisioned so the whole app works offline out of the box.
In production, unconfigured tasks resolve to ``None`` → AI endpoints return
503 until an admin configures providers in the UI.
"""

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment

logger = logging.getLogger(__name__)

DEFAULT_TASK = "default"

MOCK_PROVIDER_NAME = "Built-in Mock (dev only)"


@dataclass
class ResolvedModel:
    """The effective model configuration for one AI task invocation."""

    provider_type: str
    base_url: str
    api_key: Optional[str]
    model_name: str
    source: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


async def _find_assignment(
    db: AsyncSession, task_type: str, scope: str, user_id: Optional[UUID]
) -> Optional[tuple[AIProvider, AIModel]]:
    """Active assignment (provider+model) for a task at one scope."""
    conditions = [
        AITaskAssignment.task_type == task_type,
        AITaskAssignment.is_active.is_(True),
        AITaskAssignment.scope == scope,
        AIModel.is_active.is_(True),
        AIProvider.is_active.is_(True),
    ]
    if scope == "user":
        if user_id is None:
            return None
        conditions.append(AITaskAssignment.user_id == user_id)
    rows = await db.execute(
        select(AITaskAssignment, AIProvider, AIModel)
        .join(AIProvider, AITaskAssignment.provider_id == AIProvider.id)
        .join(AIModel, AITaskAssignment.model_id == AIModel.id)
        .where(*conditions)
        .limit(1)
    )
    row = rows.first()
    return (row[1], row[2]) if row else None


async def ensure_dev_bootstrap(db: AsyncSession) -> None:
    """Dev/test convenience: seed a system mock provider once, if empty."""
    if not settings.is_dev:
        return
    any_provider = await db.execute(select(AIProvider.id).limit(1))
    if any_provider.scalars().first() is not None:
        return
    provider = AIProvider(
        name=MOCK_PROVIDER_NAME,
        scope="system",
        provider_type="mock",
        api_base="mock://local",
    )
    db.add(provider)
    await db.flush()
    models = {}
    for model_name in ("mock-large", "mock-small"):
        model = AIModel(provider_id=provider.id, name=model_name, model_name=model_name)
        db.add(model)
        await db.flush()
        models[model_name] = model
    db.add(
        AITaskAssignment(
            task_type=DEFAULT_TASK,
            scope="system",
            provider_id=provider.id,
            model_id=models["mock-large"].id,
        )
    )
    await db.commit()
    logger.info("Dev bootstrap: seeded system mock provider (mock-large/mock-small).")


async def _resolve_scanned(
    db: AsyncSession, task_type: str, user_id: Optional[UUID], source_suffix: str = ""
) -> Optional[ResolvedModel]:
    """Scan task-specific then default assignments, user scope before system."""
    for task in (task_type, DEFAULT_TASK):
        for scope in ("user", "system"):
            found = await _find_assignment(db, task, scope, user_id)
            if found:
                provider, model = found
                return ResolvedModel(
                    provider_type=provider.provider_type,
                    base_url=provider.api_base,
                    api_key=provider.api_key,
                    model_name=model.model_name,
                    source=f"{scope}:{task}{source_suffix}",
                    temperature=model.temperature,
                    max_tokens=model.max_tokens,
                )
    return None


async def resolve_task_model(
    db: AsyncSession,
    task_type: str,
    user_id: Optional[UUID] = None,
) -> Optional[ResolvedModel]:
    """Resolve the effective provider/model for a task and user.

    Returns ``None`` when nothing is configured (production before an admin
    sets up providers; dev auto-provisions the mock provider instead).
    """
    resolved = await _resolve_scanned(db, task_type, user_id)
    if resolved is not None:
        return resolved
    await ensure_dev_bootstrap(db)
    return await _resolve_scanned(
        db, task_type, user_id, source_suffix=" (dev bootstrap)"
    )


def known_task_types() -> list[dict]:
    """Task types available for assignment (for the settings UI)."""
    from app.models.enums import AITaskType

    tasks = [{"value": t.value, "label": t.value.replace("_", " ")} for t in AITaskType]
    tasks.append({"value": DEFAULT_TASK, "label": "default (all tasks)"})
    return tasks
