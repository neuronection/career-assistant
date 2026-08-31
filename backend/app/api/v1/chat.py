import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import quick_assist
from app.ai.agents.chatbot import CHATBOT, prepare_chat_prompt
from app.ai.provider import StructuredStream, partial_answer_text
from app.ai.schemas import ChatReply
from app.core.database import get_db
from app.core.errors import AINotConfiguredError, DomainError
from app.models.enums import AITaskType
from app.schemas.chat import (
    AssistIn,
    AssistOut,
    MessageIn,
    MessageOut,
    SessionCreate,
    SessionOut,
)
from app.services.chat_service import ChatService
from app.services.profile_service import ProfileService
from app.services.deps import get_current_user, get_profile_for_user

router = APIRouter(tags=["chat"])


@router.post("/chat/sessions", response_model=SessionOut, status_code=201)
async def create_session(
    data: SessionCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionOut:
    """Start a chat session."""
    return SessionOut.model_validate(
        await ChatService(db).create_session(user.id, data)
    )


@router.get("/chat/sessions", response_model=list[SessionOut])
async def list_sessions(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[SessionOut]:
    """The caller's chat sessions."""
    rows = await ChatService(db).list_sessions(user.id)
    return [SessionOut.model_validate(s) for s in rows]


@router.get("/chat/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_messages(
    session_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    """All messages of a session."""
    rows = await ChatService(db).messages(user.id, session_id)
    return [MessageOut.model_validate(m) for m in rows]


@router.post("/chat/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID,
    data: MessageIn,
    stream: bool = Query(default=False),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a message; returns [user_message, assistant_reply] — or an SSE
    stream (`?stream=true`) of status/delta/meta/done events."""
    if not stream:
        return await _send_sync(session_id, data, user, db)
    return await _send_stream(session_id, data, user, db)


async def _send_sync(session_id, data, user, db) -> list[MessageOut]:
    profile = await get_profile_for_user(db, user.id)
    try:
        await ChatService(db).send_message(user.id, session_id, data.content, profile)
    except AINotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    rows = await ChatService(db).messages(user.id, session_id)
    return [MessageOut.model_validate(m) for m in rows[-2:]]


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _send_stream(session_id, data, user, db):
    profile = await get_profile_for_user(db, user.id)
    try:
        session, history, _ = await ChatService(db).begin_message(
            user.id, session_id, data.content
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    prompt, tool_metadata = await prepare_chat_prompt(
        db,
        profile_summary=await ProfileService(db).profile_summary(profile),
        history=history,
        message=data.content,
        page_context=session.context,
        user_id=user.id,
    )

    stream = StructuredStream()

    async def events():
        found = sum(
            len(tool.get("results") or []) for tool in tool_metadata.get("tools", [])
        )
        yield _sse(
            "status",
            {"stage": "searching the catalog", "found": found},
        )
        sent = 0
        try:
            async for chunk in stream.chunks(
                db, AITaskType.CHAT, ChatReply, CHATBOT, prompt, user.id
            ):
                partial = partial_answer_text("".join(stream._raw))
                if len(partial) > sent:
                    yield _sse("delta", {"text": partial[sent:]})
                    sent = len(partial)
            if stream.reply is None:
                raise DomainError(stream.error or "AI produced no valid reply")
            message = await ChatService(db).complete_message(
                session, stream.reply, tool_metadata
            )
            yield _sse(
                "meta",
                {
                    "message_id": str(message.id),
                    "referenced_job_codes": stream.reply.referenced_job_codes,
                    "referenced_posting_refs": tool_metadata.get("refs", []),
                    "explore_query": tool_metadata.get("explore_query"),
                },
            )
            yield _sse("done", {"ok": True})
        except DomainError as exc:
            yield _sse("error", {"detail": str(exc)})
        except Exception as exc:  # noqa: BLE001 — stream must end cleanly
            yield _sse("error", {"detail": f"AI error: {exc}"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/ai/assist", response_model=AssistOut)
async def assist(
    data: AssistIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> AssistOut:
    """Contextual quick answer for the popup Ask-AI buttons."""
    profile = await get_profile_for_user(db, user.id)
    try:
        reply = await quick_assist(
            db,
            user.id,
            question=data.question,
            page=data.page,
            job_code=data.job_code,
            profile_summary=await profile_summary_for(db, profile),
        )
    except AINotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return AssistOut(
        answer=reply.answer, referenced_job_codes=reply.referenced_job_codes
    )


async def profile_summary_for(db, profile) -> str:
    """Compact profile line for quick assist."""

    return await ProfileService(db).profile_summary(profile)
