import pytest
from app.core.encryption import (
    decrypt_secret,
    encrypt_secret,
    is_encrypted,
    mask_secret,
)
from app.ai.providers.resolution import resolve_task_model
from app.ai.providers.service import AIProviderService
from app.core.security import hash_password
from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
from app.models.enums import AITaskType
from app.models.user_model import User


async def _mk_user(db, email: str, is_admin: bool = False) -> User:
    user = User(
        email=email, password_hash=hash_password("password123"), is_admin=is_admin
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _mk_provider_with_model(
    db, user: User, scope: str, model_name: str, provider_type: str = "mock"
) -> tuple[AIProvider, AIModel]:
    provider = AIProvider(
        name=f"prov-{model_name}",
        scope=scope,
        user_id=user.id if scope == "user" else None,
        provider_type=provider_type,
        api_base="https://api.example.com/v1",
        api_key_encrypted=encrypt_secret("sk-secret-123"),
    )
    db.add(provider)
    await db.flush()
    model = AIModel(provider_id=provider.id, name=model_name, model_name=model_name)
    db.add(model)
    await db.flush()
    db.add(
        AITaskAssignment(
            task_type="match_score",
            scope=scope,
            user_id=user.id if scope == "user" else None,
            provider_id=provider.id,
            model_id=model.id,
        )
    )
    await db.commit()
    return provider, model


async def test_encryption_round_trip():
    encrypted = encrypt_secret("sk-live-abc")
    assert is_encrypted(encrypted)
    assert "sk-live-abc" not in encrypted
    assert decrypt_secret(encrypted) == "sk-live-abc"
    assert decrypt_secret("legacy-plaintext") == "legacy-plaintext"
    assert mask_secret(encrypted) == "***"
    assert decrypt_secret(None) is None


async def test_first_registered_user_becomes_admin(client, db):
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "first@example.com", "password": "password123"},
    )
    assert first.status_code == 201
    await client.post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": "password123"},
    )
    from sqlalchemy import select

    from app.models.user_model import User

    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    by_email = {u.email: u.is_admin for u in rows}
    assert by_email["first@example.com"] is True
    assert by_email["second@example.com"] is False


async def test_provider_crud_and_key_masking(client, auth_headers):
    created = await client.post(
        "/api/v1/ai/providers",
        json={
            "name": "My OpenRouter",
            "provider_type": "openai_compatible",
            "api_base": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-123",
            "scope": "user",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["api_key"] == "***"
    assert "sk-or-123" not in created.text

    listed = (await client.get("/api/v1/ai/providers", headers=auth_headers)).json()
    assert any(p["name"] == "My OpenRouter" for p in listed)

    updated = await client.put(
        f"/api/v1/ai/providers/{body['id']}",
        json={"api_key": "***", "name": "Renamed"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["api_key"] == "***"


async def test_personal_provider_is_private(client, auth_headers):
    await client.post(
        "/api/v1/ai/providers",
        json={
            "name": "Private",
            "provider_type": "openai",
            "api_key": "sk-1",
            "scope": "user",
        },
        headers=auth_headers,
    )
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "snoop@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    listed = (await client.get("/api/v1/ai/providers", headers=other_headers)).json()
    assert not any(p["name"] == "Private" for p in listed)


async def test_system_provider_requires_admin(client, auth_headers):
    member = await client.post(
        "/api/v1/auth/register",
        json={"email": "member@example.com", "password": "password123"},
    )
    member_headers = {"Authorization": f"Bearer {member.json()['access_token']}"}
    forbidden = await client.post(
        "/api/v1/ai/providers",
        json={"name": "Global", "provider_type": "openai", "scope": "system"},
        headers=member_headers,
    )
    assert forbidden.status_code == 403
    allowed = await client.post(
        "/api/v1/ai/providers",
        json={"name": "Global", "provider_type": "openai", "scope": "system"},
        headers=auth_headers,
    )
    assert allowed.status_code == 201


async def test_admin_manages_system_provider(client, auth_headers):
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert me["is_admin"] is True

    created = await client.post(
        "/api/v1/ai/providers",
        json={
            "name": "Org OpenAI",
            "provider_type": "openai",
            "api_base": "https://api.openai.com/v1",
            "api_key": "sk-org",
            "scope": "system",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    provider_id = created.json()["id"]
    model = await client.post(
        f"/api/v1/ai/providers/{provider_id}/models",
        json={"name": "GPT-4o mini", "model_name": "gpt-4o-mini"},
        headers=auth_headers,
    )
    assert model.status_code == 201
    model_id = model.json()["id"]

    assignment = await client.put(
        "/api/v1/ai/assignments/match_score",
        json={"scope": "system", "model_id": model_id},
        headers=auth_headers,
    )
    assert assignment.status_code == 200, assignment.text

    summary = (
        await client.get("/api/v1/ai/config/summary", headers=auth_headers)
    ).json()
    match_task = next(t for t in summary["tasks"] if t["task_type"] == "match_score")
    assert match_task["model_name"] == "gpt-4o-mini"
    assert match_task["source"] == "system:match_score"
    assert summary["can_manage_global"] is True


async def test_user_assignment_overrides_system(
    db, client, auth_headers, seeded_catalog
):
    admin_headers = auth_headers
    created = await client.post(
        "/api/v1/ai/providers",
        json={"name": "Org", "provider_type": "mock", "scope": "system"},
        headers=admin_headers,
    )
    model = await client.post(
        f"/api/v1/ai/providers/{created.json()['id']}/models",
        json={"name": "org-model", "model_name": "org-large"},
        headers=admin_headers,
    )
    await client.put(
        "/api/v1/ai/assignments/match_score",
        json={"scope": "system", "model_id": model.json()["id"]},
        headers=admin_headers,
    )

    user = await _mk_user(db, "member@example.com", is_admin=False)
    personal_provider = AIProvider(
        name="personal",
        scope="user",
        user_id=user.id,
        provider_type="mock",
        api_base="https://x/v1",
    )
    db.add(personal_provider)
    await db.flush()
    personal_model = AIModel(
        provider_id=personal_provider.id, name="mine", model_name="my-small-model"
    )
    db.add(personal_model)
    await db.flush()
    db.add(
        AITaskAssignment(
            task_type="match_score",
            scope="user",
            user_id=user.id,
            provider_id=personal_provider.id,
            model_id=personal_model.id,
        )
    )
    await db.commit()

    resolved = await resolve_task_model(db, "match_score", user.id)
    assert resolved.model_name == "my-small-model"
    assert resolved.source == "user:match_score"

    other_user = await _mk_user(db, "member2@example.com", is_admin=False)
    resolved_other = await resolve_task_model(db, "match_score", other_user.id)
    assert resolved_other.model_name == "org-large"
    assert resolved_other.source == "system:match_score"


async def test_default_task_fallback(db, client, auth_headers):
    created = await client.post(
        "/api/v1/ai/providers",
        json={"name": "Fallback", "provider_type": "mock", "scope": "system"},
        headers=auth_headers,
    )
    model = await client.post(
        f"/api/v1/ai/providers/{created.json()['id']}/models",
        json={"name": "fallback", "model_name": "fallback-model"},
        headers=auth_headers,
    )
    await client.put(
        "/api/v1/ai/assignments/default",
        json={"scope": "system", "model_id": model.json()["id"]},
        headers=auth_headers,
    )
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    from sqlalchemy import select

    from app.models.user_model import User

    user = (
        (await db.execute(select(User).where(User.email == me["email"])))
        .scalars()
        .first()
    )
    resolved = await resolve_task_model(db, "chat", user.id)
    assert resolved.model_name == "fallback-model"
    assert resolved.source == "system:default"


async def test_invoke_uses_resolved_model(db, client, auth_headers, seeded_catalog):
    job = (await client.get("/api/v1/jobs/nurse", headers=auth_headers)).json()
    scored = await client.post(
        "/api/v1/match/score", json={"job_id": job["id"]}, headers=auth_headers
    )
    assert scored.status_code == 200

    from sqlalchemy import select

    from app.models.ai_model import AIGeneration

    rows = (
        (
            await db.execute(
                select(AIGeneration)
                .where(AIGeneration.task_type == AITaskType.MATCH_SCORE.value)
                .order_by(AIGeneration.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .all()
    )
    assert rows
    assert rows[0].provider == "mock"


async def test_test_connection_endpoint(client, auth_headers):
    created = await client.post(
        "/api/v1/ai/providers",
        json={"name": "Mock", "provider_type": "mock", "scope": "user"},
        headers=auth_headers,
    )
    model = await client.post(
        f"/api/v1/ai/providers/{created.json()['id']}/models",
        json={"name": "m", "model_name": "mock-1"},
        headers=auth_headers,
    )
    result = await client.post(
        f"/api/v1/ai/test?provider_id={created.json()['id']}&model_id={model.json()['id']}",
        headers=auth_headers,
    )
    assert result.status_code == 200
    assert result.json()["ok"] is True


@pytest.mark.parametrize(
    ("provider_type", "expected_param"),
    [
        ("openai", "max_completion_tokens"),
        ("openai_compatible", "max_tokens"),
    ],
)
async def test_run_test_sends_cap_param_per_provider_type(
    db, provider_type, expected_param, monkeypatch
):
    """Modern OpenAI models reject `max_tokens`; compatible endpoints don't
    know `max_completion_tokens` — the test ping adapts per provider type."""

    import openai

    user = await _mk_user(db, f"testconn-{provider_type}@example.com")
    provider, model = await _mk_provider_with_model(
        db, user, "user", "gpt-test", provider_type=provider_type
    )
    captured = {}

    class _FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)

            class _Message:
                content = "OK"

            class _Choice:
                message = _Message()

            class _Response:
                choices = [_Choice()]
                usage = None

            return _Response()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self, **kwargs):
            self.chat = _FakeChat()

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)
    result = await AIProviderService(db).run_test(
        user, provider_id=provider.id, model_id=model.id
    )
    assert result["ok"] is True
    assert expected_param in captured
    unexpected = (
        "max_tokens"
        if expected_param == "max_completion_tokens"
        else "max_completion_tokens"
    )
    assert unexpected not in captured
