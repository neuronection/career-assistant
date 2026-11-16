"""Plan 58 P2: call-time cost provenance and system price overrides."""

from sqlalchemy import select

from app.ai import gateway as gateway_module
from app.ai.gateway import ainvoke_structured
from app.models.ai_model import AIGeneration, AIPriceOverride
from app.models.enums import AITaskType
from tests.test_ai_budgets import _assign_real_model, _FakeChatModel, _Out


async def test_call_time_cost_uses_override_and_records_provenance(db, monkeypatch):
    user = await _assign_real_model(db, "pricing-cost@example.com")
    db.add(
        AIPriceOverride(
            provider_key=None,
            provider_ref=None,
            model="gpt-test",
            match="exact",
            input_micros_per_million=2_000_000,
            output_micros_per_million=6_000_000,
            metering="tokens",
        )
    )
    await db.commit()
    monkeypatch.setattr(gateway_module, "build_chat_model", lambda resolved: _FakeChatModel())

    await ainvoke_structured(db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id)

    row = (await db.execute(select(AIGeneration))).scalars().one()
    assert row.tokens_in == 5 and row.tokens_out == 5
    assert row.cost_micros == 40  # 5*2 + 5*6 micro-dollars
    assert row.usage_source == "provider"
    assert row.price_source == "user"
    assert row.price_version is not None
    assert row.provider_key is None


async def test_unknown_price_stays_null_not_zero(db, monkeypatch):
    user = await _assign_real_model(db, "pricing-unknown@example.com")
    monkeypatch.setattr(gateway_module, "build_chat_model", lambda resolved: _FakeChatModel())

    await ainvoke_structured(db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id)

    row = (await db.execute(select(AIGeneration))).scalars().one()
    assert row.cost_micros is None
    assert row.price_source == "unknown"


async def test_local_provider_is_priced_at_zero(db, monkeypatch):
    user = await _assign_real_model(db, "pricing-local@example.com")
    from app.models.ai_provider_model import AIProvider

    provider = (await db.execute(select(AIProvider))).scalars().one()
    provider.is_local = True
    await db.commit()
    monkeypatch.setattr(gateway_module, "build_chat_model", lambda resolved: _FakeChatModel())

    await ainvoke_structured(db, AITaskType.ASSIST, _Out, "s", "u", user_id=user.id)

    row = (await db.execute(select(AIGeneration))).scalars().one()
    assert row.cost_micros == 0
    assert row.price_source == "local"


async def test_price_override_api_crud(client, auth_headers, db):
    created = await client.put(
        "/api/v1/ai/prices",
        json={
            "model": "gpt-6.1-sol",
            "provider_key": "openai",
            "input_micros_per_million": 2_000_000,
            "output_micros_per_million": 10_000_000,
            "metering": "tokens",
        },
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["provider_key"] == "openai"

    listed = (await client.get("/api/v1/ai/prices", headers=auth_headers)).json()
    assert len(listed["overrides"]) == 1

    updated = await client.put(
        "/api/v1/ai/prices",
        json={
            "model": "gpt-6.1-sol",
            "provider_key": "openai",
            "input_micros_per_million": 3_000_000,
            "output_micros_per_million": 12_000_000,
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["input_micros_per_million"] == 3_000_000
    assert updated.json()["id"] == body["id"]

    deleted = await client.delete(f"/api/v1/ai/prices/{body['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/ai/prices", headers=auth_headers)).json()["overrides"] == []


async def test_price_override_api_is_admin_only(client, auth_headers):
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "pricing-member@example.com", "password": "password123"},
    )
    from tests.conftest import session_headers

    member = session_headers(other)
    response = await client.put(
        "/api/v1/ai/prices",
        json={
            "model": "gpt-6.1-sol",
            "input_micros_per_million": 1,
            "output_micros_per_million": 1,
        },
        headers=member,
    )
    assert response.status_code == 403
    listing = await client.get("/api/v1/ai/prices", headers=member)
    assert listing.status_code == 403
    assert (await client.get("/api/v1/ai/prices", headers=auth_headers)).status_code == 200
