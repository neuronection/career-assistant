""": generalized budgets — hard stops, windowing, rollups."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.ai import gateway as gateway_module
from app.ai.budgets import usage_rollups, window_start
from app.ai.gateway import StructuredStream, ainvoke_structured
from app.core.errors import DomainError
from app.models.ai_model import AIBudget, AIGeneration
from app.models.enums import AITaskType
from pydantic import BaseModel


class _Out(BaseModel):
    answer: str


class _FakeChatModel:
    async def ainvoke(self, messages):
        from langchain_core.messages import AIMessage

        return AIMessage(
            content='{"answer": "ok"}',
            usage_metadata={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
        )


async def _assign_real_model(db, email: str, scope: str = "user"):
    from app.core.encryption import encrypt_secret
    from app.core.security import hash_password
    from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
    from app.models.user_model import User

    user = User(email=email, password_hash=hash_password("pw123456"))
    db.add(user)
    await db.flush()
    prov = AIProvider(
        name=f"prov-{email}",
        scope=scope,
        user_id=user.id if scope == "user" else None,
        provider_type="openai_compatible",
        api_base="https://api.example.com/v1",
        api_key_encrypted=encrypt_secret("sk-secret-123"),
    )
    db.add(prov)
    await db.flush()
    model = AIModel(provider_id=prov.id, name="m", model_name="gpt-test")
    db.add(model)
    await db.flush()
    db.add(
        AITaskAssignment(
            task_type=AITaskType.ASSIST.value,
            scope=scope,
            user_id=user.id if scope == "user" else None,
            provider_id=prov.id,
            model_id=model.id,
        )
    )
    await db.commit()
    return user


async def _spend(db, user_id, tokens, *, task="assist", age=None):
    db.add(
        AIGeneration(
            user_id=user_id,
            task_type=task,
            provider="openai_compatible",
            model="gpt-test",
            prompt="p",
            output={"answer": "x"},
            tokens_in=tokens,
            tokens_out=0,
            latency_ms=1.0,
            status="ok",
            created_at=(
                datetime.now(timezone.utc) - age if age else datetime.now(timezone.utc)
            ),
        )
    )
    await db.commit()


async def test_budget_hard_stop_blocks_invoke(db, monkeypatch):
    user = await _assign_real_model(db, "budget-stop@example.com")
    await _spend(db, user.id, 1000)
    db.add(
        AIBudget(name="assist cap", task_type="assist", window="day", max_tokens=100)
    )
    await db.commit()
    called = []

    def _factory(resolved):
        called.append(resolved)
        return _FakeChatModel()

    monkeypatch.setattr(gateway_module, "build_chat_model", _factory)
    with pytest.raises(DomainError, match="assist cap"):
        await ainvoke_structured(db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id)
    assert called == []


async def test_budget_window_ignores_old_spend(db, monkeypatch):
    user = await _assign_real_model(db, "budget-window@example.com")
    await _spend(db, user.id, 1000, age=timedelta(days=3))
    db.add(
        AIBudget(name="assist cap", task_type="assist", window="day", max_tokens=100)
    )
    await db.commit()
    monkeypatch.setattr(
        gateway_module, "build_chat_model", lambda resolved: _FakeChatModel()
    )
    result = await ainvoke_structured(
        db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id
    )
    assert result.answer == "ok"


async def test_budget_user_scope_only_binds_that_user(db, monkeypatch):
    user = await _assign_real_model(db, "budget-scope@example.com")
    other = await _assign_real_model(db, "budget-other@example.com")
    await _spend(db, other.id, 1000)
    db.add(
        AIBudget(
            name="other cap",
            task_type=None,
            user_id=other.id,
            window="day",
            max_tokens=10,
        )
    )
    await db.commit()
    monkeypatch.setattr(
        gateway_module, "build_chat_model", lambda resolved: _FakeChatModel()
    )
    result = await ainvoke_structured(
        db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id
    )
    assert result.answer == "ok"


async def test_budget_blocks_stream_before_first_chunk(db, monkeypatch):
    user = await _assign_real_model(db, "budget-stream@example.com")
    await _spend(db, user.id, 1000)
    db.add(
        AIBudget(name="stream cap", task_type="assist", window="day", max_tokens=100)
    )
    await db.commit()
    stream = StructuredStream()
    with pytest.raises(DomainError, match="stream cap"):
        async for _ in stream.chunks(
            db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id
        ):
            pass
    rows = (await db.execute(select(AIGeneration))).scalars().all()
    assert len(rows) == 1  # only the seeded spend; the stop is not audited


async def test_global_budget_matches_unscoped_calls(db, monkeypatch):
    await _assign_real_model(db, "budget-global@example.com", scope="system")
    await _spend(db, None, 1000)
    db.add(AIBudget(name="global cap", task_type=None, window="day", max_tokens=10))
    await db.commit()
    await db.commit()
    monkeypatch.setattr(
        gateway_module, "build_chat_model", lambda resolved: _FakeChatModel()
    )
    with pytest.raises(DomainError, match="global cap"):
        await ainvoke_structured(db, AITaskType.ASSIST, _Out, "s", "u")


def test_window_start_anchors():
    now = datetime(2026, 9, 4, 15, 30, tzinfo=timezone.utc)
    assert window_start("day", now) == datetime(2026, 9, 4, tzinfo=timezone.utc)
    assert window_start("month", now) == datetime(2026, 9, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        window_start("week")


async def test_usage_rollups_sum_per_task(db):
    user = await _assign_real_model(db, "rollups@example.com")
    await _spend(db, user.id, 7, task="assist")
    await _spend(db, user.id, 3, task="assist")
    await _spend(db, user.id, 11, task="chat")
    rollups = {r["task_type"]: r for r in await usage_rollups(db, "day")}
    assert rollups["assist"]["calls"] == 2
    assert rollups["assist"]["tokens_in"] == 10
    assert rollups["chat"]["tokens_in"] == 11


async def test_budget_crud_api(client, auth_headers, db):
    created = await client.post(
        "/api/v1/ai/budgets",
        json={"name": "daily chat cap", "task_type": "chat", "max_tokens": 50000},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    budget_id = created.json()["id"]

    listed = (await client.get("/api/v1/ai/budgets", headers=auth_headers)).json()
    assert any(b["name"] == "daily chat cap" for b in listed)

    dup = await client.post(
        "/api/v1/ai/budgets",
        json={"name": "daily chat cap", "max_tokens": 1},
        headers=auth_headers,
    )
    assert dup.status_code == 409

    bad_task = await client.post(
        "/api/v1/ai/budgets",
        json={"name": "x", "task_type": "nope", "max_tokens": 1},
        headers=auth_headers,
    )
    assert bad_task.status_code == 404

    deleted = await client.delete(
        f"/api/v1/ai/budgets/{budget_id}", headers=auth_headers
    )
    assert deleted.status_code == 204


async def test_budgets_and_rollups_are_admin_only(client, auth_headers):
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "member-budget@example.com", "password": "password123"},
    )
    member = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert (await client.get("/api/v1/ai/budgets", headers=member)).status_code == 403
    assert (
        await client.get("/api/v1/ai/usage/rollups", headers=member)
    ).status_code == 403
    assert (
        await client.get("/api/v1/ai/usage/rollups", headers=auth_headers)
    ).status_code == 200
