import asyncio
import json
import time
import uuid
from contextlib import suppress
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import quick_assist
from app.ai.gateway import partial_answer_text
from app.core.database import get_db
from app.core.errors import AINotConfiguredError, DomainError
from app.schemas.chat import (
    AssistIn,
    AssistOut,
    MessageIn,
    MessageOut,
    SessionCreate,
    SessionOut,
    SessionUpdate,
    TreeOut,
)
from app.services.chat_digest_cache import context_without_cache
from app.services.chat_service import ChatService
from app.services.profile_service import ProfileService
from app.services.deps import get_current_user, get_profile_for_user

router = APIRouter(tags=["chat"])

#: Single-flight per session (plan 98): one streaming turn at a time —
#: concurrent turns on one session would interleave persistence and
#: checkpoint the same thread twice.
_ACTIVE_TURNS: set[uuid.UUID] = set()


def _session_out(session, last_activity: datetime) -> SessionOut:
    return SessionOut(
        id=session.id,
        title=session.title,
        context=context_without_cache(session.context),
        created_at=session.created_at,
        last_activity_at=last_activity,
    )


@router.post("/chat/sessions", response_model=SessionOut, status_code=201)
async def create_session(
    data: SessionCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionOut:
    """Start a chat session."""
    session = await ChatService(db).create_session(user.id, data)
    return _session_out(session, session.updated_at or session.created_at)


@router.get("/chat/sessions", response_model=list[SessionOut])
async def list_sessions(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[SessionOut]:
    """The caller's chat sessions, most recently active first."""
    rows = await ChatService(db).list_sessions(user.id)
    return [_session_out(session, last_activity) for session, last_activity in rows]


@router.patch("/chat/sessions/{session_id}", response_model=SessionOut)
async def rename_session(
    session_id: uuid.UUID,
    data: SessionUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionOut:
    """Rename a chat session."""
    session = await ChatService(db).rename_session(user.id, session_id, data.title)
    return _session_out(session, await ChatService(db).last_activity(session))


@router.delete("/chat/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a chat session and its messages."""
    await ChatService(db).delete_session(user.id, session_id)


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
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a message; responds with the SSE turn stream
    (status/delta/tool_call/proposal/meta/done events)."""
    return await _send_stream(session_id, data, user, db)


async def _resolve_attachments(db, user, data) -> list[dict] | None:
    """Validated attachment snapshots (plan 78); 422 on unresolvable —
    never silently dropped."""
    from app.core.errors import ValidationError as DomainValidationError
    from app.services.chat_attachments import resolve_attachments

    if not data.attachments:
        return None
    try:
        return await resolve_attachments(db, user.id, data.attachments)
    except DomainValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _cv_builder_cv(session, db):
    """The owned CV a builder-bound session references, or None."""
    context = session.context or {}
    if context.get("surface") != "cv_builder" or not context.get("cv_id"):
        return None
    import uuid as uuid_mod

    from app.services.cv_service import CvService

    try:
        cv_id = uuid_mod.UUID(str(context["cv_id"]))
    except ValueError as exc:
        raise DomainError("Invalid CV reference in session context") from exc
    return await CvService(db).get_owned(cv_id, session.user_id)


async def _interview_session(session, db):
    """The owned interview session a practice-bound chat session serves,
    or None."""
    context = session.context or {}
    if context.get("surface") != "interview" or not context.get("interview_id"):
        return None
    import uuid as uuid_mod

    from app.services.interview_service import InterviewService

    try:
        interview_id = uuid_mod.UUID(str(context["interview_id"]))
    except ValueError as exc:
        raise DomainError("Invalid interview reference in session context") from exc
    return await InterviewService(db).get(session.user_id, interview_id)


async def _run_turn_stream(session, history, content, user_message_id, user, db):
    """Shared generation stream: family flow events + legacy contract,
    persisted under `user_message_id` (send, edit-branch, regenerate).

    Sessions bound to a CV (`context.surface == "cv_builder"`)
    run the builder copilot loop instead of the generic chat flow — same
    endpoint, same SSE contract, plus a terminal `builder_state` event.
    Interview-bound sessions (`context.surface == "interview"`)
    run the practice turn the same way, plus a terminal `interview_state`.
    """
    interview = await _interview_session(session, db)
    if interview is not None:
        from app.ai.agents.interview_coach import interview_turn_events

        async def interview_events():
            try:
                async for event, payload in interview_turn_events(
                    db,
                    interview,
                    session=session,
                    user_id=user.id,
                    message=content,
                    history=history,
                    user_message_id=user_message_id,
                ):
                    yield _sse(event, payload)
            except DomainError as exc:
                yield _sse(
                    "flow_failed",
                    {"code": "ai_unavailable", "message": str(exc), "retryable": True},
                )
                yield _sse("error", {"detail": str(exc)})

        return StreamingResponse(
            interview_events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    cv = await _cv_builder_cv(session, db)
    if cv is not None:
        return await _builder_stream_response(
            cv, session, history, content, user_message_id, user, db
        )

    # On-demand builder handoff (plan 78 AD3): a CV attachment plus
    # build-intent wording runs the copilot loop for THIS turn only —
    # the session itself stays a normal chat session.
    from app.models.chat_model import ChatMessage

    turn_message = await db.get(ChatMessage, user_message_id)
    if turn_message is not None:
        from app.ai.agents.chatbot import is_build_intent
        from app.services.chat_attachments import attachment_cv, effective_attachments

        attachments = await effective_attachments(db, session, turn_message)
        if attachments and is_build_intent(content):
            target = await attachment_cv(db, user.id, attachments[0].get("cv_id"))
            if target is not None:
                return await _builder_stream_response(
                    target, session, history, content, user_message_id, user, db
                )

    # ---- Main surface: the chat-turn graph IS the engine (ADR-0016) ----
    from app.ai.checkpointer import get_checkpointer
    from app.ai.graphs.chat_turn import (
        END_SENTINEL,
        TurnDeps,
        build_chat_turn_graph,
        _note_node,
        is_cancellation,
    )

    if session.id in _ACTIVE_TURNS:
        raise DomainError("A reply is already streaming for this chat")
    _ACTIVE_TURNS.add(session.id)

    profile = await get_profile_for_user(db, user.id)
    # CV reference attachments (plan 78): explicit or inherited from the
    # conversation's most recent attached message (AD2b).
    from app.services.chat_attachments import build_turn_references

    cv_references = await build_turn_references(db, session, user_message_id)

    queue: asyncio.Queue = asyncio.Queue()
    deps = TurnDeps(
        db=db,
        session=session,
        user=user,
        user_message_id=user_message_id,
        content=content,
        history=history,
        profile_summary=await ProfileService(db).profile_summary(profile),
        page_context=session.context,
        cv_references=cv_references,
        emit=lambda event, payload: queue.put_nowait((event, payload)),
    )

    async def _drive():
        """Producer: run the graph; map failures onto the SSE contract."""
        try:
            checkpointer = await get_checkpointer()
            graph = build_chat_turn_graph(deps, checkpointer)
            await graph.ainvoke(
                {},
                config={
                    "configurable": {
                        "thread_id": f"chat:{session.id}:{user_message_id}"
                    }
                },
            )
        except DomainError as exc:
            deps.emit(
                "flow_failed",
                {"code": "ai_unavailable", "message": str(exc), "retryable": True},
            )
            deps.emit("error", {"detail": str(exc)})
        except Exception as exc:  # noqa: BLE001 — stream must end cleanly
            if is_cancellation(exc):
                # LangGraph wraps node CancelledError — a self-cancelling
                # stream is an ABORT (partial persists), not a failure.
                deps.aborted = True
            else:
                detail = f"AI error: {exc}"
                deps.emit(
                    "flow_failed",
                    {"code": "ai_error", "message": detail, "retryable": True},
                )
                deps.emit("error", {"detail": detail})
        finally:
            deps.emit(END_SENTINEL, {})

    async def events():
        """Consumer: drain the graph emitter into SSE (legacy contract)."""

        async def _persist_abort() -> None:
            # Client aborted (stop button) or the stream self-cancelled:
            # persist the partial prefix so the interrupted turn survives —
            # with the trace gathered so far, so the UI can still show
            # what ran.
            partial = (
                partial_answer_text("".join(deps.stream._raw))
                if deps.stream is not None and deps.stream.reply is None
                else ""
            )
            if not partial.strip():
                return
            now = time.monotonic()
            if deps.generating and deps.generate_started is not None:
                _note_node(
                    deps,
                    "ground",
                    "searching the catalog",
                    deps.turn_started,
                    deps.generate_started,
                )
                _note_node(
                    deps,
                    "generate",
                    "writing the reply",
                    deps.generate_started,
                    now,
                    status="interrupted",
                )
            else:
                _note_node(
                    deps,
                    "ground",
                    "searching the catalog",
                    deps.turn_started,
                    now,
                    status="interrupted",
                )
            try:
                await ChatService(db).complete_interrupted(
                    session,
                    user_message_id,
                    partial,
                    metadata={
                        "tools": deps.tool_metadata.get("tools", []),
                        "nodes": deps.nodes_trace,
                        "elapsed_ms": int((now - deps.turn_started) * 1000),
                        "model": deps.stream.model if deps.stream else None,
                    },
                )
            except Exception:  # noqa: BLE001 — best-effort persistence
                await db.rollback()

        try:
            driver = asyncio.create_task(_drive())
            try:
                while True:
                    event, payload = await queue.get()
                    if event == END_SENTINEL:
                        break
                    yield _sse(event, payload)
                # The driver finished normally — but a CancelledError that
                # bubbled out of the graph (self-cancelling stream) ends
                # the task as cancelled too: treat it as an abort.
                with suppress(asyncio.CancelledError):
                    await driver
                if driver.cancelled() or deps.aborted:
                    await _persist_abort()
                    raise asyncio.CancelledError
            except asyncio.CancelledError:
                # Consumer cancelled (client gone): cancel the run at the
                # node boundary, persist, then surface the abort.
                driver.cancel()
                with suppress(BaseException):
                    await driver
                await _persist_abort()
                raise
        finally:
            _ACTIVE_TURNS.discard(session.id)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _builder_stream_response(
    cv, session, history, content, user_message_id, user, db
):
    """Stream one builder copilot turn (legacy bound sessions AND the
    plan-78 on-demand handoff share this path)."""
    from app.ai.agents.cv_builder_chat import builder_turn_events

    async def builder_events():
        try:
            async for event, payload in builder_turn_events(
                db,
                cv,
                session=session,
                user_id=user.id,
                message=content,
                history=history,
                user_message_id=user_message_id,
            ):
                yield _sse(event, payload)
        except DomainError as exc:
            yield _sse(
                "flow_failed",
                {"code": "ai_unavailable", "message": str(exc), "retryable": True},
            )
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(
        builder_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _send_stream(session_id, data, user, db):
    attachments = await _resolve_attachments(db, user, data)
    try:
        session, history, message_id = await ChatService(db).begin_message(
            user.id, session_id, data.content, attachments
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _run_turn_stream(session, history, data.content, message_id, user, db)


@router.post("/chat/messages/{message_id}/edit")
async def edit_message(
    message_id: uuid.UUID,
    data: MessageIn,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Edit-and-resend: branch the user message as a new
    sibling, then stream a fresh reply for the edited prompt."""
    try:
        session, history, edited_id = await ChatService(db).edit_message(
            user.id,
            message_id,
            data.content,
            attachments=await _resolve_attachments(db, user, data),
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _run_turn_stream(session, history, data.content, edited_id, user, db)


@router.post("/chat/messages/{message_id}/regenerate")
async def regenerate_message(
    message_id: uuid.UUID,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Regenerate: stream a fresh assistant sibling under this user
    message; earlier replies stay switchable variants."""
    try:
        session, history, target_id, content = await ChatService(db).regenerate_message(
            user.id, message_id
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _run_turn_stream(session, history, content, target_id, user, db)


@router.post("/chat/messages/{message_id}/select", response_model=list[MessageOut])
async def select_message(
    message_id: uuid.UUID,
    user=Depends(get_current_user),
    db=Depends(get_db),
) -> list[MessageOut]:
    """Flip one branch pointer and return the re-walked visible path."""
    try:
        rows = await ChatService(db).select_message(user.id, message_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return [MessageOut.model_validate(m) for m in rows]


@router.get("/chat/sessions/{session_id}/tree", response_model=TreeOut)
async def get_tree(
    session_id: uuid.UUID,
    user=Depends(get_current_user),
    db=Depends(get_db),
) -> TreeOut:
    """Read-only branch-tree projection for the graph rail."""
    return TreeOut.model_validate(await ChatService(db).tree(user.id, session_id))


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
