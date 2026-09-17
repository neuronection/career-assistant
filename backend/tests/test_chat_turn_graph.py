"""Chat-turn graph groundwork (plan 98 Phase 1, ADR-0016).

No graph ships in Phase 1 — these tests pin the groundwork the Phase-2
skeleton builds on: the InMemorySaver scaffolding, the registry→bind
spec adapter, the checkpointer retention beat and the gateway
agent-round funnel (native tool calls, audited, mock-scriptable).
"""

import sqlite3
import time
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from app.ai.gateway import ainvoke_agent, register_agent_mock
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType

from tests.test_ai_funnel import _assign_real_model, provider_module

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
    from app.ai.tools.langchain import chat_tool_specs, main_chat_tool_keys

    keys = main_chat_tool_keys()
    assert "my_experience" in keys
    assert "compare_jobs" in keys
    assert "my_notifications" in keys
    assert not any(key.startswith(("cv_", "web_")) for key in keys), (
        "surface-owned families stay unbound in main chat"
    )
    assert "propose_profile_edits" not in keys, "capabilities never bind"

    specs = chat_tool_specs()
    by_name = {spec["function"]["name"]: spec for spec in specs}
    assert set(by_name) == set(keys)
    spec = by_name["my_experience"]
    assert spec["type"] == "function"
    assert spec["function"]["parameters"]["type"] == "object"
    assert "limit" in spec["function"]["parameters"]["properties"]

    only_callable = chat_tool_specs(["search_jobs", "propose_profile_edits", "ghost"])
    assert [s["function"]["name"] for s in only_callable] == ["search_jobs"], (
        "unknown keys and capabilities drop silently"
    )


def _checkpoint_id(ms_ago: int) -> str:
    """A UUIDv6-shaped id whose first 12 hex chars are the 48-bit
    100 ns timestamp prefix (the same math the prune compares)."""
    ticks = int((time.time() - ms_ago / 1000) * 1000) * 10_000 + _GREGORIAN_100NS
    return f"{ticks >> 12:012x}" + "0" * 20


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
