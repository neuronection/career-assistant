import json

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
    db,
    user: User,
    scope: str,
    model_name: str,
    provider_type: str = "mock",
    api_base: str = "https://api.example.com/v1",
) -> tuple[AIProvider, AIModel]:
    provider = AIProvider(
        name=f"prov-{model_name}",
        scope=scope,
        user_id=user.id if scope == "user" else None,
        provider_type=provider_type,
        api_base=api_base,
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


async def test_first_registered_user_becomes_admin(client, db, multi_user_mode):
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


async def test_system_provider_requires_admin(client, multi_user_mode):
    admin = await client.post(
        "/api/v1/auth/register",
        json={"email": "first@example.com", "password": "password123"},
    )
    admin_headers = {"Authorization": f"Bearer {admin.json()['access_token']}"}
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
        headers=admin_headers,
    )
    assert allowed.status_code == 201


async def test_admin_manages_system_provider(client, auth_headers):
    me = await client.get("/api/v1/auth/me")
    assert me.json()["is_admin"] is True

    created = await client.post(
        "/api/v1/ai/providers",
        json={
            "name": "Org OpenAI",
            "provider_type": "openai",
            "api_base": "https://api.openai.com/v1",
            "api_key": "sk-org",
            "scope": "system",
        },
    )
    assert created.status_code == 201
    provider_id = created.json()["id"]
    model = await client.post(
        f"/api/v1/ai/providers/{provider_id}/models",
        json={"name": "GPT-4o mini", "model_name": "gpt-4o-mini"},
    )
    assert model.status_code == 201
    model_id = model.json()["id"]

    assignment = await client.put(
        "/api/v1/ai/assignments/match_score",
        json={"scope": "system", "model_id": model_id},
    )
    assert assignment.status_code == 200, assignment.text

    summary = (await client.get("/api/v1/ai/config/summary")).json()
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


async def test_model_update_and_reasoning_effort(db, client, auth_headers):
    """Models are editable (PUT) and carry reasoning_effort end-to-end:
    API → DB → resolution → the ResolvedModel the factory consumes."""
    created = await client.post(
        "/api/v1/ai/providers",
        json={"name": "Reasoning Co", "provider_type": "mock", "scope": "system"},
        headers=auth_headers,
    )
    provider_id = created.json()["id"]
    model = await client.post(
        f"/api/v1/ai/providers/{provider_id}/models",
        json={
            "name": "o3",
            "model_name": "o3-mini",
            "reasoning_effort": "high",
            "temperature": 0.2,
            "max_tokens": 1024,
        },
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    body = model.json()
    assert body["reasoning_effort"] == "high"
    model_id = body["id"]

    updated = await client.put(
        f"/api/v1/ai/models/{model_id}",
        json={
            "name": "o3 (reasoning)",
            "reasoning_effort": "medium",
            "temperature": None,
            "max_tokens": 2048,
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    payload = updated.json()
    assert payload["name"] == "o3 (reasoning)"
    assert payload["reasoning_effort"] == "medium"
    assert payload["temperature"] is None
    assert payload["max_tokens"] == 2048

    cleared = await client.put(
        f"/api/v1/ai/models/{model_id}",
        json={"reasoning_effort": ""},
        headers=auth_headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["reasoning_effort"] is None
    assert cleared.json()["temperature"] is None
    assert cleared.json()["max_tokens"] == 2048

    restored = await client.put(
        f"/api/v1/ai/models/{model_id}",
        json={"reasoning_effort": "medium"},
        headers=auth_headers,
    )
    assert restored.json()["reasoning_effort"] == "medium"

    await client.put(
        "/api/v1/ai/assignments/match_score",
        json={"scope": "system", "model_id": model_id},
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
    resolved = await resolve_task_model(db, "match_score", user.id)
    assert resolved.model_name == "o3-mini"
    assert resolved.reasoning_effort == "medium"


async def test_model_caps_persist(db, client, auth_headers):
    """Capability toggles persist end-to-end: create → update → clear,
    with unknown capability keys rejected (matches the UI's toggles)."""
    created = await client.post(
        "/api/v1/ai/providers",
        json={"name": "Caps Co", "provider_type": "mock", "scope": "system"},
        headers=auth_headers,
    )
    provider_id = created.json()["id"]
    model = await client.post(
        f"/api/v1/ai/providers/{provider_id}/models",
        json={"name": "m", "model_name": "gpt-test", "caps": ["text", "vision"]},
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    body = model.json()
    assert body["caps"] == ["text", "vision"]
    model_id = body["id"]

    updated = await client.put(
        f"/api/v1/ai/models/{model_id}",
        json={"caps": ["text", "tools", "audio"]},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["caps"] == ["text", "tools", "audio"]

    # Sparse update: omitted caps stay unchanged.
    untouched = await client.put(
        f"/api/v1/ai/models/{model_id}",
        json={"name": "renamed"},
        headers=auth_headers,
    )
    assert untouched.json()["caps"] == ["text", "tools", "audio"]

    # Explicit null clears back to "not declared".
    cleared = await client.put(
        f"/api/v1/ai/models/{model_id}",
        json={"caps": None},
        headers=auth_headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["caps"] is None

    rejected = await client.post(
        f"/api/v1/ai/providers/{provider_id}/models",
        json={"name": "m", "model_name": "gpt-test", "caps": ["telepathy"]},
        headers=auth_headers,
    )
    assert rejected.status_code == 422
    assert "telepathy" in str(rejected.json()["detail"])


async def test_member_cannot_edit_system_model(client, auth_headers):
    created = await client.post(
        "/api/v1/ai/providers",
        json={"name": "Locked", "provider_type": "mock", "scope": "system"},
        headers=auth_headers,
    )
    model = await client.post(
        f"/api/v1/ai/providers/{created.json()['id']}/models",
        json={"name": "m", "model_name": "m-1"},
        headers=auth_headers,
    )
    member = await client.post(
        "/api/v1/auth/register",
        json={"email": "editor@example.com", "password": "password123"},
    )
    member_headers = {"Authorization": f"Bearer {member.json()['access_token']}"}
    forbidden = await client.put(
        f"/api/v1/ai/models/{model.json()['id']}",
        json={"name": "hijacked"},
        headers=member_headers,
    )
    assert forbidden.status_code == 400
    assert forbidden.json()["detail"] == "Only admins can edit global models"


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
    (
        "provider_type",
        "api_base",
        "expected_param",
    ),
    [
        ("openai", "https://api.example.com/v1", "max_completion_tokens"),
        ("openai_compatible", "https://api.example.com/v1", "max_tokens"),
        ("openai_compatible", "https://api.openai.com/v1", "max_completion_tokens"),
    ],
)
async def test_run_test_sends_cap_param_per_provider_type(
    db, provider_type, api_base, expected_param
):
    """Modern OpenAI models reject `max_tokens`; compatible endpoints don't
    know `max_completion_tokens` — the test ping adapts per provider type,
    and an api.openai.com base URL wins over the declared type."""

    import httpx

    user = await _mk_user(db, f"testconn-{provider_type}@example.com")
    provider, model = await _mk_provider_with_model(
        db, user, "user", "gpt-test", provider_type=provider_type, api_base=api_base
    )
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    result = await AIProviderService(db).run_test(
        user,
        provider_id=provider.id,
        model_id=model.id,
        transport=httpx.MockTransport(handler),
    )
    assert result["ok"] is True
    assert expected_param in captured
    unexpected = (
        "max_tokens"
        if expected_param == "max_completion_tokens"
        else "max_completion_tokens"
    )
    assert unexpected not in captured
    # Unset temperature is omitted — reasoning models reject non-default values.
    assert "temperature" not in captured


async def test_run_test_reports_http_error(db):
    import httpx

    user = await _mk_user(db, "testconn-error@example.com")
    provider, model = await _mk_provider_with_model(
        db, user, "user", "gpt-test", provider_type="openai_compatible"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    result = await AIProviderService(db).run_test(
        user,
        provider_id=provider.id,
        model_id=model.id,
        transport=httpx.MockTransport(handler),
    )
    assert result["ok"] is False
    assert "Error code: 401" in result["error"]
    assert "bad key" in result["error"]


async def test_provider_presets_endpoint(client, auth_headers):
    response = await client.get("/api/v1/ai/providers/presets", headers=auth_headers)
    assert response.status_code == 200, response.text
    presets = response.json()
    assert presets["openai"]["type"] == "openai"
    assert presets["gemini"]["type"] == "google"
    assert presets["gemini"]["base_url"] == (
        "https://generativelanguage.googleapis.com"
    )
    assert presets["openrouter"]["base_url"] == "https://openrouter.ai/api/v1"
    assert presets["ollama"]["local"] is True
    assert presets["lm_studio"]["base_url"] == "http://localhost:1234/v1"
    assert all("name" in preset and "type" in preset for preset in presets.values())


async def test_create_google_provider_persists(client, auth_headers):
    created = await client.post(
        "/api/v1/ai/providers",
        json={
            "name": "Google Gemini",
            "provider_type": "google",
            "api_base": "https://generativelanguage.googleapis.com",
            "api_key": "AIza-test",
            "scope": "user",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["provider_type"] == "google"

    listed = (await client.get("/api/v1/ai/providers", headers=auth_headers)).json()
    row = next(p for p in listed if p["name"] == "Google Gemini")
    assert row["provider_type"] == "google"


async def test_run_test_google_native_ping(db):
    """Google providers ping through the factory model (no OpenAI wire);
    the transport seam keeps the Gemini call offline."""
    import httpx

    from app.ai.chat_models import GOOGLE_BASE_URL

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "OK"}], "role": "model"},
                        "finishReason": "STOP",
                        "index": 0,
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 5,
                    "candidatesTokenCount": 1,
                    "totalTokenCount": 6,
                },
                "modelVersion": "gemini-test",
            },
        )

    user = await _mk_user(db, "testconn-google@example.com")
    provider, model = await _mk_provider_with_model(
        db,
        user,
        "user",
        "gemini-test",
        provider_type="google",
        api_base=GOOGLE_BASE_URL,
    )
    result = await AIProviderService(db).run_test(
        user,
        provider_id=provider.id,
        model_id=model.id,
        transport=httpx.MockTransport(handler),
    )
    assert result["ok"] is True, result
    assert result["reply"] == "OK"
    assert ":generateContent" in captured["url"]


async def test_run_test_google_reports_error(db):
    import httpx

    from app.ai.chat_models import GOOGLE_BASE_URL

    user = await _mk_user(db, "testconn-google-err@example.com")
    provider, model = await _mk_provider_with_model(
        db,
        user,
        "user",
        "gemini-test",
        provider_type="google",
        api_base=GOOGLE_BASE_URL,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "API key not valid"}})

    result = await AIProviderService(db).run_test(
        user,
        provider_id=provider.id,
        model_id=model.id,
        transport=httpx.MockTransport(handler),
    )
    assert result["ok"] is False
    assert "400" in result["error"]


async def test_provider_local_and_country_metadata(client, auth_headers):
    created = await client.post(
        "/api/v1/ai/providers",
        json={
            "name": "Home Ollama",
            "provider_type": "openai_compatible",
            "api_base": "http://localhost:11434/v1",
            "scope": "user",
            "is_local": True,
            "country": "DE",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["is_local"] is True
    assert body["country"] == "DE"

    updated = await client.put(
        f"/api/v1/ai/providers/{body['id']}",
        json={"is_local": False, "country": "NL"},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_local"] is False
    assert updated.json()["country"] == "NL"

    listed = (await client.get("/api/v1/ai/providers", headers=auth_headers)).json()
    row = next(p for p in listed if p["name"] == "Home Ollama")
    assert row["is_local"] is False
    assert row["country"] == "NL"


async def test_fetch_external_models_google_catalog(client, auth_headers, monkeypatch):
    """Native google providers discover via the google-genai SDK — only
    generateContent-capable models are offered, ids drop the models/
    prefix, and the payload shape matches the OpenAI branch."""

    class _FakeModel:
        def __init__(self, name, display_name, methods):
            self.name = name
            self.display_name = display_name
            self.supported_actions = methods

    class _FakePager:
        def __init__(self, items):
            self._items = items

        def __aiter__(self):
            return self._agen()

        async def _agen(self):
            for item in self._items:
                yield item

    class _FakeAioModels:
        async def list(self):
            return _FakePager(
                [
                    _FakeModel(
                        "models/gemini-2.5-flash",
                        "Gemini 2.5 Flash",
                        ["generateContent"],
                    ),
                    _FakeModel(
                        "models/gemini-embedding-001",
                        "Embedding",
                        ["embedContent"],
                    ),
                ]
            )

    class _FakeAio:
        models = _FakeAioModels()

    class _FakeClient:
        def __init__(self, api_key=None, http_options=None):
            self.api_key = api_key
            self.aio = _FakeAio()

    import google.genai.client as genai_client_module

    monkeypatch.setattr(genai_client_module, "Client", _FakeClient)

    created = await client.post(
        "/api/v1/ai/providers",
        json={
            "name": "Native Gemini",
            "provider_type": "google",
            "api_base": "https://generativelanguage.googleapis.com",
            "api_key": "g-key",
            "scope": "user",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    provider_id = created.json()["id"]

    response = await client.get(
        f"/api/v1/ai/providers/{provider_id}/fetch-external-models",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    items = response.json()
    assert items == [
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "owned_by": "google"}
    ], "embedding models are filtered and the models/ prefix is stripped"


def test_google_sdk_model_field_contract():
    """The discovery branch reads ``Model.supported_actions`` — pin the
    installed google-genai field so a rename surfaces here, not in
    production (it already bit once: the legacy SDK called it
    ``supported_generation_methods``)."""
    from google.genai import types

    assert "supported_actions" in types.Model.model_fields
