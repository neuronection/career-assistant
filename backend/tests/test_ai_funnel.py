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


class _FakeRecoveryModel:
    """Streams scripted pieces, then answers `ainvoke` rescues."""

    def __init__(self, pieces, replies, finish_reason="STOP"):
        self.pieces = list(pieces)
        self.replies = list(replies)
        self.finish_reason = finish_reason
        self.invoke_calls = 0

    def astream(self, messages):
        pieces = self.pieces
        finish_reason = self.finish_reason

        async def _gen():
            for piece in pieces:
                yield AIMessageChunk(
                    content=piece, response_metadata={"finish_reason": finish_reason}
                )
            yield AIMessageChunk(content="", usage_metadata=dict(USAGE))

        return _gen()

    async def ainvoke(self, messages):
        self.invoke_calls += 1
        reply = self.replies[min(self.invoke_calls - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return AIMessage(
            content=reply,
            usage_metadata=dict(USAGE),
            response_metadata={"finish_reason": self.finish_reason},
        )


async def test_stream_whitespace_chunks_fall_back_to_invoke(db, monkeypatch):
    user = await _assign_real_model(db)
    fake = _FakeRecoveryModel([" ", " \n"], ['{"answer": "recovered"}'])
    monkeypatch.setattr(provider_module, "build_chat_model", lambda resolved: fake)

    stream = StructuredStream()
    pieces = [
        piece
        async for piece in stream.chunks(
            db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id
        )
    ]
    assert stream.reply is not None
    assert stream.reply.answer == "recovered"
    assert fake.invoke_calls == 1
    assert pieces[-1] == '{"answer": "recovered"}'


async def test_stream_prose_reply_rescued_by_invoke(db, monkeypatch):
    user = await _assign_real_model(db)
    fake = _FakeRecoveryModel(
        ["Sure — here is my take, no JSON at all."], ['{"answer": "rescued"}']
    )
    monkeypatch.setattr(provider_module, "build_chat_model", lambda resolved: fake)

    stream = StructuredStream()
    pieces = [
        piece
        async for piece in stream.chunks(
            db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id
        )
    ]
    assert stream.reply is not None
    assert stream.reply.answer == "rescued"
    assert fake.invoke_calls == 1
    assert '{"answer": "rescued"}' in pieces


async def test_stream_rescue_failure_audits_raw_snippet(db, monkeypatch):
    user = await _assign_real_model(db)
    fake = _FakeRecoveryModel(
        ["Plain prose, still no braces."], ["Still prose on the retry."]
    )
    monkeypatch.setattr(provider_module, "build_chat_model", lambda resolved: fake)

    stream = StructuredStream()
    with pytest.raises(StructuredAIError, match="not usable structured output"):
        async for _ in stream.chunks(
            db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id
        ):
            pass
    assert fake.invoke_calls == 1
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
    assert "raw=" in rows[0].error
    assert "Plain prose" in rows[0].error


async def test_stream_no_rescue_after_answer_text_streamed(db, monkeypatch):
    user = await _assign_real_model(db)
    fake = _FakeRecoveryModel(['{"answer": "Hel'], [])
    monkeypatch.setattr(provider_module, "build_chat_model", lambda resolved: fake)

    stream = StructuredStream()
    with pytest.raises(StructuredAIError, match="not usable structured output"):
        async for _ in stream.chunks(
            db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id
        ):
            pass
    assert fake.invoke_calls == 0


async def test_stream_failure_names_token_cap(db, monkeypatch):
    user = await _assign_real_model(db)
    fake = _FakeRecoveryModel(
        ["Prose only."],
        ["Prose again."],
        finish_reason="MAX_TOKENS",
    )
    monkeypatch.setattr(provider_module, "build_chat_model", lambda resolved: fake)

    stream = StructuredStream()
    with pytest.raises(StructuredAIError, match="token cap"):
        async for _ in stream.chunks(
            db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id
        ):
            pass


async def test_stream_carries_image_parts(db, monkeypatch):
    """Plan 83A: images ride the streaming path as multimodal parts —
    the same encoding the non-streaming invoke uses."""
    user = await _assign_real_model(db)
    fake = _FakeStreamModel(['{"answer": "seen"}'])
    monkeypatch.setattr(provider_module, "build_chat_model", lambda resolved: fake)

    stream = StructuredStream()
    pieces = [
        piece
        async for piece in stream.chunks(
            db,
            AITaskType.ASSIST,
            _Out,
            "s",
            "look",
            user_id=user.id,
            images=[("image/png", b"png-bytes")],
        )
    ]
    assert stream.reply.answer == "seen"
    assert pieces == ['{"answer": "seen"}']

    user_message = fake.calls[0][1]
    assert user_message.content[0] == {"type": "text", "text": "look"}
    assert user_message.content[1]["type"] == "image_url"
    assert user_message.content[1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )


async def test_invoke_and_stream_share_user_content_encoding():
    from app.ai.gateway import _user_content

    assert _user_content("hi", None) == "hi"
    parts = _user_content("hi", [("image/png", b"x")])
    assert parts[0] == {"type": "text", "text": "hi"}
    assert parts[1]["image_url"]["url"] == "data:image/png;base64,eA=="
