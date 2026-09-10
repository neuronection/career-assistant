"""Interview practice endpoints: session create (plan draft),
history, detail and plan editing. The practice loop itself rides the
chat endpoint (slice 35.2) — a session kind, not a tool."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.interview import (
    InterviewPlanPatch,
    InterviewSessionCreate,
    InterviewSessionOut,
)
from app.services.deps import get_current_user
from app.services.interview_service import InterviewService

router = APIRouter(prefix="/interview", tags=["interview"])


def _session_out(session) -> InterviewSessionOut:
    return InterviewSessionOut(
        id=session.id,
        kind=session.kind,
        status=session.status,
        role_label=session.role_label,
        posting_ref=session.posting.ref if session.posting is not None else None,
        chat_session_id=session.chat_session_id,
        plan=session.plan or [],
        rubric_scores=session.rubric_scores or [],
        debrief=session.debrief,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.post("/sessions", response_model=InterviewSessionOut, status_code=201)
async def create_session(
    payload: InterviewSessionCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterviewSessionOut:
    """Create a practice session: generate the question-plan draft from
    the posting extract (or the catalog archetype). Unconfigured AI → 503."""
    session = await InterviewService(db).create(user.id, payload)
    return _session_out(session)


@router.get("/sessions", response_model=list[InterviewSessionOut])
async def list_sessions(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InterviewSessionOut]:
    """The caller's practice sessions, most recently updated first."""
    rows = await InterviewService(db).list_sessions(user.id)
    return [_session_out(session) for session in rows]


@router.get("/sessions/{session_id}", response_model=InterviewSessionOut)
async def get_session(
    session_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterviewSessionOut:
    """One practice session with plan, rubric and debrief."""
    return _session_out(await InterviewService(db).get(user.id, session_id))


@router.patch("/sessions/{session_id}/plan", response_model=InterviewSessionOut)
async def patch_plan(
    session_id: uuid.UUID,
    payload: InterviewPlanPatch,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterviewSessionOut:
    """Edit the question plan (add/remove/reorder) before or while
    practicing; already-answered questions cannot be removed."""
    session = await InterviewService(db).patch_plan(user.id, session_id, payload)
    return _session_out(session)


@router.post("/sessions/{session_id}/start", response_model=InterviewSessionOut)
async def start_session(
    session_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterviewSessionOut:
    """Start practicing: bind a chat session (the transcript lives in
    chat) and seed the opening question. Resuming an active
    session returns it unchanged."""
    from app.ai.agents.interview_coach import render_opening_question
    from app.core.errors import DomainError
    from app.schemas.chat import SessionCreate
    from app.services.chat_service import ChatService

    service = InterviewService(db)
    interview = await service.get(user.id, session_id)
    if interview.status == "active" and interview.chat_session_id is not None:
        return _session_out(interview)
    if interview.status != "planned":
        raise DomainError("This session can no longer be started")
    chat = await ChatService(db).create_session(
        user.id,
        SessionCreate(
            title=f"Interview — {interview.role_label}"[:200],
            context={
                "surface": "interview",
                "interview_id": str(interview.id),
            },
        ),
    )
    plan = interview.plan or []
    if not plan:
        raise DomainError("This session has no question plan")
    await ChatService(db).seed_assistant_message(
        chat,
        render_opening_question(plan[0], len(plan)),
        {
            "surface": "interview",
            "interview_id": str(interview.id),
            "question_id": plan[0].get("id"),
        },
    )
    return _session_out(await service.set_chat_session(user.id, session_id, chat.id))


@router.post("/sessions/{session_id}/debrief", response_model=InterviewSessionOut)
async def debrief_session(
    session_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterviewSessionOut:
    """Generate the debrief for a completed session (idempotent): the
    rubric aggregate is deterministic math; the narrative is one audited
    `interview_debrief` call; resources link learning content."""
    return _session_out(
        await InterviewService(db).generate_debrief(user.id, session_id)
    )


@router.post("/sessions/{session_id}/retry", response_model=InterviewSessionOut)
async def retry_weak_areas(
    session_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterviewSessionOut:
    """One-click weak-area retry: a fresh planned session reusing the
    weak questions from this debrief."""
    return _session_out(await InterviewService(db).retry_weak(user.id, session_id))
