"""Admin /ai/web settings + the family web-search providers surface
(plan 28 / ADR-0035) — probe statuses, Fernet token, secret-safety."""

import httpx
import pytest

from app.core.encryption import decrypt_secret
from app.services import webfetch
from tests.conftest import session_headers


class _AlwaysErrorClient:
    is_closed = False

    async def get(self, *_a, **_k):
        raise httpx.ConnectError("down")


@pytest.fixture(autouse=True)
def _probe_isolated(monkeypatch):
    monkeypatch.setattr(webfetch, "_probe_cache", {})
    yield


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """The probe never leaves the test process."""
    monkeypatch.setattr(webfetch, "_client", lambda: _AlwaysErrorClient())
    yield


async def _get(client, headers):
    return await client.get("/api/v1/ai/web", headers=headers)


async def _put(client, headers, payload):
    return await client.put("/api/v1/ai/web", headers=headers, json=payload)


async def _providers(client, headers):
    return await client.get("/api/v1/ai/web/search-providers", headers=headers)


@pytest.mark.asyncio
async def test_requires_admin(client):
    async def _headers(email: str) -> dict:
        register = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "password123"},
        )
        assert register.status_code == 201
        return session_headers(register)

    admin = await _headers("chief1@example.com")
    member = await _headers("member1@example.com")

    anon = await client.get("/api/v1/ai/web")
    assert anon.status_code == 401, anon.text
    plain = await _get(client, member)
    assert plain.status_code == 403, plain.text
    admin_status = await _get(client, admin)
    assert admin_status.status_code == 200

    anon_providers = await client.get("/api/v1/ai/web/search-providers")
    assert anon_providers.status_code == 401
    member_providers = await _providers(client, member)
    assert member_providers.status_code == 403


@pytest.mark.asyncio
async def test_web_reports_github_token_state_only(client, client_admin_headers):
    headers = client_admin_headers
    empty = (await _get(client, headers)).json()
    assert empty == {"github_token_set": False}


@pytest.mark.asyncio
async def test_token_is_encrypted_and_cleared(client, db, client_admin_headers):
    from sqlalchemy import select

    from app.models.settings_model import AppSetting

    headers = client_admin_headers
    sealed = (await _put(client, headers, {"github_token": "gh_pat_value"})).json()
    assert sealed["github_token_set"] is True
    assert "gh_pat_value" not in str(sealed)

    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == "web.github_token")))
        .scalars()
        .first()
    )
    stored = (row.value or {}).get("token") or ""
    assert "gh_pat_value" not in stored
    assert decrypt_secret(stored) == "gh_pat_value"

    cleared_token = (await _put(client, headers, {"github_token": ""})).json()
    assert cleared_token["github_token_set"] is False


@pytest.mark.asyncio
async def test_search_providers_crud_roundtrip(client, db, client_admin_headers):
    from sqlalchemy import select

    from app.models.settings_model import AppSetting

    headers = client_admin_headers

    empty = await _providers(client, headers)
    assert empty.status_code == 200
    assert empty.json() == {"providers": []}

    created = await client.post(
        "/api/v1/ai/web/search-providers",
        headers=headers,
        json={
            "type": "searxng",
            "name": "Campus SearXNG",
            "base_url": "https://searx.example.org/",
        },
    )
    assert created.status_code == 201, created.text
    provider = created.json()
    assert provider["id"] == "legacy" or len(provider["id"]) == 8
    assert provider["base_url"] == "https://searx.example.org"
    assert provider["enabled"] is True
    assert provider["key_set"] is False

    # the legacy single-URL value migrates away once providers exist
    legacy_row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == "web.searxng_url")))
        .scalars()
        .first()
    )
    assert legacy_row is None or not (legacy_row.value or {}).get("url")

    second = await client.post(
        "/api/v1/ai/web/search-providers",
        headers=headers,
        json={
            "type": "searxng",
            "name": "Backup SearXNG",
            "base_url": "https://backup.example.org",
        },
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]

    moved = await client.post(
        f"/api/v1/ai/web/search-providers/{second_id}/move",
        headers=headers,
        json={"direction": "up"},
    )
    assert moved.status_code == 200, moved.text
    assert [entry["id"] for entry in moved.json()["providers"]] == [second_id, provider["id"]]

    removed = await client.delete(f"/api/v1/ai/web/search-providers/{second_id}", headers=headers)
    assert removed.status_code == 204
    remaining = (await _providers(client, headers)).json()["providers"]
    assert [entry["id"] for entry in remaining] == [provider["id"]]

    catalog = await client.get("/api/v1/ai/web/search-providers/catalog", headers=headers)
    assert catalog.status_code == 200
    assert "searxng" in catalog.json()["providers"]


@pytest.mark.asyncio
async def test_search_providers_reject_bad_input(client, client_admin_headers):
    headers = client_admin_headers
    unknown_type = await client.post(
        "/api/v1/ai/web/search-providers",
        headers=headers,
        json={"type": "tavily", "base_url": "https://api.tavily.com", "api_key": "k"},
    )
    # keyed POST providers wait for guarded adapters (career Phase 4 note)
    assert unknown_type.status_code == 422
    missing_base = await client.post(
        "/api/v1/ai/web/search-providers", headers=headers, json={"type": "searxng"}
    )
    assert missing_base.status_code == 422
    bad_url = await client.post(
        "/api/v1/ai/web/search-providers",
        headers=headers,
        json={"type": "searxng", "base_url": "searx.example.org"},
    )
    assert bad_url.status_code == 422
    unknown = await client.put(
        "/api/v1/ai/web/search-providers/nope", headers=headers, json={"name": "x"}
    )
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_legacy_searxng_url_migrates_to_providers(client, db, client_admin_headers):
    from sqlalchemy import select

    from app.models.settings_model import AppSetting
    from app.services.search_providers import list_providers

    db.add(
        AppSetting(
            key="web.searxng_url",
            value={"url": "https://searx.example"},
        )
    )
    await db.commit()

    providers = await list_providers(db)
    assert len(providers) == 1
    assert providers[0]["id"] == "legacy"
    assert providers[0]["type"] == "searxng"
    assert providers[0]["base_url"] == "https://searx.example"
    assert providers[0]["enabled"] is True

    legacy_row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == "web.searxng_url")))
        .scalars()
        .first()
    )
    assert legacy_row is None or not (legacy_row.value or {}).get("url")

    via_api = (await _providers(client, client_admin_headers)).json()["providers"]
    assert [entry["id"] for entry in via_api] == ["legacy"]
