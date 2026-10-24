"""AI configuration status for the SPA bootstrap (plan 118).

Derived from the existing database configuration — no new tables, no
env-var settings. Task resolution is the truth: a capability slot that
resolves is covered, and any resolution that lands on the mock provider
is reported so the UI can never hide it.

This module only reads. It resolves with ``allow_dev_bootstrap=False``
so asking "is AI configured?" never provisions the dev mock carrier.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.ai_status import AiStatusOut

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.resolution import resolve_task_model

SLOT_CAPABILITIES: tuple[str, ...] = ("text", "vision", "stt", "embeddings")


@dataclass(frozen=True)
class AiStatus:
    """What the SPA needs to know about the caller's AI configuration."""

    configured: bool
    provider_type: str | None
    default_model: str | None
    assigned_slots: int
    total_slots: int
    missing_slots: list[str] = field(default_factory=list)
    mock_active: bool = False
    setup_dismissed: bool = False

    def payload(self) -> "AiStatusOut":
        """Bootstrap JSON shape (``/me`` bootstrap ``ai`` key)."""
        from app.schemas.ai_status import AiStatusOut, AiTaskCoverageOut

        return AiStatusOut(
            configured=self.configured,
            provider_type=self.provider_type,
            default_model=self.default_model,
            task_coverage=AiTaskCoverageOut(
                assigned=self.assigned_slots,
                total=self.total_slots,
                missing=list(self.missing_slots),
            ),
            mock_active=self.mock_active,
            setup_dismissed=self.setup_dismissed,
        )


async def ai_status(
    db: AsyncSession, user_id: UUID | None, *, setup_dismissed: bool = False
) -> AiStatus:
    """Summarise the effective AI configuration for one caller.

    Args:
        db: Session used for task resolution (read-only).
        user_id: Owner the user-scope assignments resolve for.
        setup_dismissed: Whether the caller skipped the first-run setup step.

    Returns:
        The resolved status; ``configured`` mirrors the chat default slot.
    """
    resolved = {
        slot: await resolve_task_model(db, slot, user_id, allow_dev_bootstrap=False)
        for slot in SLOT_CAPABILITIES
    }
    text = resolved["text"]
    assigned = [slot for slot, model in resolved.items() if model is not None]
    missing = [slot for slot in SLOT_CAPABILITIES if slot not in assigned]
    return AiStatus(
        configured=text is not None,
        provider_type=text.provider_type if text is not None else None,
        default_model=text.model_name if text is not None else None,
        assigned_slots=len(assigned),
        total_slots=len(SLOT_CAPABILITIES),
        missing_slots=missing,
        mock_active=any(
            model is not None and model.provider_type == "mock" for model in resolved.values()
        ),
        setup_dismissed=setup_dismissed,
    )
