import pytest

from app.ai.gateway import AINotConfiguredError
from app.ai.providers.resolution import resolve_task_model
from app.ai.providers.service import AIProviderService
from app.core.boot import BootConfigError, validate_boot_config
from app.core.config import settings
from app.core.errors import ValidationError


def _production(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")


def _pin_keys(monkeypatch, session: str | None, refresh: str | None, data: str | None):
    monkeypatch.setattr(settings, "SESSION_KEY", session)
    monkeypatch.setattr(settings, "REFRESH_KEY", refresh)
    monkeypatch.setattr(settings, "DATA_KEY", data)


_STRONG = {
    "session": "s" + "0123456789abcdef" * 3,
    "refresh": "r" + "0123456789abcdef" * 3,
    "data": "Y2FyZWVyLXNhbXBsZS1kYXRhLWtleS0zMmJ5dGVzISE=",
}


def test_boot_guard_allows_dev_and_test():
    assert validate_boot_config() == []


def test_boot_guard_rejects_weak_pinned_keys(monkeypatch):
    for name, index in (
        ("CAREER_SESSION_KEY", 0),
        ("CAREER_REFRESH_KEY", 1),
        ("CAREER_DATA_KEY", 2),
    ):
        _production(monkeypatch)
        values = [_STRONG["session"], _STRONG["refresh"], _STRONG["data"]]
        values[index] = "dev-only-change-me"
        _pin_keys(monkeypatch, *values)
        monkeypatch.setattr(settings, "DEBUG", False)
        with pytest.raises(BootConfigError, match=name):
            validate_boot_config()


def test_boot_guard_rejects_short_pinned_keys(monkeypatch):
    _production(monkeypatch)
    _pin_keys(monkeypatch, "short", _STRONG["refresh"], _STRONG["data"])
    monkeypatch.setattr(settings, "DEBUG", False)
    with pytest.raises(BootConfigError, match="CAREER_SESSION_KEY"):
        validate_boot_config()


def test_boot_guard_rejects_committed_test_fixture_keys(monkeypatch):
    """The .env.test / ci.yml fixture keys are public (committed) — a
    production boot pinned to them must be refused (identity-auth §8)."""
    _production(monkeypatch)
    monkeypatch.setattr(settings, "DEBUG", False)
    for value in (
        "test-session-key-0123456789abcdefghijklmnopqrstuv",
        "test-refresh-key-0123456789abcdefghijklmnopqrstuv",
        "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY",
    ):
        _pin_keys(monkeypatch, value, value, value)
        with pytest.raises(BootConfigError, match="known dev/test value"):
            validate_boot_config()


def test_boot_guard_rejects_partial_key_pin(monkeypatch):
    _production(monkeypatch)
    _pin_keys(monkeypatch, _STRONG["session"], None, _STRONG["data"])
    monkeypatch.setattr(settings, "DEBUG", False)
    with pytest.raises(BootConfigError, match="CAREER_REFRESH_KEY is missing"):
        validate_boot_config()


def test_boot_guard_rejects_unusable_data_key(monkeypatch):
    """DATA_KEY must be 32-byte urlsafe-base64 Fernet material (§8)."""
    _production(monkeypatch)
    _pin_keys(monkeypatch, _STRONG["session"], _STRONG["refresh"], "z" * 48)
    monkeypatch.setattr(settings, "DEBUG", False)
    with pytest.raises(BootConfigError, match="must be usable Fernet"):
        validate_boot_config()


def test_boot_guard_rejects_duplicate_keys(monkeypatch):
    _production(monkeypatch)
    _pin_keys(monkeypatch, _STRONG["session"], _STRONG["session"], _STRONG["data"])
    monkeypatch.setattr(settings, "DEBUG", False)
    with pytest.raises(BootConfigError, match="distinct"):
        validate_boot_config()


def test_boot_guard_refuses_missing_keys_on_production_server(monkeypatch):
    """§8 server posture: env/DB-config keys or nothing — a server never
    silently generates its key material."""
    _production(monkeypatch)
    monkeypatch.setattr(settings, "IDENTITY_MODE", "server")
    _pin_keys(monkeypatch, None, None, None)
    monkeypatch.setattr(settings, "DEBUG", False)
    with pytest.raises(BootConfigError, match="missing"):
        validate_boot_config()


def test_boot_guard_allows_generated_keys_on_desktop(monkeypatch):
    """§8 desktop posture: keyring-or-0600-file — the generated
    auth_keys.json is the documented desktop key source."""
    _production(monkeypatch)
    monkeypatch.setattr(settings, "IDENTITY_MODE", "desktop")
    _pin_keys(monkeypatch, None, None, None)
    monkeypatch.setattr(settings, "DEBUG", False)
    warnings = validate_boot_config()
    assert any("auth_keys.json" in warning for warning in warnings)


def test_boot_guard_rejects_debug_in_production(monkeypatch):
    _production(monkeypatch)
    _pin_keys(monkeypatch, _STRONG["session"], _STRONG["refresh"], _STRONG["data"])
    monkeypatch.setattr(settings, "DEBUG", True)
    with pytest.raises(BootConfigError, match="DEBUG"):
        validate_boot_config()


def test_boot_guard_valid_production_config(monkeypatch):
    _production(monkeypatch)
    monkeypatch.setattr(settings, "IDENTITY_MODE", "server")
    _pin_keys(monkeypatch, _STRONG["session"], _STRONG["refresh"], _STRONG["data"])
    monkeypatch.setattr(settings, "DEBUG", False)
    assert validate_boot_config() == []


async def test_production_without_providers_resolves_to_none(db, monkeypatch):
    _production(monkeypatch)
    assert await resolve_task_model(db, "match_score") is None


async def test_dev_without_mock_optin_resolves_to_none(db, monkeypatch):
    """MOCK_AI is off by default: dev AI stays unconfigured (503 path)."""
    monkeypatch.setattr(settings, "MOCK_AI", False)
    assert settings.is_dev
    assert await resolve_task_model(db, "match_score") is None


async def test_dev_mock_optin_bootstraps_mock_provider(db, monkeypatch, seeded_catalog):
    """MOCK_AI=1 restores the offline dev experience (run-dev.sh --mock-ai)."""
    monkeypatch.setattr(settings, "MOCK_AI", True)
    assert settings.is_dev
    resolved = await resolve_task_model(db, "match_score")
    assert resolved is not None
    assert resolved.provider_type == "mock"
    assert resolved.model_name == "mock-large"
    assert "dev bootstrap" in resolved.source


async def test_dev_mock_optin_hides_seeded_mock_rows(db, monkeypatch):
    """With MOCK_AI off, already-seeded mock rows are invisible to resolution."""
    monkeypatch.setattr(settings, "MOCK_AI", True)
    assert await resolve_task_model(db, "match_score") is not None
    monkeypatch.setattr(settings, "MOCK_AI", False)
    assert await resolve_task_model(db, "match_score") is None


async def test_production_ai_call_returns_503(
    client, auth_headers, profile_ready, seeded_catalog, monkeypatch
):
    job = (
        await client.get("/api/v1/jobs/software-developer", headers=auth_headers)
    ).json()
    _production(monkeypatch)
    response = await client.post(
        "/api/v1/match/score", json={"job_id": job["id"]}, headers=auth_headers
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()


async def test_ai_service_direct_invocation_raises_when_unconfigured(
    db, client, auth_headers, seeded_catalog, monkeypatch
):
    from app.ai.agents import score_match
    from app.services.job_service import JobService

    _production(monkeypatch)
    job = await JobService(db).require_job("nurse")
    with pytest.raises(AINotConfiguredError):
        await score_match(db, None, {}, JobService.job_snapshot(job))


async def test_cannot_create_mock_provider_in_production(
    client, auth_headers, monkeypatch
):
    _production(monkeypatch)
    response = await client.post(
        "/api/v1/ai/providers",
        json={"name": "Mock", "provider_type": "mock", "scope": "user"},
        headers=auth_headers,
    )
    assert response.status_code in (400, 403)
    assert "development" in response.json()["detail"]


async def test_cannot_switch_provider_to_mock_in_production(
    client, auth_headers, monkeypatch
):
    created = await client.post(
        "/api/v1/ai/providers",
        json={
            "name": "Real",
            "provider_type": "openai",
            "api_key": "sk-1",
            "scope": "user",
        },
        headers=auth_headers,
    )
    _production(monkeypatch)
    updated = await client.put(
        f"/api/v1/ai/providers/{created.json()['id']}",
        json={"provider_type": "mock"},
        headers=auth_headers,
    )
    assert updated.status_code == 400
    assert "development" in updated.json()["detail"]


def test_mock_provider_type_rejected_in_production(monkeypatch):
    from app.ai.providers.service import _validate_provider_type

    _production(monkeypatch)
    with pytest.raises(ValidationError, match="development"):
        _validate_provider_type("mock")
    assert _validate_provider_type("openai") == "openai"


async def test_existing_mock_provider_still_resolves_in_dev(
    db, client, auth_headers, seeded_catalog
):
    user = await _user(db, "student@example.com")
    resolved = await resolve_task_model(db, "match_score", user.id)
    assert resolved is not None and resolved.provider_type == "mock"

    service = AIProviderService(db)
    providers = await service.list_providers(user)
    assert providers
    external = await service.fetch_external_models(providers[0].id, user)
    assert external[0]["id"] == "mock-large"


async def _user(db, email):
    from sqlalchemy import select

    from app.models.user_model import User

    return (await db.execute(select(User).where(User.email == email))).scalars().first()
