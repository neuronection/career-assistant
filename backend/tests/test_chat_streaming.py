"""Chat streaming: SSE event order, persistence, audit, partial extraction."""

import json


from app.ai.provider import StructuredStream, partial_answer_text
from app.models.ai_model import AIGeneration
from sqlalchemy import select


def test_partial_answer_text_extracts_growing_value():
    assert partial_answer_text('{"foo": 1, ') == ""
    assert partial_answer_text('{"answer": "') == ""
    assert partial_answer_text('{"answer": "Hel') == "Hel"
    assert partial_answer_text('{"answer": "Hello \\n world"}') == "Hello \n world"
    assert partial_answer_text('{"answer": "done", "x": 1}') == "done"


async def _post_message(client, session_id, headers, **params):
    return await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "data science careers"},
        params=params or None,
        headers=headers,
    )


async def test_stream_events_order_and_persistence(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "stream"}, headers=auth_headers
        )
    ).json()

    response = await _post_message(client, session["id"], auth_headers, stream="true")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "status"
    assert "delta" in names
    assert names[-1] == "done"
    assert "error" not in names

    deltas = "".join(payload["text"] for name, payload in events if name == "delta")
    assert len(deltas) > 0

    meta = next(payload for name, payload in events if name == "meta")
    assert meta["referenced_job_codes"] is not None

    messages = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == deltas

    audit = (
        (await db.execute(select(AIGeneration).where(AIGeneration.task_type == "chat")))
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert audit[0].status == "ok"


async def test_non_streaming_path_unchanged(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "sync"}, headers=auth_headers
        )
    ).json()
    response = await _post_message(client, session["id"], auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert [m["role"] for m in body] == ["user", "assistant"]
    audit = (
        (await db.execute(select(AIGeneration).where(AIGeneration.task_type == "chat")))
        .scalars()
        .all()
    )
    assert len(audit) == 1


async def test_stream_reports_error_when_ai_fails(
    client, db, auth_headers, profile_ready, seeded_catalog, monkeypatch
):
    from app.ai.provider import StructuredAIError

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
    assert "error" in names
    error_payload = next(p for n, p in events if n == "error")
    assert "no valid output" in error_payload["detail"]


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
