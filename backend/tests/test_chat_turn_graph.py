"""Chat-turn graph groundwork (plan 98 Phase 1, ADR-0016).

No graph ships in Phase 1 — these tests pin the groundwork the Phase-2
skeleton builds on: the InMemorySaver scaffolding, the registry→bind
spec adapter, the checkpointer retention beat and the gateway
agent-round funnel (native tool calls, audited, mock-scriptable).
"""

import json
import sqlite3
from contextlib import suppress
import time
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from app.ai.gateway import ainvoke_agent, register_agent_mock
from app.ai.mock_chat import mock_chat_reply
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType

from tests.test_ai_funnel import _assign_real_model, provider_module
from app.models.chat_model import ChatMessage
from app.services.experience_service import ExperienceService
from tests.test_chat_profile_ops import _auth_user

_GREGORIAN_100NS = 122192928000000000


def test_in_memory_saver_checkpoints_a_trivial_graph():
    """The Phase-2 test scaffold: a StateGraph + InMemorySaver round-trip."""
    from typing import TypedDict

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    class State(TypedDict, total=False):
        value: str

    graph = StateGraph(State)
    graph.add_node("step", lambda state: {"value": state["value"].upper()})
    graph.add_edge(START, "step")
    graph.add_edge("step", END)
    compiled = graph.compile(checkpointer=InMemorySaver())

    result = compiled.invoke(
        {"value": "chat"}, config={"configurable": {"thread_id": "t-run-1"}}
    )
    assert result["value"] == "CHAT"
    history = list(
        compiled.get_state_history({"configurable": {"thread_id": "t-run-1"}})
    )
    assert history, "checkpoint thread recorded"


def test_main_chat_tool_keys_exclude_owned_families_and_capabilities():
    from app.ai.tools.langchain import (
        MAIN_CHAT_CV_TOOLS,
        chat_tool_specs,
        main_chat_tool_keys,
    )

    keys = main_chat_tool_keys()
    assert "my_experience" in keys
    assert "compare_jobs" in keys
    assert "my_notifications" in keys
    assert not any(key.startswith("web_") for key in keys), (
        "surface-owned web family stays unbound in main chat"
    )
    assert {
        "cv_read_state",
        "cv_review_visual",
        "cv_set_template",
        "cv_apply_theme",
        "cv_update_design",
        "cv_set_context",
    } <= set(keys), "the CV allowlist binds in main chat"
    assert not any(
        key.startswith("cv_") and key not in MAIN_CHAT_CV_TOOLS for key in keys
    ), "non-allowlisted cv_* stay unbound (content editors stay builder-side)"
    assert "propose_profile_edits" not in keys, "capabilities never bind"

    specs = chat_tool_specs()
    by_name = {spec["function"]["name"]: spec for spec in specs}
    assert set(by_name) == set(keys)
    spec = by_name["my_experience"]
    assert spec["type"] == "function"
    assert spec["function"]["parameters"]["type"] == "object"
    assert "limit" in spec["function"]["parameters"]["properties"]
    styling = by_name["cv_update_design"]
    assert styling["function"]["description"].startswith("Patch design tokens")

    only_callable = chat_tool_specs(["search_jobs", "propose_profile_edits", "ghost"])
    assert [s["function"]["name"] for s in only_callable] == ["search_jobs"], (
        "unknown keys and capabilities drop silently"
    )


def _checkpoint_id(ms_ago: int) -> str:
    """A UUIDv6-shaped id whose first 12 hex chars are the 48-bit
    100 ns timestamp prefix (the same math the prune compares)."""
    ticks = int((time.time() - ms_ago / 1000) * 1000) * 10_000 + _GREGORIAN_100NS
    return f"{ticks >> 12:012x}" + "0" * 20


def test_salvage_streamed_chat_reply_keeps_a_streamed_answer():
    """A structurally-broken reply stream no longer kills the turn: the
    answer bytes the UI already rendered are kept as the reply."""
    from app.ai.graphs.chat_turn import salvage_streamed_chat_reply

    streamed = (
        '{"answer": "The navy sidebar reads dated; slate is better",'
        '"referenced_job_codes": ['  # truncated tail
    )
    salvaged = salvage_streamed_chat_reply(streamed)
    assert salvaged is not None
    assert salvaged["answer"] == "The navy sidebar reads dated; slate is better"
    assert salvaged["profile_ops"] == []
    assert salvage_streamed_chat_reply("") is None
    assert salvage_streamed_chat_reply('{"referenced_job_codes": [1]}') is None


def test_extract_json_repairs_a_truncated_object():
    """Flash models hitting a cutoff leak a truncated JSON object; the
    largest brace-closed prefix still carries the answer field."""
    from app.ai.gateway import _extract_json

    truncated = (
        '{"answer": "modern slate looks professional",\n'
        '  "profile_ops": [],\n  "referenced_job_codes": ["S1A2B3C4"'
    )
    out = _extract_json(truncated)
    assert out["answer"] == "modern slate looks professional"
    # A prose-wrapped but complete object still parses.
    wrapped = 'Sure! {"answer": "hi"} Hope that helps.'
    assert _extract_json(wrapped)["answer"] == "hi"
    # A fenced object parses.
    fenced = '```json\n{"answer": "fenced"}\n```'
    assert _extract_json(fenced)["answer"] == "fenced"


def test_prune_checkpoints_removes_stale_threads(tmp_path: Path):
    from app.ai.checkpointer import prune_checkpoints

    db = tmp_path / "checkpoints.db"
    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "create table checkpoints ("
            "thread_id text, checkpoint_ns text, checkpoint_id text)"
        )
        connection.execute(
            "create table writes ("
            "thread_id text, checkpoint_ns text, checkpoint_id text, data text)"
        )
        for thread, cid in (
            ("fresh", _checkpoint_id(1000)),
            ("stale", _checkpoint_id(30 * 86_400_000)),
        ):
            connection.execute(
                "insert into checkpoints values (?, '0', ?)", (thread, cid)
            )
            connection.execute(
                "insert into writes values (?, '0', ?, 'x')", (thread, cid)
            )
        connection.commit()
    finally:
        connection.close()

    assert prune_checkpoints(db, ttl_days=14) == 1
    connection = sqlite3.connect(db)
    try:
        rows = connection.execute("select thread_id from checkpoints").fetchall()
        writes_left = connection.execute("select count(*) from writes").fetchone()[0]
    finally:
        connection.close()
    assert rows == [("fresh",)]
    assert writes_left == 1, "writes of removed checkpoints drop with them"
    assert prune_checkpoints(tmp_path / "missing.db", ttl_days=14) == 0


class _FakeAgentModel:
    """Bound-tools stand-in: records the bind, returns scripted calls."""

    def __init__(self, reply: AIMessage):
        self.reply = reply
        self.bound: list | None = None

    def bind_tools(self, tools):
        self.bound = tools
        return self

    async def ainvoke(self, messages):
        return self.reply


async def test_ainvoke_agent_audits_tool_calls(db, monkeypatch):
    user = await _assign_real_model(db)
    reply = AIMessage(
        content="",
        tool_calls=[{"name": "my_experience", "args": {"limit": 5}, "id": "call-1"}],
    )
    fake = _FakeAgentModel(reply)
    monkeypatch.setattr(
        provider_module, "build_chat_model", lambda resolved, **kw: fake
    )

    result = await ainvoke_agent(
        db,
        AITaskType.ASSIST,
        system="sys",
        messages=[HumanMessage(content="edit my experience")],
        tools=[{"type": "function", "function": {"name": "my_experience"}}],
        user_id=user.id,
    )
    assert result.tool_calls[0]["name"] == "my_experience"
    assert fake.bound is not None, "tools were bound on the model"

    rows = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == "assist")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "ok"
    assert rows[0].output["tool_calls"] == [
        {"name": "my_experience", "args": {"limit": 5}}
    ]


async def _assign_mock_model(db):
    from app.core.security import hash_password
    from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
    from app.models.user_model import User

    user = User(email="agent-mock@example.com", password_hash=hash_password("pw123456"))
    db.add(user)
    await db.flush()
    prov = AIProvider(
        name="mock-prov",
        scope="user",
        user_id=user.id,
        provider_type="mock",
    )
    db.add(prov)
    await db.flush()
    model = AIModel(provider_id=prov.id, name="mock", model_name="mock-model")
    db.add(model)
    await db.flush()
    db.add(
        AITaskAssignment(
            task_type=AITaskType.CHAT.value,
            scope="user",
            user_id=user.id,
            provider_id=prov.id,
            model_id=model.id,
        )
    )
    await db.commit()
    return user


async def test_ainvoke_agent_mock_is_scriptable(db):
    user = await _assign_mock_model(db)
    tools = [{"type": "function", "function": {"name": "search_jobs"}}]

    result = await ainvoke_agent(
        db,
        AITaskType.CHAT,
        system="sys",
        messages=[HumanMessage(content="hello")],
        tools=tools,
        user_id=user.id,
    )
    assert result.tool_calls == [], "default mock proceeds to synth (legacy parity)"
    assert result.content == ""

    register_agent_mock(
        "chat",
        lambda user_text, tool_names: {
            "content": "",
            "tool_calls": [{"name": tool_names[0], "args": {}, "id": "c1"}],
        },
    )
    try:
        scripted = await ainvoke_agent(
            db,
            AITaskType.CHAT,
            system="sys",
            messages=[HumanMessage(content="hello")],
            tools=tools,
            user_id=user.id,
        )
        assert scripted.tool_calls[0]["name"] == "search_jobs"
    finally:
        from app.ai import gateway as gateway_module

        gateway_module.AGENT_MOCK_SCRIPTS.pop("chat", None)


# ------------------------------------------------ plan 98 phase 3: rounds


async def _send_turn(client, auth_headers, content: str):
    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "rounds"}, headers=auth_headers
        )
    ).json()
    response = await client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        json={"content": content},
        params={"stream": "true"},
        headers=auth_headers,
    )
    events = []
    for block in response.text.split("\n\n"):
        if not block.strip():
            continue
        name = data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        events.append((name, json.loads(data)))
    return session, events


async def test_agent_rounds_ground_edit_via_digest_tool(
    client, db, auth_headers, monkeypatch
):
    """Edit-verb turn: the agent mock calls my_experience; the proposal
    grounds on the tool result (never an invented id)."""
    from app.ai import gateway as gateway_module
    from app.models.enums import AITaskType

    gateway_module.register_mock_fixture(AITaskType.CHAT, mock_chat_reply)
    user = await _auth_user(db)
    item = await ExperienceService(db).create_item(
        user.id, {"title": "Crew bot", "kind": "project", "open_ended": True}
    )
    await db.commit()
    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "ground"}, headers=auth_headers
        )
    ).json()
    response = await client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        json={"content": f"delete the project: {item.title}"},
        params={"stream": "true"},
        headers=auth_headers,
    )
    events = []
    for block in response.text.split("\n\n"):
        name = data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if name:
            events.append((name, json.loads(data)))
    cards = [p for n, p in events if n == "proposal"]
    assert cards, events
    assert cards[0]["entity_id"] == str(item.id)


async def test_agent_round_budget_caps_executed_tools(
    client, db, auth_headers, monkeypatch
):
    """More tool calls than the per-turn budget → extras drop with a
    persisted reason and the turn still completes."""
    from app.ai import gateway as gateway_module
    from app.ai.graphs import chat_turn as ct

    def greedy(user_text, tool_names):
        return {
            "content": "",
            "tool_calls": [
                {"name": "search_jobs", "args": {"query": f"q{i}"}, "id": f"c{i}"}
                for i in range(10)
            ],
        }

    gateway_module.register_agent_mock(AITaskType.CHAT.value, greedy)
    try:
        session, events = await _send_turn(client, auth_headers, "hello there")
    finally:
        gateway_module.AGENT_MOCK_SCRIPTS.pop(AITaskType.CHAT.value, None)
    names = [n for n, _ in events]
    assert names[-1] == "flow_finished", "the turn survives the greedy agent"

    rows = (
        (
            await db.execute(
                select(ChatMessage).where(ChatMessage.session_id == session["id"])
            )
        )
        .scalars()
        .all()
    )
    assistant = next(r for r in rows if r.role == "assistant")
    # The per-turn budget caps AGENT-executed tools; retrieve's own
    # deterministic cards (search_jobs) ride the same trace.
    assert (
        len(assistant.metadata_json.get("tools", [])) <= 1 + ct.MAX_TOOL_CALLS_PER_TURN
    )
    assert assistant.metadata_json.get("tools_dropped"), (
        "over-budget calls drop with a persisted reason"
    )


async def test_agent_rounds_stop_at_round_cap(client, db, auth_headers):
    """A script that always calls tools cannot loop forever — the round
    cap ends the loop and the turn completes."""
    from app.ai import gateway as gateway_module

    def looper(user_text, tool_names):
        return {
            "content": "",
            "tool_calls": [{"name": "search_jobs", "args": {"query": "x"}, "id": "c"}],
        }

    gateway_module.register_agent_mock(AITaskType.CHAT.value, looper)
    try:
        session, events = await _send_turn(client, auth_headers, "hello there")
    finally:
        gateway_module.AGENT_MOCK_SCRIPTS.pop(AITaskType.CHAT.value, None)
    names = [n for n, _ in events]
    assert names[-1] == "flow_finished"
    tool_events = [p for n, p in events if n == "tool_call"]
    assert len(tool_events) <= ct_guard()


def ct_guard():
    from app.ai.graphs import chat_turn as ct

    return ct.MAX_AGENT_ROUNDS * ct.MAX_TOOL_CALLS_PER_TURN


async def test_agent_degrades_to_digest_stuffing(client, db, auth_headers, monkeypatch):
    """A provider that cannot call tools degrades: digests are stuffed by
    the fallback, and the plan-99 gate DROPS the ungrounded edit op —
    a degraded turn never overwrites content the model has not seen
    (deliberate safety regression, plan 99 §11.9). The turn still
    completes and the drop is visible in the meta note."""
    import json as _json

    from app.ai import gateway as gateway_module
    from app.ai.graphs import chat_turn as ct
    from app.models.enums import AITaskType

    async def broken_agent(*args, **kwargs):
        raise gateway_module.StructuredAIError("provider rejected tools")

    def ungrounded_delete(schema, user_prompt):
        ctx = _json.loads(user_prompt.split("CONTEXT_JSON: ", 1)[1])
        items = (ctx["tool_results"].get("my_experience") or {}).get("items") or []
        if not items:
            return {"answer": "plain"}
        return {
            "answer": "proposing without a read",
            "profile_ops": [
                {
                    "kind": "experience_item",
                    "action": "delete",
                    "entity_id": items[0]["id"],
                }
            ],
        }

    monkeypatch.setattr(ct, "ainvoke_agent", broken_agent)
    gateway_module.register_mock_fixture(AITaskType.CHAT, ungrounded_delete)
    try:
        user = await _auth_user(db)
        item = await ExperienceService(db).create_item(
            user.id, {"title": "Old bot", "kind": "project", "open_ended": True}
        )
        await db.commit()
        session = (
            await client.post(
                "/api/v1/chat/sessions", json={"title": "degrade"}, headers=auth_headers
            )
        ).json()
        response = await client.post(
            f"/api/v1/chat/sessions/{session['id']}/messages",
            json={"content": f"delete the project: {item.title}"},
            params={"stream": "true"},
            headers=auth_headers,
        )
    finally:
        gateway_module.register_mock_fixture(AITaskType.CHAT, mock_chat_reply)
    events = []
    for block in response.text.split("\n\n"):
        name = data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if name:
            events.append((name, json.loads(data)))
    assert not [p for n, p in events if n == "proposal"], (
        "degraded turns never emit ungrounded edit cards"
    )
    names = [n for n, _ in events]
    assert names[-1] == "flow_finished", "the turn survives the degraded provider"
    meta = next(p for n, p in events if n == "meta")
    dropped_reasons = json.dumps(meta.get("proposals_dropped_reasons") or [])
    assert "unread_target" in dropped_reasons


# ------------------------------------------------- dual-mode (desktop)


async def test_checkpointer_picks_sqlite_for_desktop(monkeypatch, tmp_path):
    """Desktop profile (sqlite DATABASE_URL): the saver is AsyncSqliteSaver
    on a sibling checkpoints.db — the chat-turn graph never needs a
    Postgres server, and checkpoint round-trips work on SQLite."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.ai import checkpointer as cp
    from app.core.config import settings

    monkeypatch.setattr(
        settings,
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'career-assistant.db'}",
    )
    monkeypatch.setattr(cp, "_stack", None)
    monkeypatch.setattr(cp, "_checkpointer", None)
    saver = await cp.get_checkpointer()
    assert isinstance(saver, AsyncSqliteSaver)

    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class State(TypedDict, total=False):
        value: str

    graph = StateGraph(State)
    graph.add_node("step", lambda state: {"value": state["value"] + "!"})
    graph.add_edge(START, "step")
    graph.add_edge("step", END)
    compiled = graph.compile(checkpointer=saver)
    result = await compiled.ainvoke(
        {"value": "desktop"}, config={"configurable": {"thread_id": "t-desk"}}
    )
    assert result["value"] == "desktop!"
    history = [
        snap
        async for snap in compiled.aget_state_history(
            {"configurable": {"thread_id": "t-desk"}}
        )
    ]
    assert history, "checkpointed on the desktop sqlite saver"
    await cp.aclose_checkpointer()
    assert (tmp_path / "checkpoints.db").exists(), "sibling checkpoint file"


# ------------------------------------------ plan 98 phase 4: retention/cancel


async def test_postgres_prune_removes_stale_threads(db):
    """The server retention beat: stale checkpoint threads (and their
    orphaned blobs/writes) drop; fresh threads survive."""
    import pytest as _pytest

    from app.core.config import settings

    if not settings.DATABASE_URL.startswith("postgresql"):
        _pytest.skip(
            "Postgres retention beat — the langgraph tables are "
            "created by the server's saver setup, not migrations"
        )
    from sqlalchemy import text

    from app.ai.checkpointer import prune_postgres_checkpoints

    stale_id = _checkpoint_id(30 * 86_400_000)
    fresh_id = _checkpoint_id(1000)

    def _insert(thread: str, cid: str):
        return text(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, "
            "parent_checkpoint_id, checkpoint, metadata) "
            "VALUES (:t, '', :c, NULL, '{}', '{}')"
        ).bindparams(t=thread, c=cid)

    await db.execute(_insert("stale-thread", stale_id))
    await db.execute(_insert("fresh-thread", fresh_id))
    await db.execute(
        text(
            "INSERT INTO checkpoint_blobs (thread_id, checkpoint_ns, channel, "
            "version, type, blob) VALUES ('stale-thread', '', 'ch', 'v1', 'json', NULL)"
        )
    )
    await db.execute(
        text(
            "INSERT INTO checkpoint_writes (thread_id, checkpoint_ns, "
            "checkpoint_id, task_id, idx, channel, type, blob) "
            "VALUES ('stale-thread', '', :c, 'task', 0, 'ch', 'json', '\\x7b7d')"
        ).bindparams(c=stale_id)
    )
    await db.commit()

    removed = await prune_postgres_checkpoints(db, ttl_days=14)
    await db.commit()
    assert removed >= 1

    threads = {
        row[0]
        for row in (
            await db.execute(text("SELECT thread_id FROM checkpoints"))
        ).fetchall()
    }
    assert "stale-thread" not in threads
    assert "fresh-thread" in threads
    leftovers = (
        await db.execute(
            text(
                "SELECT count(*) FROM checkpoint_blobs WHERE thread_id = 'stale-thread'"
            )
        )
    ).scalar()
    assert leftovers == 0
    # Idempotent: a second run removes nothing.
    assert await prune_postgres_checkpoints(db, ttl_days=14) == 0


async def test_cancel_at_node_boundary_leaves_resumable_thread():
    """Exit gate: an aborted run pauses at the node boundary — the last
    completed node's checkpoint survives, the pending node is resumable
    (dormant: nothing auto-resumes it)."""
    import asyncio
    from typing import TypedDict

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    class State(TypedDict, total=False):
        steps: list

    async def step1(state: State) -> dict:
        return {"steps": ["one"]}

    async def step2(state: State) -> dict:
        await asyncio.sleep(30)
        return {"steps": ["two"]}

    graph = StateGraph(State)
    graph.add_node("step1", step1)
    graph.add_node("step2", step2)
    graph.add_edge(START, "step1")
    graph.add_edge("step1", "step2")
    graph.add_edge("step2", END)
    compiled = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t-cancel"}}

    task = asyncio.create_task(compiled.ainvoke({"steps": []}, config=config))
    await asyncio.sleep(0.2)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    state = await compiled.aget_state(config)
    assert state.values.get("steps") == ["one"], "step1's checkpoint survives"
    assert state.next == ("step2",), "step2 is resumable-dormant"
