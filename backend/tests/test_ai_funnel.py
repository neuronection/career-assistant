"""Funnel internals on the LangChain factory: invoke, retry, usage, stream.

Fakes replace ``build_chat_model`` — no network, no provider SDKs.
"""

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from pydantic import BaseModel
from sqlalchemy import select

from app.ai import gateway as provider_module
from app.ai.gateway import StructuredAIError, StructuredStream, ainvoke_structured
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType

USAGE = {"input_tokens": 12, "output_tokens": 34, "total_tokens": 46}


class _Out(BaseModel):
    answer: str


class _FakeChatModel:
    """Stands in for the factory product; returns scripted replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[list] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return AIMessage(content=reply, usage_metadata=dict(USAGE))


class _FakeStreamModel:
    """Stands in for the factory product; streams scripted pieces."""

    def __init__(self, pieces):
        self.pieces = list(pieces)
        self.calls: list[list] = []

    def astream(self, messages):
        self.calls.append(messages)
        pieces = self.pieces

        async def _gen():
            for piece in pieces:
                yield AIMessageChunk(content=piece)
            yield AIMessageChunk(content="", usage_metadata=dict(USAGE))

        return _gen()


async def _assign_real_model(db, provider_type="openai_compatible", **overrides):
    from app.core.security import hash_password
    from app.core.encryption import encrypt_secret
    from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
    from app.models.user_model import User

    user = User(email="funnel@example.com", password_hash=hash_password("pw123456"))
    db.add(user)
    await db.flush()
    defaults = dict(
        name="prov",
        scope="user",
        user_id=user.id,
        provider_type=provider_type,
        api_base="https://api.example.com/v1",
        api_key_encrypted=encrypt_secret("sk-secret-123"),
    )
    defaults.update(overrides)
    prov = AIProvider(**defaults)
    db.add(prov)
    await db.flush()
    model = AIModel(provider_id=prov.id, name="m", model_name="gpt-test")
    db.add(model)
    await db.flush()
    db.add(
        AITaskAssignment(
            task_type=AITaskType.ASSIST.value,
            scope="user",
            user_id=user.id,
            provider_id=prov.id,
            model_id=model.id,
        )
    )
    await db.commit()
    return user


async def test_invoke_records_usage_and_provider(db, monkeypatch):
    user = await _assign_real_model(db)
    fake = _FakeChatModel(['{"answer": "hello"}'])
    monkeypatch.setattr(provider_module, "build_chat_model", lambda resolved: fake)

    result = await ainvoke_structured(
        db,
        AITaskType.ASSIST,
        _Out,
        system="sys",
        user="usr",
        user_id=user.id,
    )
    assert result.answer == "hello"

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
    assert rows[0].provider == "openai_compatible"
    assert rows[0].tokens_in == 12
    assert rows[0].tokens_out == 34
    assert rows[0].output == {"answer": "hello"}


async def test_invoke_retries_after_failure(db, monkeypatch):
    user = await _assign_real_model(db)
    fake = _FakeChatModel([RuntimeError("boom"), '{"answer": "recovered"}'])
    monkeypatch.setattr(provider_module, "build_chat_model", lambda resolved: fake)

    result = await ainvoke_structured(
        db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id
    )
    assert result.answer == "recovered"
    assert len(fake.calls) == 2


async def test_invoke_fails_after_three_attempts(db, monkeypatch):
    user = await _assign_real_model(db)
    fake = _FakeChatModel([ValueError("no json")] * 5)
    monkeypatch.setattr(provider_module, "build_chat_model", lambda resolved: fake)

    with pytest.raises(StructuredAIError, match="3 attempts"):
        await ainvoke_structured(db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id)
    assert len(fake.calls) == 3
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
    assert rows[0].status == "error"
    assert "no json" in rows[0].error


async def test_invoke_sends_vision_parts(db, monkeypatch):
    user = await _assign_real_model(db)
    fake = _FakeChatModel(['{"answer": "seen"}'])
    monkeypatch.setattr(provider_module, "build_chat_model", lambda resolved: fake)

    await ainvoke_structured(
        db,
        AITaskType.ASSIST,
        _Out,
        "s",
        "look",
        user_id=user.id,
        images=[("image/png", b"png")],
    )
    user_message = fake.calls[0][1]
    blocks = user_message.content
    assert blocks[0] == {"type": "text", "text": "look"}
    assert blocks[1]["type"] == "image_url"
    assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_stream_yields_pieces_and_audits_once(db, monkeypatch):
    user = await _assign_real_model(db)
    fake = _FakeStreamModel(['{"answer": "Hel', 'lo there"}'])
    monkeypatch.setattr(provider_module, "build_chat_model", lambda resolved: fake)

    stream = StructuredStream()
    pieces = [
        piece
        async for piece in stream.chunks(
            db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id
        )
    ]
    assert pieces == ['{"answer": "Hel', 'lo there"}']
    assert stream.reply is not None
    assert stream.reply.answer == "Hello there"

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
    assert rows[0].tokens_in == 12
    assert rows[0].tokens_out == 34
