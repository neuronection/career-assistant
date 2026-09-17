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
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import (
    RunRef,
    StructuredStream,
    ainvoke_agent,
    partial_answer_text,
)
from app.models.chat_model import ChatSession
from app.models.enums import AITaskType, ProposalKind
from app.models.user_model import User

MAX_PROFILE_OPS = 5

#: Tool-round budgets (plan 98 phase 3): LLM calls per turn stay ≤ 4
#: (rounds + synth) and executed tools per turn are capped — over-budget
#: calls are dropped with a persisted reason, never silently. Plan 99.1
#: raises the tool cap: read-before-edit adds one full-content read per
#: edited target on top of the digests (cheap DB point lookups).
MAX_AGENT_ROUNDS = 3
MAX_TOOL_CALLS_PER_TURN = 10

#: Digest tools whose model-pulled results persist into the plan-81
#: session cache (so later keyword-less turns stay grounded).
DIGEST_TOOLS = {"my_experience", "my_skills", "my_education", "my_profile_digest"}

#: Full-content read tools (plan 99.1): results ground the
#: read-before-edit gate for this turn AND persist into the session
#: cache (per-entity signature) for later turns.
READ_TOOLS = {"read_profile_item", "read_profile_section"}

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
    #: plan 98 phase 3 — tool rounds
    pending_calls: list[dict]
    tool_results_extra: dict
    rounds: int
    tools_executed: int
    degraded: bool
    #: plan 99.1 — full-content read keys grounding this turn's
    #: read-before-edit gate (``read:{kind}:{id-or-section}``).
    read_keys: list[str]
    #: plan 99.1 — accumulated read results (list-valued in the context).
    read_results: list[dict]


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
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)
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
    """Server-side grounding: registry tools, detections, digest cache.

    Digests are NOT pre-run (plan 98 phase 3): the model calls digest
    tools itself during agent rounds; ``ground_digests`` is the degrade
    fallback when the provider cannot call tools. The deterministic
    detections (catalog search, posting refs, notifications, postings,
    web prefetch) stay code-owned — the model never re-detects what
    code already knows.
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
        digest_mode="cached",
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
    deps.emit(
        "flow_started",
        {
            "flow": "chat",
            "steps": steps,
            "stage": "searching the catalog",
            "found": found,
        },
    )
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


async def agent_round(state: ChatTurnState, deps: TurnDeps) -> dict:
    """One native tool-round call (``gateway.ainvoke_agent``).

    Budgets: at most ``MAX_AGENT_ROUNDS`` LLM rounds per turn; a provider
    that cannot call tools degrades to the digest-stuffing fallback
    (today's behavior) instead of failing the turn.
    """
    from langchain_core.messages import HumanMessage

    from app.ai.agents.prompts import AGENT_ROUND
    from app.ai.agents.chatbot import ground_digests
    from app.ai.agents.context import context_json, parse_context
    from app.ai.tools.langchain import chat_tool_specs

    rounds = state.get("rounds", 0)
    if state.get("degraded") or rounds >= MAX_AGENT_ROUNDS:
        return {}
    specs = chat_tool_specs()
    if not specs:
        return {}
    try:
        message = await ainvoke_agent(
            deps.db,
            AITaskType.CHAT,
            system=AGENT_ROUND,
            messages=[HumanMessage(content=state["prompt"])],
            tools=specs,
            user_id=deps.user.id,
            run=RunRef(id=deps.run_id, stage=f"agent_round:{rounds}"),
        )
    except Exception as exc:  # noqa: BLE001 — degrade, never fail the turn
        if is_cancellation(exc):
            raise
        deps.degraded = True
        # Degrade fallback: stuff the digests the model can no longer
        # pull itself (edit grounding must survive without tool calls).
        ctx = parse_context(state["prompt"])
        tool_results = ctx.setdefault("tool_results", {})
        before = set(tool_results)
        old_metadata = dict(state.get("tool_metadata") or {})
        metadata_tools = list(old_metadata.get("tools", []))
        await ground_digests(
            deps.db,
            user_id=deps.user.id,
            message=deps.content,
            session=deps.session,
            tool_results=tool_results,
            metadata_tools=metadata_tools,
            prepare_started=deps.turn_started,
        )
        new_tools = metadata_tools[len(old_metadata.get("tools", [])) :]
        for offset, tool in enumerate(new_tools):
            deps.emit(
                "tool_call",
                {
                    "id": f"{tool.get('name', 'tool')}-fallback-{offset}",
                    "name": tool.get("name", "tool"),
                    "title": tool.get("title", tool.get("name", "tool")),
                    "status": tool.get("status", "done"),
                    "args": tool.get("args_summary", ""),
                    "result": tool.get("result_summary", ""),
                    "duration_ms": tool.get("duration_ms"),
                },
            )
        tool_metadata = dict(old_metadata)
        tool_metadata["tools"] = metadata_tools
        deps.tool_metadata = tool_metadata
        return {
            "degraded": True,
            "tool_results_extra": {
                k: v for k, v in tool_results.items() if k not in before
            },
            "tool_metadata": tool_metadata,
            "prompt": context_json(ctx),
        }
    calls = [
        {"name": call["name"], "args": call.get("args") or {}, "id": call["id"]}
        for call in (message.tool_calls or [])
    ]
    return {"pending_calls": calls}


async def execute_tools(state: ChatTurnState, deps: TurnDeps) -> dict:
    """Run the model's tool calls through ``run_tool`` (the single
    executor: audit/budget/requires_user unchanged) and emit the cards.
    Over-budget calls drop with a persisted reason."""
    from app.ai.agents.chatbot import TOOL_TITLES
    from app.ai.tools import run_tool

    calls = state.get("pending_calls") or []
    extra: dict = {}
    metadata_tools = list((state.get("tool_metadata") or {}).get("tools", []))
    dropped: list[dict] = []
    executed_total = state.get("tools_executed", 0)
    executed = 0
    read_keys = list(state.get("read_keys") or [])
    read_results = list(state.get("read_results") or [])
    for call in calls:
        if executed_total + executed >= MAX_TOOL_CALLS_PER_TURN:
            dropped.append(
                {
                    "name": call["name"],
                    "reason": "per-turn tool budget exhausted",
                }
            )
            continue
        started = time.monotonic()
        try:
            result = await run_tool(deps.db, call["name"], deps.user.id, call["args"])
        except Exception as exc:  # noqa: BLE001 — an observation, not a failure
            result = {"error": str(exc)}
        executed += 1
        if call["name"] not in READ_TOOLS:
            extra[call["name"]] = result
        duration_ms = int((time.monotonic() - started) * 1000)
        if call["name"] in DIGEST_TOOLS:
            # plan 81 continuity: a model-pulled digest persists into the
            # session cache so later turns without keywords stay grounded.
            from app.services import chat_digest_cache

            sigs = await chat_digest_cache.digest_signatures(
                deps.db, deps.user.id, [call["name"]]
            )
            sig = sigs.get(call["name"])
            if sig and deps.session is not None:
                chat_digest_cache.save(
                    deps.session,
                    {call["name"]: chat_digest_cache.fresh_entry(result, sig)},
                )
        elif call["name"] in READ_TOOLS:
            # plan 99.1: full-content reads ground this turn's
            # read-before-edit gate and persist per entity, so a later
            # turn editing the same (unchanged) item need not re-read.
            from app.services import chat_digest_cache

            read_results.append(result)
            if isinstance(result, dict) and result.get("error") is None:
                kind = result.get("kind")
                target = result.get("entity_id") or result.get("section")
                if kind and target:
                    read_keys.append(chat_digest_cache.read_cache_key(kind, target))
                    if deps.session is not None:
                        sig = await chat_digest_cache.entity_signature(
                            deps.db,
                            kind,
                            uuid.UUID(str(target)) if result.get("entity_id") else None,
                        )
                        if sig:
                            chat_digest_cache.save(
                                deps.session,
                                {
                                    chat_digest_cache.read_cache_key(
                                        kind, target
                                    ): chat_digest_cache.fresh_entry(result, sig)
                                },
                            )
        deps.emit(
            "tool_call",
            {
                "id": f"{call['name']}-{deps.run_id.hex[:6]}-{executed}",
                "name": call["name"],
                "title": TOOL_TITLES.get(call["name"], call["name"]),
                "status": "done",
                "args": "",
                "result": "",
                "duration_ms": duration_ms,
            },
        )
        metadata_tools.append(
            {
                "name": call["name"],
                "title": TOOL_TITLES.get(call["name"], call["name"]),
                "status": "done",
                "start_ms": int((started - deps.turn_started) * 1000),
                "args_summary": "",
                "duration_ms": duration_ms,
                "results": [call["name"].replace("my_", "")],
                "result_summary": call["name"].replace("my_", ""),
            }
        )
    tool_metadata = dict(state.get("tool_metadata") or {})
    tool_metadata["tools"] = metadata_tools
    if dropped:
        tool_metadata["tools_dropped"] = dropped
    deps.tool_metadata = tool_metadata
    # Observations re-enter the prompt immediately: the next round (and
    # the synth step) must see the results in the same context JSON.
    # Read results ACCUMULATE (list-valued): a second read must never
    # clobber the first's content in the model's context.
    prompt = state["prompt"]
    if extra or read_results:
        from app.ai.agents.context import context_json, parse_context

        ctx = parse_context(prompt)
        tool_results = ctx.setdefault("tool_results", {})
        tool_results.update(extra)
        if read_results:
            tool_results["read_profile_item"] = [
                row
                for row in read_results
                if row.get("kind") != ProposalKind.PROFILE_SECTION.value
            ]
            tool_results["read_profile_section"] = [
                row
                for row in read_results
                if row.get("kind") == ProposalKind.PROFILE_SECTION.value
            ]
        prompt = context_json(ctx)
    return {
        "tool_results_extra": {**state.get("tool_results_extra", {}), **extra},
        "rounds": state.get("rounds", 0) + 1,
        "pending_calls": [],
        "tools_executed": executed_total + executed,
        "read_keys": read_keys,
        "read_results": read_results,
        "tool_metadata": tool_metadata,
        "prompt": prompt,
    }


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
    from app.ai.agents.prompts import CHATBOT
    from app.ai.schemas import ChatReply

    stream = StructuredStream()
    deps.stream = stream
    sent = 0
    prompt = state["prompt"]
    async for _chunk in stream.chunks(
        deps.db, AITaskType.CHAT, ChatReply, CHATBOT, prompt, deps.user.id
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
        "prompt": prompt,
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
        from app.services import chat_digest_cache

        grounding = await chat_digest_cache.grounded_read_keys(
            deps.db, deps.session, state.get("read_keys") or []
        )
        created, dropped = await ProfileProposalService(deps.db).create_from_ops(
            deps.user.id,
            [op.model_dump() for op in ops[:MAX_PROFILE_OPS]],
            grounding=grounding,
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
    if state.get("rounds"):
        tool_metadata["tool_rounds"] = state["rounds"]
    if state.get("degraded"):
        tool_metadata["degraded"] = True
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
        ("agent_round", agent_round),
        ("execute_tools", execute_tools),
        ("synth", synth),
        ("hitl", hitl),
        ("finalize", finalize),
    ):
        node_name, node_fn = node(name, fn)
        builder.add_node(node_name, node_fn)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "agent_round")
    builder.add_conditional_edges(
        "agent_round",
        lambda state: ("execute_tools" if state.get("pending_calls") else "synth"),
        {"execute_tools": "execute_tools", "synth": "synth"},
    )
    builder.add_edge("execute_tools", "agent_round")
    builder.add_edge("synth", "hitl")
    builder.add_edge("hitl", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)
