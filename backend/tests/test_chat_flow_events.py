"""Chat SSE stream: family event vocabulary alongside legacy names.

additive only: legacy `status` stays first, legacy `done`
stays last, `delta` is already the family name. The byte-identical parity
tripwire in test_chat_streaming.py still guards the legacy contract.
"""

import json

from app.models.ai_model import AIGeneration
from sqlalchemy import select


async def _post_message(client, session_id, headers, **params):
    return await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "data science careers"},
        params=params or None,
        headers=headers,
    )


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        events.append((name, json.loads(data)))
    return events


async def test_stream_emits_family_vocabulary_alongside_legacy(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "flow"}, headers=auth_headers
        )
    ).json()

    response = await _post_message(client, session["id"], auth_headers, stream="true")
    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [name for name, _ in events]

    # Legacy contract intact (parity with test_chat_streaming).
    assert names[0] == "status"
    assert names[-1] == "done"
    assert "delta" in names

    # Family vocabulary present and well-ordered.
    assert "flow_started" in names
    assert "node_started" in names
    assert "node_finished" in names
    assert "flow_finished" in names
    assert names.index("flow_finished") < names.index("done")
    assert names.index("status") < names.index("flow_started")

    flow = next(p for n, p in events if n == "flow_started")
    assert flow["flow"] == "chat"
    assert [s["id"] for s in flow["steps"]] == ["ground", "generate"]

    started = [p["id"] for n, p in events if n == "node_started"]
    finished = [p["id"] for n, p in events if n == "node_finished"]
    assert started == ["ground", "generate"]
    assert finished == ["ground", "generate"]


async def test_stream_emits_flow_failed_on_error(
    client, db, auth_headers, profile_ready, seeded_catalog, monkeypatch
):
    from app.ai.gateway import StructuredAIError, StructuredStream

    async def broken_chunks(*args, **kwargs):
        raise StructuredAIError("no valid output")
        yield ""  # pragma: no cover — makes it an async generator

    monkeypatch.setattr(StructuredStream, "chunks", broken_chunks)
    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "err"}, headers=auth_headers
        )
    ).json()
    response = await _post_message(client, session["id"], auth_headers, stream="true")
    events = _parse_sse(response.text)
    names = [name for name, _ in events]

    assert "flow_failed" in names
    assert names.index("flow_failed") < names.index("error")
    failed = next(p for n, p in events if n == "flow_failed")
    assert failed["retryable"] is True
    assert "no valid output" in failed["message"]


async def test_flow_events_do_not_duplicate_audit_rows(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "audit"}, headers=auth_headers
        )
    ).json()
    response = await _post_message(client, session["id"], auth_headers, stream="true")
    assert response.status_code == 200
    rows = (
        (await db.execute(select(AIGeneration).where(AIGeneration.task_type == "chat")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "ok"


async def test_stream_emits_tool_call_trace_events(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    """: completed tool cards stream in after `ground` opens and
    before the first delta; flow_finished carries the turn meta."""
    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "trace"}, headers=auth_headers
        )
    ).json()
    response = await _post_message(client, session["id"], auth_headers, stream="true")
    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [name for name, _ in events]

    tool_events = [payload for name, payload in events if name == "tool_call"]
    assert tool_events, "expected at least the catalog search tool card"
    first = tool_events[0]
    assert first["name"] == "search_jobs"
    assert first["title"] == "Searching the job catalog"
    assert first["status"] == "done"
    assert isinstance(first["duration_ms"], int)
    assert "durationMs" not in first
    assert len(first["args"]) <= 300
    assert len(first["result"]) <= 300

    first_delta = names.index("delta")
    tool_indexes = [i for i, name in enumerate(names) if name == "tool_call"]
    assert min(tool_indexes) > names.index("node_started")
    assert max(tool_indexes) < first_delta

    finished = [p for n, p in events if n == "node_finished"]
    assert all(isinstance(p.get("duration_ms"), int) for p in finished)

    flow_finished = next(p for n, p in events if n == "flow_finished")
    assert flow_finished["total_ms"] > 0
    assert flow_finished["tool_count"] == len(tool_events)
    assert isinstance(flow_finished["model"], str) and flow_finished["model"]

    messages = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    meta = messages[-1]["metadata_json"]
    assert meta["model"] == flow_finished["model"]
    assert 0 < meta["elapsed_ms"] <= flow_finished["total_ms"] + 5
    assert len(meta["tools"]) == len(tool_events)
    assert all(isinstance(t["duration_ms"], int) for t in meta["tools"])
    assert all(len(t["args_summary"]) <= 300 for t in meta["tools"])
    assert meta["referenced_job_codes"] is not None
    assert meta["referenced_posting_refs"] is not None
    # Persisted-trace wave: per-tool execution window + status, graph-node
    # windows and token usage (when the provider reports it).
    assert all(t["status"] == "done" for t in meta["tools"])
    assert all(
        isinstance(t["start_ms"], int) and t["start_ms"] >= 0 for t in meta["tools"]
    )
    node_ids = [node["id"] for node in meta["nodes"]]
    assert node_ids == ["ground", "generate"]
    assert all(node["status"] == "done" for node in meta["nodes"])
    assert all(isinstance(node["duration_ms"], int) for node in meta["nodes"])
    assert meta["nodes"][0]["start_ms"] == 0
    for key in ("tokens_in", "tokens_out"):
        assert meta.get(key) is None or isinstance(meta[key], int)


async def test_tool_call_events_stay_additive_for_edit_and_regenerate(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    """Branching endpoints reuse the shared stream, so they
    inherit the trace events and persisted metadata."""
    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "branch"}, headers=auth_headers
        )
    ).json()
    first = await _post_message(client, session["id"], auth_headers, stream="true")
    assert first.status_code == 200
    messages = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    user_message_id = messages[0]["id"]

    response = await client.post(
        f"/api/v1/chat/messages/{user_message_id}/regenerate",
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert "tool_call" in names
    finished = next(p for n, p in events if n == "flow_finished")
    assert finished["total_ms"] > 0


def test_summarize_caps_trace_strings():
    """: summaries are serialized-safe and truncated to
    SUMMARY_LIMIT — on the wire and in the persisted trace alike."""
    from app.ai.agents.chatbot import SUMMARY_LIMIT, _summarize

    assert len(_summarize({"blob": "x" * 500})) == SUMMARY_LIMIT
    assert _summarize({"code": "DATA-01"}) == '{"code": "DATA-01"}'
    assert _summarize(None) == "null"
    assert _summarize(object()).startswith('"')


async def test_interrupted_turn_persists_partial_trace(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    """The persisted-trace wave: an aborted turn keeps the tool + node
    trace gathered so far (not just the stream_interrupted flag)."""
    from app.models.chat_model import ChatSession as ChatSessionRow
    from app.services.chat_service import ChatService

    created = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "interrupted"}, headers=auth_headers
        )
    ).json()
    session_row = (
        (
            await db.execute(
                select(ChatSessionRow).where(ChatSessionRow.id == created["id"])
            )
        )
        .scalars()
        .one()
    )
    service = ChatService(db)
    _, _, parent_id = await service.begin_message(
        session_row.user_id, session_row.id, "trace me"
    )
    await service.complete_interrupted(
        session_row,
        parent_id,
        "partial answer so far",
        metadata={
            "tools": [
                {
                    "name": "search_jobs",
                    "title": "Searching the job catalog",
                    "status": "done",
                    "start_ms": 0,
                    "args_summary": '{"query": "nurse"}',
                    "duration_ms": 9,
                }
            ],
            "nodes": [
                {
                    "id": "ground",
                    "label": "searching the catalog",
                    "status": "interrupted",
                    "start_ms": 0,
                    "duration_ms": 900,
                }
            ],
            "elapsed_ms": 900,
            "model": "gpt-5.6",
        },
    )

    messages = (
        await client.get(
            f"/api/v1/chat/sessions/{created['id']}/messages", headers=auth_headers
        )
    ).json()
    meta = messages[-1]["metadata_json"]
    assert meta["stream_interrupted"] is True
    assert meta["tools"][0]["name"] == "search_jobs"
    assert meta["nodes"][0]["status"] == "interrupted"
    assert meta["model"] == "gpt-5.6"
