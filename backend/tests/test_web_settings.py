"""Admin /ai/web settings — probe statuses, Fernet token, secret-safety."""

import httpx
import pytest

from app.core.encryption import decrypt_secret
from app.services import webfetch


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


@pytest.mark.asyncio
async def test_requires_admin(client, multi_user_mode):
    async def _headers(email: str) -> dict:
        register = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "password123"},
        )
        assert register.status_code == 201
        return {"Authorization": f"Bearer {register.json()['access_token']}"}

    admin = await _headers("chief1@example.com")
    member = await _headers("member1@example.com")

    anon = await client.get("/api/v1/ai/web")
    assert anon.status_code == 401, anon.text
    plain = await _get(client, member)
    assert plain.status_code == 403, plain.text
    admin_status = await _get(client, admin)
    assert admin_status.status_code == 200


@pytest.mark.asyncio
async def test_report_states_before_and_after_config(client, client_admin_headers):
    headers = client_admin_headers

    empty = (await _get(client, headers)).json()
    assert empty["searxng_url"] == ""
    assert empty["searxng_probe"]["status"] == "unconfigured"
    assert empty["github_token_set"] is False

    unreachable = (
        await _put(client, headers, {"searxng_url": "https://nope.invalid/sx"})
    ).json()
    assert unreachable["searxng_probe"]["status"] == "unreachable"

    cleared = (await _put(client, headers, {"searxng_url": ""})).json()
    assert cleared["searxng_url"] == ""
    assert cleared["searxng_probe"]["status"] == "unconfigured"


@pytest.mark.asyncio
async def test_token_is_encrypted_and_cleared(client, db, client_admin_headers):
    from sqlalchemy import select

    from app.models.settings_model import AppSetting

    headers = client_admin_headers
    sealed = (await _put(client, headers, {"github_token": "gh_pat_value"})).json()
    assert sealed["github_token_set"] is True
    assert "gh_pat_value" not in str(sealed)

    row = (
        (
            await db.execute(
                select(AppSetting).where(AppSetting.key == "web.github_token")
            )
        )
        .scalars()
        .first()
    )
    stored = (row.value or {}).get("token") or ""
    assert "gh_pat_value" not in stored
    assert decrypt_secret(stored) == "gh_pat_value"

    cleared_token = (await _put(client, headers, {"github_token": ""})).json()
    assert cleared_token["github_token_set"] is False
