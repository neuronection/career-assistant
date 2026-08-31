"""Security hardening: rate limits, lockout, token revocation, headers."""

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.ratelimit import SlidingWindowRateLimiter, client_identity
from app.models.user_model import User
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _reset_limiter_state():
    from app.core import ratelimit

    ratelimit.limiter._events.clear()
    yield
    ratelimit.limiter._events.clear()


async def _register(
    client: AsyncClient, email="student@example.com", password="supersecret1"
):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "T"},
    )


def test_sliding_window_allows_then_blocks(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 3)
    limiter = SlidingWindowRateLimiter()
    for _ in range(3):
        assert limiter.check("auth", "1.2.3.4") is None
    retry = limiter.check("auth", "1.2.3.4")
    assert retry is not None and retry >= 1
    assert limiter.check("auth", "5.6.7.8") is None


def test_sliding_window_zero_limit_disables_bucket(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 0)
    limiter = SlidingWindowRateLimiter()
    for _ in range(10):
        assert limiter.check("auth", "1.2.3.4") is None


def _scope(headers=None, client=("9.9.9.9", 1234)):
    raw = [(k.encode(), v.encode()) for k, v in (headers or {}).items()]
    return {"client": client, "headers": raw}


def test_client_identity_uses_rightmost_forwarded_hop():
    scope = _scope({"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 203.0.113.9"})
    assert client_identity(scope) == "203.0.113.9"


def test_client_identity_ignores_spoofable_leading_hops():
    scope = _scope({"X-Forwarded-For": "1.1.1.1"}, client=("203.0.113.9", 5))
    assert client_identity(scope) == "1.1.1.1"
    scope = _scope({"X-Forwarded-For": "1.1.1.1, 203.0.113.9"}, client=None)
    assert client_identity(scope) == "203.0.113.9"


def test_client_identity_falls_back_to_socket_address():
    assert client_identity(_scope()) == "9.9.9.9"
    assert client_identity({"headers": [], "client": None}) == "unknown"


async def test_login_rate_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 3)
    for _ in range(3):
        await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrong"},
        )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrong"},
    )
    assert response.status_code == 429
    assert "retry-after" in {k.lower() for k in response.headers}


async def test_disabled_limiter_lets_requests_through(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    for _ in range(30):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrong"},
        )
        assert response.status_code == 401


async def test_lockout_after_threshold_then_expiry(
    client, auth_headers, db, monkeypatch
):
    monkeypatch.setattr(settings, "LOCKOUT_THRESHOLD", 3)
    monkeypatch.setattr(settings, "LOCKOUT_MINUTES", 15)
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    email = me["email"]

    for _ in range(3):
        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong-pass"}
        )
        assert response.status_code == 401

    locked = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "supersecret1"},
    )
    assert locked.status_code == 423

    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    user.locked_until = None
    await db.commit()

    ok = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "supersecret1"}
    )
    assert ok.status_code == 200


async def test_successful_login_resets_failure_counter(client, auth_headers, db):
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    email = me["email"]
    for _ in range(2):
        await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong-pass"}
        )
    ok = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "supersecret1"}
    )
    assert ok.status_code == 200
    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


async def test_revoke_sessions_invalidates_old_token(client, auth_headers, db):
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    user = (
        (await db.execute(select(User).where(User.email == me["email"])))
        .scalars()
        .first()
    )
    old_version = user.token_version

    revoked = await client.post("/api/v1/auth/revoke-sessions", headers=auth_headers)
    assert revoked.status_code == 200
    assert revoked.json()["token_version"] == old_version + 1

    stale = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert stale.status_code == 401


async def test_security_headers_present(client):
    response = await client.get("/health")
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


async def test_web_csp_stays_strict(client):
    """No eval anywhere on the web deployment — even with a shell-shaped query."""
    from app.desktop import shell_token

    shell_token.issue()
    try:
        for query in ("", "?shell=not-the-token"):
            response = await client.get(f"/health{query}")
            csp = response.headers["content-security-policy"]
            assert "script-src 'self';" in csp
            assert "unsafe-eval" not in csp
    finally:
        shell_token.reset()


async def test_desktop_shell_query_gets_eval_csp(client):
    """The per-boot shell token unlocks the desktop CSP variant; old tokens
    die with the next issue() (token rotates per boot)."""
    from app.desktop import shell_token

    token = shell_token.issue()
    try:
        response = await client.get(f"/health?shell={token}")
        csp = response.headers["content-security-policy"]
        assert "script-src 'self' 'unsafe-eval';" in csp

        rotated = shell_token.issue()
        stale = await client.get(f"/health?shell={token}")
        assert "unsafe-eval" not in stale.headers["content-security-policy"]

        fresh = await client.get(f"/health?shell={rotated}")
        assert "unsafe-eval" in fresh.headers["content-security-policy"]
    finally:
        shell_token.reset()


async def test_password_minimum_length_enforced(client):
    response = await _register(client, "shortpw@example.com", "short12")
    assert response.status_code == 422


async def test_ai_rate_limit_per_user(monkeypatch):
    monkeypatch.setattr(settings, "AI_RATE_LIMIT", 2)
    from app.ai import provider
    from app.core import ratelimit
    from app.core.errors import DomainError
    from app.models.enums import AITaskType

    uid = "11111111-1111-1111-1111-111111111111"
    for _ in range(2):
        assert ratelimit.limiter.check("ai", f"user:{uid}") is None

    with pytest.raises(DomainError, match="rate limit"):
        await provider.ainvoke_structured(
            None, AITaskType.ASSIST, dict, "sys", "usr", user_id=uid
        )
