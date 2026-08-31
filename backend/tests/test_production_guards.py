import pytest

from app.ai.provider import AINotConfiguredError
from app.ai.providers.resolution import resolve_task_model
from app.ai.providers.service import AIProviderService
from app.core.boot import BootConfigError, validate_boot_config
from app.core.config import settings
from app.core.errors import ValidationError


def _production(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")


def test_boot_guard_allows_dev_and_test():
    assert validate_boot_config() == []


def test_boot_guard_rejects_weak_jwt_secret(monkeypatch):
    _production(monkeypatch)
    monkeypatch.setattr(settings, "JWT_SECRET", "dev-only-change-me")
    monkeypatch.setattr(settings, "DEBUG", False)
    with pytest.raises(BootConfigError, match="JWT_SECRET"):
        validate_boot_config()


def test_boot_guard_rejects_debug_in_production(monkeypatch):
    _production(monkeypatch)
    monkeypatch.setattr(settings, "JWT_SECRET", settings.JWT_SECRET)
    monkeypatch.setattr(settings, "DEBUG", True)
    with pytest.raises(BootConfigError, match="DEBUG"):
        validate_boot_config()


def test_boot_guard_valid_production_config(monkeypatch):
    _production(monkeypatch)
    monkeypatch.setattr(settings, "JWT_SECRET", "x" * 40)
    monkeypatch.setattr(settings, "DEBUG", False)
    assert validate_boot_config() == []


async def test_production_without_providers_resolves_to_none(db, monkeypatch):
    _production(monkeypatch)
    assert await resolve_task_model(db, "match_score") is None


async def test_dev_bootstraps_mock_provider_automatically(
    db, monkeypatch, seeded_catalog
):
    assert settings.is_dev
    resolved = await resolve_task_model(db, "match_score")
    assert resolved is not None
    assert resolved.provider_type == "mock"
    assert resolved.model_name == "mock-large"
    assert "dev bootstrap" in resolved.source


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
