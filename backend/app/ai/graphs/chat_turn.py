"""Main-chat turn as a checkpointed graph (ADR-0016, plan 98 Phase 2).

The SSE contract is unchanged — the endpoint owns it exactly as before;
this module owns the TURN: retrieve (server tools + digest cache) →
synth (structured streaming reply) → hitl (proposal cards + fanout) →
finalize (persistence + meta/flow events).

Streaming bridge: nodes emit ``(event, payload)`` pairs through the
deps emitter (an ``asyncio.Queue`` putter) while the graph runs in a
producer task; the endpoint drains the queue into SSE. Live objects
(db session, stream, reply, trace windows) live on ``TurnDeps`` —
NEVER in the state, which the checkpointer serializes.
``thread_id`` = ``chat:{session_id}:{message_id}`` per turn.

Phase 3 will insert ``agent_round ⇄ execute_tools`` between retrieve
and synth (native tool calls through ``gateway.ainvoke_agent``); the
deterministic detections and prompt-stuffed digests stay in ``retrieve``
until then — the graph shape does not change, only what feeds ``synth``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import StructuredStream, partial_answer_text
from app.models.chat_model import ChatSession
from app.models.enums import AITaskType
from app.models.user_model import User

MAX_PROFILE_OPS = 5

#: The producer-side end sentinel (never a real SSE event).
END_SENTINEL = "__end__"


class ChatTurnState(TypedDict, total=False):
    """JSON-safe turn state — the checkpointer serializes this."""

    prompt: str
    tool_metadata: dict
    reply: dict
    model: Optional[str]
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    proposals: list[dict]
    proposals_dropped: int
    dropped_reasons: list[dict]
    overflow: int


@dataclass
class TurnDeps:
    """Per-turn live wiring (never serialized into checkpoints)."""

    db: AsyncSession
    session: ChatSession
    user: User
    user_message_id: Any
    content: str
    history: list[dict]
    profile_summary: str
    page_context: Optional[dict]
    cv_references: Optional[list[dict]]
    emit: Callable[[str, dict], None]
    turn_started: float = field(default_factory=time.monotonic)
    stream: Optional[StructuredStream] = None
    nodes_trace: list[dict] = field(default_factory=list)
    created_proposals: list = field(default_factory=list)
    tool_metadata: dict = field(default_factory=dict)
    generating: bool = False
    generate_started: Optional[float] = None
    aborted: bool = False


def is_cancellation(exc: BaseException) -> bool:
    """True when the exception chain carries an asyncio.CancelledError.

    LangGraph wraps node-raised CancelledError ("Node 'synth' raised …"),
    so a self-cancelling stream must be detected through ``__cause__`` /
    ``__context__`` — the abort contract (partial persistence, no
    flow_failed) depends on telling it apart from a real failure.
    """
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, asyncio.CancelledError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _note_node(
    deps: TurnDeps,
    node_id: str,
    label: str,
    started: float,
    ended: float,
    status: str = "done",
) -> None:
    deps.nodes_trace.append(
        {
            "id": node_id,
            "label": label,
            "status": status,
            "start_ms": int((started - deps.turn_started) * 1000),
            "duration_ms": int((ended - started) * 1000),
        }
    )


async def retrieve(state: ChatTurnState, deps: TurnDeps) -> dict:
    """Server-side grounding: registry tools, digest cache, detections.

    Phase 2 keeps ``prepare_chat_prompt`` verbatim (it IS this node);
    the tool rounds move these into model-called tools in Phase 3.
    """
    from app.ai.agents.chatbot import prepare_chat_prompt

    prompt, tool_metadata = await prepare_chat_prompt(
        deps.db,
        profile_summary=deps.profile_summary,
        history=deps.history,
        message=deps.content,
        page_context=deps.page_context,
        user_id=deps.user.id,
        cv_references=deps.cv_references,
        session=deps.session,
    )
    if deps.cv_references:
        tool_metadata["referenced_cv_ids"] = [r["cv_id"] for r in deps.cv_references]
    deps.tool_metadata = tool_metadata

    tools = tool_metadata.get("tools", [])
    found = sum(len(tool.get("results") or []) for tool in tools)
    steps = [
        {"id": "ground", "label": "searching the catalog"},
        {"id": "generate", "label": "writing the reply"},
    ]
    deps.emit("status", {"stage": "searching the catalog", "found": found})
    # Family event vocabulary alongside the legacy names: additive only —
    # legacy `status` stays first, legacy `done` stays last, `delta` is
    # already the family name.
    deps.emit("flow_started", {"flow": "chat", "steps": steps})
    deps.emit("node_started", {"id": "ground", "label": steps[0]["label"]})
    # Turn trace: tools ran pre-LLM inside retrieve, so cards stream in
    # as completed.
    for index, tool in enumerate(tools):
        deps.emit(
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
    return {"prompt": prompt, "tool_metadata": tool_metadata}


def _open_generate(deps: TurnDeps) -> float:
    """The ground→generate transition (first delta or stream end)."""
    now = time.monotonic()
    deps.emit(
        "node_finished",
        {"id": "ground", "duration_ms": int((now - deps.turn_started) * 1000)},
    )
    _note_node(deps, "ground", "searching the catalog", deps.turn_started, now)
    deps.emit("node_started", {"id": "generate", "label": "writing the reply"})
    return now


async def synth(state: ChatTurnState, deps: TurnDeps) -> dict:
    """The structured streaming reply (one gateway call, unchanged)."""
    from app.ai.agents.chatbot import CHATBOT
    from app.ai.schemas import ChatReply

    stream = StructuredStream()
    deps.stream = stream
    sent = 0
    async for _chunk in stream.chunks(
        deps.db, AITaskType.CHAT, ChatReply, CHATBOT, state["prompt"], deps.user.id
    ):
        partial = partial_answer_text("".join(stream._raw))
        if len(partial) > sent:
            if not deps.generating:
                deps.generating = True
                deps.generate_started = _open_generate(deps)
            deps.emit("delta", {"text": partial[sent:]})
            sent = len(partial)
    if stream.reply is None:
        from app.core.errors import DomainError

        raise DomainError(stream.error or "AI produced no valid reply")
    if not deps.generating:
        deps.generate_started = _open_generate(deps)
    reply = stream.reply
    return {
        "reply": reply.model_dump(mode="json"),
        "model": stream.model,
        "tokens_in": stream.tokens_in,
        "tokens_out": stream.tokens_out,
    }


async def hitl(state: ChatTurnState, deps: TurnDeps) -> dict:
    """Profile ops → proposal cards (+ notification fanout). Nothing
    applies here; the user resolves each card."""
    from app.ai.schemas import ChatReply
    from app.services.profile_proposal_service import (
        ProfileProposalService,
        notify_proposals,
        proposal_event,
    )

    reply = ChatReply.model_validate(state["reply"])
    ops = reply.profile_ops or []
    created: list = []
    dropped: list = []
    overflow = max(0, len(ops) - MAX_PROFILE_OPS)
    if ops:
        created, dropped = await ProfileProposalService(deps.db).create_from_ops(
            deps.user.id,
            [op.model_dump() for op in ops[:MAX_PROFILE_OPS]],
            chat_session_id=deps.session.id,
        )
        if created:
            await notify_proposals(deps.db, deps.user.id, created, deps.session.id)
    deps.created_proposals = created
    generate_ended = time.monotonic()
    deps.emit(
        "node_finished",
        {
            "id": "generate",
            "duration_ms": int(
                (generate_ended - (deps.generate_started or deps.turn_started)) * 1000
            ),
        },
    )
    _note_node(
        deps,
        "generate",
        "writing the reply",
        deps.generate_started or deps.turn_started,
        generate_ended,
    )
    dropped_reasons = [
        {
            "kind": str(drop["op"].get("kind")),
            "reason": str(drop.get("reason", "")).removeprefix("Value error, ")[:200],
        }
        for drop in dropped[:5]
    ]
    return {
        "proposals": [proposal_event(p) for p in created],
        "proposals_dropped": len(dropped) + overflow,
        "dropped_reasons": dropped_reasons,
        "overflow": overflow,
    }


async def finalize(state: ChatTurnState, deps: TurnDeps) -> dict:
    """Persist the turn + terminal events (meta/proposals/flow/done)."""
    from app.ai.schemas import ChatReply
    from app.services.chat_service import ChatService

    reply = ChatReply.model_validate(state["reply"])
    tool_metadata = dict(state.get("tool_metadata") or {})
    total_ms = int((time.monotonic() - deps.turn_started) * 1000)
    tool_metadata["elapsed_ms"] = total_ms
    tool_metadata["nodes"] = deps.nodes_trace
    if state.get("model"):
        tool_metadata["model"] = state["model"]
    if state.get("tokens_in") is not None:
        tool_metadata["tokens_in"] = state["tokens_in"]
    if state.get("tokens_out") is not None:
        tool_metadata["tokens_out"] = state["tokens_out"]
    if deps.created_proposals:
        tool_metadata["proposals"] = list(state.get("proposals") or [])
    dropped = state.get("proposals_dropped") or 0
    if dropped:
        tool_metadata["proposals_dropped"] = dropped
        tool_metadata["proposals_dropped_reasons"] = state.get("dropped_reasons") or []
    message = await ChatService(deps.db).complete_message(
        deps.session, deps.user_message_id, reply, tool_metadata
    )
    if deps.created_proposals:
        for proposal in deps.created_proposals:
            proposal.chat_message_id = message.id
        await deps.db.commit()
    await ChatService(deps.db).autotitle_if_first_turn(
        deps.user.id, deps.session.id, deps.content
    )
    deps.emit(
        "meta",
        {
            "message_id": str(message.id),
            "referenced_job_codes": reply.referenced_job_codes,
            "referenced_posting_refs": tool_metadata.get("refs", []),
            "explore_query": tool_metadata.get("explore_query"),
            "proposals_dropped": dropped or None,
            "proposals_dropped_reasons": tool_metadata.get("proposals_dropped_reasons"),
        },
    )
    for payload in state.get("proposals") or []:
        deps.emit("proposal", payload)
    deps.emit(
        "flow_finished",
        {
            "flow": "chat",
            "model": state.get("model"),
            "total_ms": total_ms,
            "tool_count": len(tool_metadata.get("tools", [])),
            "proposal_count": len(deps.created_proposals),
        },
    )
    deps.emit("done", {"ok": True})
    return {"message_id": str(message.id)}


def build_chat_turn_graph(deps: TurnDeps, checkpointer: Any):
    """The main-chat turn graph, deps-injected (built per turn, study
    pattern). Node bodies close over ``deps``; the state stays
    JSON-safe for the checkpointer."""

    def node(name: str, fn):
        async def run(state: ChatTurnState) -> dict:
            return await fn(state, deps)

        run.__name__ = name
        return name, run

    builder = StateGraph(ChatTurnState)
    for name, fn in (
        ("retrieve", retrieve),
        ("synth", synth),
        ("hitl", hitl),
        ("finalize", finalize),
    ):
        node_name, node_fn = node(name, fn)
        builder.add_node(node_name, node_fn)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "synth")
    builder.add_edge("synth", "hitl")
    builder.add_edge("hitl", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)
