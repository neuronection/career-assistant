"""Typed assessment-bank availability state (plan 225 S1).

The question bank is reference data that arrives through the seed-pack lane;
a fresh instance before the reference-banks pack is applied has no bank. The
state is exposed as a domain refusal when a run needs the bank and none is
installed, and as a typed phase notice when the bank exists but a phase has
no question eligible for the caller's stage.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.assessment_model import AssessmentQuestion
from app.models.enums import QuestionStatus

REFERENCE_BANK_PACK = "neuronection-reference-banks"
BANK_NOT_LOADED_CODE = "ASSESSMENT_BANK_NOT_LOADED"
BANK_PHASE_EMPTY_CODE = "ASSESSMENT_BANK_PHASE_EMPTY"


@dataclass(frozen=True)
class AssessmentBankState:
    """How many active bank questions are installed, if any."""

    question_count: int
    pack: str = REFERENCE_BANK_PACK

    @property
    def loaded(self) -> bool:
        """True once at least one active bank question exists."""
        return self.question_count > 0

    @property
    def code(self) -> str:
        """The typed state code (``loaded`` or the not-loaded refusal)."""
        return "loaded" if self.loaded else BANK_NOT_LOADED_CODE


async def assessment_bank_state(db: AsyncSession) -> AssessmentBankState:
    """Read the installed bank state (active rows only, never run clones)."""
    count = await db.scalar(
        select(func.count())
        .select_from(AssessmentQuestion)
        .where(
            AssessmentQuestion.run_id.is_(None),
            AssessmentQuestion.status == QuestionStatus.ACTIVE.value,
        )
    )
    return AssessmentBankState(question_count=int(count or 0))


def bank_phase_notice(phase: int) -> dict:
    """The typed notice recorded when a bank phase yields no questions."""
    return {
        "code": BANK_PHASE_EMPTY_CODE,
        "phase": phase,
        "pack": REFERENCE_BANK_PACK,
        "detail": (
            f"phase {phase} has no assessment question matching this profile; "
            f"apply the {REFERENCE_BANK_PACK} pack or widen the question stages"
        ),
    }


class AssessmentBankNotLoadedError(ConflictError):
    """Starting a bank-backed run requires an applied question bank."""

    def __init__(self, state: AssessmentBankState | None = None) -> None:
        self.state = state or AssessmentBankState(question_count=0)
        self.pack = self.state.pack
        super().__init__(
            f"assessment bank not loaded; apply the {self.pack} pack before starting a run"
        )

    @property
    def code(self) -> str:
        """The typed refusal code."""
        return BANK_NOT_LOADED_CODE


__all__ = [
    "BANK_NOT_LOADED_CODE",
    "BANK_PHASE_EMPTY_CODE",
    "REFERENCE_BANK_PACK",
    "AssessmentBankNotLoadedError",
    "AssessmentBankState",
    "assessment_bank_state",
    "bank_phase_notice",
]
