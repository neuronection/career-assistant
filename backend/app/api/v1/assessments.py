"""Assessment pipeline endpoints (Phase 23)."""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AINotConfiguredError, DomainError
from app.services.assessment.runner import AssessmentService
from app.services.deps import get_current_user

router = APIRouter(prefix="/assessments", tags=["assessments"])


class CreateRunIn(BaseModel):
    kind: str = "full"
    context: dict = Field(default_factory=dict)


class AnswersIn(BaseModel):
    answers: list[dict] = Field(default_factory=list, max_length=30)


class AssistIn(BaseModel):
    question_id: str


@router.post("", status_code=201)
async def create_run(
    body: CreateRunIn = Body(default=CreateRunIn()),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start a run (kind: onboarding | full | custom + context)."""
    service = AssessmentService(db)
    run = await service.create_run(user.id, body.kind, body.context)
    return await service.state(run)


@router.get("")
async def history(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """The caller's runs, newest first."""
    runs = await AssessmentService(db).history(user.id)
    return [
        {
            "id": str(r.id),
            "kind": r.kind,
            "status": r.status,
            "current_phase": r.current_phase,
            "phase_order": r.phase_order,
            "created_at": r.created_at.isoformat(),
        }
        for r in runs
    ]


@router.get("/{run_id}")
async def get_state(
    run_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """State, progress and the current phase's questions."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    return await service.state(run)


@router.post("/{run_id}/answers")
async def submit_answers(
    run_id: UUID,
    body: AnswersIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Batch save-on-answer (skips pass null/{} answers)."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    try:
        return await service.submit_answers(run, body.answers)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{run_id}/advance")
async def advance(
    run_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Score the current phase; on the last phase, complete + apply results."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    try:
        return await service.advance(run, user.id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{run_id}/cancel")
async def cancel(
    run_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Abandon a run (history keeps it; outputs are not applied)."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    return await service.cancel(run)


@router.post("/{run_id}/assist")
async def assist(
    run_id: UUID,
    body: AssistIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ask AI about a specific question (audited, rate-limited like assist)."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    try:
        answer = await service.assist(run, body.question_id)
    except AINotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"answer": answer}


@router.get("/{run_id}/results")
async def results(
    run_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Derived profile delta + shortlist (diffable across runs)."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    return await service.results(run)
