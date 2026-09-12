import asyncio
import json
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import quick_assist
from app.ai.agents.chatbot import CHATBOT, prepare_chat_prompt
from app.ai.gateway import StructuredStream, partial_answer_text
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
    SessionUpdate,
    TreeOut,
)
from app.services.chat_service import ChatService
from app.services.profile_service import ProfileService
from app.services.deps import get_current_user, get_profile_for_user

router = APIRouter(tags=["chat"])


def _session_out(session, last_activity: datetime) -> SessionOut:
    return SessionOut(
        id=session.id,
        title=session.title,
        context=session.context,
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

    turn_started = time.monotonic()
    profile = await get_profile_for_user(db, user.id)
    prompt, tool_metadata = await prepare_chat_prompt(
        db,
        profile_summary=await ProfileService(db).profile_summary(profile),
        history=history,
        message=content,
        page_context=session.context,
        user_id=user.id,
    )

    stream = StructuredStream()

    async def events():
        tools = tool_metadata.get("tools", [])
        nodes_trace: list[dict] = []

        def _note_node(
            node_id: str,
            label: str,
            started: float,
            ended: float,
            status: str = "done",
        ) -> None:
            """Record one graph-node window for the persisted trace."""
            nodes_trace.append(
                {
                    "id": node_id,
                    "label": label,
                    "status": status,
                    "start_ms": int((started - turn_started) * 1000),
                    "duration_ms": int((ended - started) * 1000),
                }
            )

        found = sum(len(tool.get("results") or []) for tool in tools)
        steps = [
            {"id": "ground", "label": "searching the catalog"},
            {"id": "generate", "label": "writing the reply"},
        ]
        yield _sse(
            "status",
            {"stage": "searching the catalog", "found": found},
        )
        # Family event vocabulary alongside the legacy
        # names: additive only — legacy `status` stays first, legacy
        # `done` stays last, `delta` is already the family name.
        yield _sse("flow_started", {"flow": "chat", "steps": steps})
        yield _sse("node_started", {"id": "ground", "label": steps[0]["label"]})
        # Turn trace: tools ran pre-LLM inside
        # `prepare_chat_prompt`, so cards stream in as completed.
        for index, tool in enumerate(tools):
            yield _sse(
                "tool_call",
                {
                    "id": f"{tool.get('name', 'tool')}-{index}",
                    "name": tool.get("name", "tool"),
                    "title": tool.get("title", tool.get("name", "tool")),
                    "status": "done",
                    "args": tool.get("args_summary", ""),
                    "result": tool.get("result_summary", ""),
                    "duration_ms": tool.get("duration_ms"),
                },
            )
        sent = 0
        generating = False
        generate_started: float | None = None
        try:
            async for chunk in stream.chunks(
                db, AITaskType.CHAT, ChatReply, CHATBOT, prompt, user.id
            ):
                partial = partial_answer_text("".join(stream._raw))
                if len(partial) > sent:
                    if not generating:
                        generating = True
                        generate_started = time.monotonic()
                        yield _sse(
                            "node_finished",
                            {
                                "id": "ground",
                                "duration_ms": int(
                                    (generate_started - turn_started) * 1000
                                ),
                            },
                        )
                        _note_node(
                            "ground",
                            steps[0]["label"],
                            turn_started,
                            generate_started,
                        )
                        yield _sse(
                            "node_started",
                            {"id": "generate", "label": steps[1]["label"]},
                        )
                    yield _sse("delta", {"text": partial[sent:]})
                    sent = len(partial)
            if stream.reply is None:
                raise DomainError(stream.error or "AI produced no valid reply")
            if not generating:
                generate_started = time.monotonic()
                yield _sse(
                    "node_finished",
                    {
                        "id": "ground",
                        "duration_ms": int((generate_started - turn_started) * 1000),
                    },
                )
                _note_node("ground", steps[0]["label"], turn_started, generate_started)
                yield _sse(
                    "node_started", {"id": "generate", "label": steps[1]["label"]}
                )
            generate_ended = time.monotonic()
            yield _sse(
                "node_finished",
                {
                    "id": "generate",
                    "duration_ms": int(
                        (generate_ended - (generate_started or turn_started)) * 1000
                    ),
                },
            )
            _note_node(
                "generate",
                steps[1]["label"],
                generate_started or turn_started,
                generate_ended,
            )
            total_ms = int((time.monotonic() - turn_started) * 1000)
            tool_metadata["elapsed_ms"] = total_ms
            tool_metadata["nodes"] = nodes_trace
            if stream.model:
                tool_metadata["model"] = stream.model
            if stream.tokens_in is not None:
                tool_metadata["tokens_in"] = stream.tokens_in
            if stream.tokens_out is not None:
                tool_metadata["tokens_out"] = stream.tokens_out
            message = await ChatService(db).complete_message(
                session, user_message_id, stream.reply, tool_metadata
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
            yield _sse(
                "flow_finished",
                {
                    "flow": "chat",
                    "model": stream.model,
                    "total_ms": total_ms,
                    "tool_count": len(tools),
                },
            )
            yield _sse("done", {"ok": True})
        except asyncio.CancelledError:
            # Client aborted (stop button): persist the partial prefix so
            # the interrupted turn survives — with the trace
            # gathered so far, so the UI can still show what ran.
            partial = partial_answer_text("".join(stream._raw))
            if stream.reply is None and partial.strip():
                now = time.monotonic()
                if generating and generate_started is not None:
                    _note_node(
                        "ground", steps[0]["label"], turn_started, generate_started
                    )
                    _note_node(
                        "generate",
                        steps[1]["label"],
                        generate_started,
                        now,
                        status="interrupted",
                    )
                else:
                    _note_node(
                        "ground",
                        steps[0]["label"],
                        turn_started,
                        now,
                        status="interrupted",
                    )
                try:
                    await ChatService(db).complete_interrupted(
                        session,
                        user_message_id,
                        partial,
                        metadata={
                            "tools": tool_metadata.get("tools", []),
                            "nodes": nodes_trace,
                            "elapsed_ms": int((now - turn_started) * 1000),
                            "model": stream.model,
                        },
                    )
                except Exception:  # noqa: BLE001 — best-effort persistence
                    await db.rollback()
            raise
        except DomainError as exc:
            yield _sse(
                "flow_failed",
                {"code": "ai_unavailable", "message": str(exc), "retryable": True},
            )
            yield _sse("error", {"detail": str(exc)})
        except Exception as exc:  # noqa: BLE001 — stream must end cleanly
            detail = f"AI error: {exc}"
            yield _sse(
                "flow_failed",
                {"code": "ai_error", "message": detail, "retryable": True},
            )
            yield _sse("error", {"detail": detail})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _send_stream(session_id, data, user, db):
    try:
        session, history, message_id = await ChatService(db).begin_message(
            user.id, session_id, data.content
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _run_turn_stream(session, history, data.content, message_id, user, db)


@router.post("/chat/messages/{message_id}/edit")
async def edit_message(
    message_id: uuid.UUID,
    data: MessageIn,
    stream: bool = Query(default=False),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Edit-and-resend: branch the user message as a new
    sibling, then stream a fresh reply for the edited prompt."""
    try:
        session, history, edited_id = await ChatService(db).edit_message(
            user.id, message_id, data.content
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if not stream:
        profile = await get_profile_for_user(db, user.id)
        await ChatService(db).finish_turn(
            session, history, edited_id, data.content, profile
        )
        rows = await ChatService(db).messages(user.id, session.id)
        return [MessageOut.model_validate(m) for m in rows[-2:]]
    return await _run_turn_stream(session, history, data.content, edited_id, user, db)


@router.post("/chat/messages/{message_id}/regenerate")
async def regenerate_message(
    message_id: uuid.UUID,
    stream: bool = Query(default=False),
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
    if not stream:
        profile = await get_profile_for_user(db, user.id)
        await ChatService(db).finish_turn(session, history, target_id, content, profile)
        rows = await ChatService(db).messages(user.id, session.id)
        return [MessageOut.model_validate(m) for m in rows[-2:]]
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
