"""Auth contract through the real app (identity-auth §7/§8/§10/§12).

Kit-contract-style coverage for plan 16 P3a (replaces the pre-kit token
tests): register/login/refresh rotation + reuse detection/logout/
logout-all/me, lockout, cookie flags, double-submit CSRF, token claims
and key separation, inactive-user rejection, and the generic login
error. Instance modes / DIM / shell-secret gate live in
`test_instance_modes.py`; admin guard rails in `test_admin.py`.
"""

from dataclasses import replace
from datetime import UTC

import pytest

from tests.conftest import (
    auth_kit,
    mint_session_headers,
    register_user,
    session_headers,
    user_id_from_headers,
)

PASSWORD = "supersecret1"


def _refresh_headers(cookie_value: str) -> dict:
    """Refresh probe headers: the raw cookie under test plus a CSRF pair
    (cookie-bearing non-GET echoes nx_csrf — §10 applies to refresh too)."""
    csrf = "test-csrf-token"
    return {
        "Cookie": f"nx_refresh={cookie_value}; nx_csrf={csrf}",
        "X-CSRF-Token": csrf,
    }


# ---------------------------------------------------------------- register


async def test_register_returns_public_user_and_session_cookies(client, db):
    from sqlalchemy import select

    from app.models.identity_model import AuthSession
    from app.models.user_model import Profile, User

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@example.com",
            "password": PASSWORD,
            "full_name": "New User",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"id", "email", "full_name", "is_admin", "is_active"}
    assert body["email"] == "new@example.com"
    assert body["is_admin"] is True, "the first user is the instance admin (§12)"

    user_id = body["id"]
    assert (await db.execute(select(User).where(User.id == user_id))).scalars().first()
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id))).scalars().first()
    )
    assert profile is not None, "Default profile auto-provisioned on registration (§6)"
    families = (
        (await db.execute(select(AuthSession).where(AuthSession.user_id == user_id)))
        .scalars()
        .all()
    )
    assert len(families) == 1, "register opens one refresh family"


async def test_register_duplicate_email_conflicts(client):
    body = {"email": "dup@example.com", "password": PASSWORD}
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 201
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 409


async def test_register_enforces_password_policy(client):
    response = await client.post(
        "/api/v1/auth/register", json={"email": "x@example.com", "password": "short"}
    )
    assert response.status_code == 422


async def test_register_second_user_is_not_admin(client):
    await register_user(client, "admin@example.com", PASSWORD)
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "member@example.com", "password": PASSWORD},
    )
    assert second.status_code == 201
    assert second.json()["is_admin"] is False


async def test_register_can_be_disabled(client):
    kit = auth_kit()
    kit.config = replace(kit.config, registration_enabled=False)
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "nope@example.com", "password": PASSWORD},
    )
    assert response.status_code == 403


async def test_registration_env_var_reaches_the_register_route(monkeypatch):
    """§16 end-to-end: `CAREER_REGISTRATION_ENABLED=false` in the process
    environment ⇒ the installed kit config disables registration and the
    register route refuses with 403. Nothing is re-implemented here — the
    real `_install_identity` builds the config from `Settings`."""
    import httpx
    from fastapi import FastAPI

    import app.auth.install as install_module
    from app.core.config import Settings

    monkeypatch.setenv("CAREER_REGISTRATION_ENABLED", "false")

    app = FastAPI()
    install_module.install_identity(app, Settings())
    assert app.state.auth.config.registration_enabled is False

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as anon:
        response = await anon.post(
            "/api/v1/auth/register",
            json={"email": "nope@example.com", "password": PASSWORD},
        )
    assert response.status_code == 403, response.text


async def test_registration_flag_reads_the_dotenv_file_too(monkeypatch, tmp_path):
    """The same flag must work from the deployment `.env` file (docs tell
    operators to set it there) — OS environment variables override the
    file, but the file alone has to reach the kit config."""
    from fastapi import FastAPI

    import app.auth.install as install_module
    from app.core.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text("CAREER_REGISTRATION_ENABLED=false\n")
    monkeypatch.delenv("CAREER_REGISTRATION_ENABLED", raising=False)

    app = FastAPI()
    install_module.install_identity(app, Settings(_env_file=str(env_file)))
    assert app.state.auth.config.registration_enabled is False


# ------------------------------------------------------------------- login


async def test_login_sets_session_cookies(client):
    await register_user(client, "login@example.com", PASSWORD)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    headers = session_headers(response)
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "login@example.com"


@pytest.mark.contract  # §18.10 — generic login error, no user enumeration
async def test_login_failures_are_generic(client):
    await register_user(client, "known@example.com", PASSWORD)
    wrong_password = await client.post(
        "/api/v1/auth/login",
        json={"email": "known@example.com", "password": "wrong-pass1"},
    )
    unknown_user = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": "wrong-pass1"},
    )
    assert wrong_password.status_code == 401
    assert unknown_user.status_code == 401
    # §7: identical generic errors — no user enumeration.
    assert wrong_password.json() == unknown_user.json()
    assert wrong_password.json()["detail"] == "Invalid email or password"


async def test_me_requires_session(client, auth_headers):
    anonymous = await client.get("/api/v1/auth/me")
    assert anonymous.status_code == 401
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert me.status_code == 200
    assert set(me.json()) == {"id", "email", "full_name", "is_admin", "is_active"}
    assert me.json()["id"] == user_id_from_headers(auth_headers)


@pytest.mark.contract  # §18.4 — lockout after N failures ⇒ 423
async def test_lockout_after_threshold(client, db):
    from datetime import datetime

    from sqlalchemy import select

    from app.models.user_model import User

    kit = auth_kit()
    kit.config = replace(kit.config, lockout_threshold=3, lockout_minutes=15)
    await register_user(client, "lockout@example.com", PASSWORD)

    for _ in range(2):
        failed = await client.post(
            "/api/v1/auth/login",
            json={"email": "lockout@example.com", "password": "wrong-pass1"},
        )
        assert failed.status_code == 401
    # The failure that crosses the threshold reports the lock (§7).
    locking = await client.post(
        "/api/v1/auth/login",
        json={"email": "lockout@example.com", "password": "wrong-pass1"},
    )
    assert locking.status_code == 423
    locked = await client.post(
        "/api/v1/auth/login",
        json={"email": "lockout@example.com", "password": PASSWORD},
    )
    assert locked.status_code == 423

    user = (
        (await db.execute(select(User).where(User.email == "lockout@example.com"))).scalars().one()
    )
    assert user.locked_until is not None

    # Lock window elapsed (§7 unlocks after LOCKOUT_MINUTES) — the next
    # successful login resets the counters.
    kit.users.set_login_failures(user.id, 2, datetime.now(UTC))
    recovered = await client.post(
        "/api/v1/auth/login",
        json={"email": "lockout@example.com", "password": PASSWORD},
    )
    assert recovered.status_code == 200
    db.expire_all()
    user = (
        (await db.execute(select(User).where(User.email == "lockout@example.com"))).scalars().one()
    )
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


async def test_failed_login_counts_failures(client, db):
    await register_user(client, "reset@example.com", PASSWORD)
    for _ in range(2):
        await client.post(
            "/api/v1/auth/login",
            json={"email": "reset@example.com", "password": "wrong-pass1"},
        )
    from sqlalchemy import select

    from app.models.user_model import User

    user = (await db.execute(select(User).where(User.email == "reset@example.com"))).scalars().one()
    assert user.failed_login_attempts == 2


# -------------------------------------------------------- cookies & CSRF §10


@pytest.mark.contract  # §18.5 — cookie flags exactly as §10
async def test_cookie_flags_are_exact(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "flags@example.com", "password": PASSWORD},
    )
    from nx_auth.testing import assert_cookie_flags

    lines = response.headers.get_list("set-cookie")
    assert_cookie_flags(lines, "nx_access", http_only=True, secure=False, path="/")
    assert_cookie_flags(lines, "nx_refresh", http_only=True, secure=False, path="/api/v1/auth")
    assert_cookie_flags(lines, "nx_csrf", http_only=False, secure=False, path="/")
    same_site = next(ln for ln in lines if ln.startswith("nx_access="))
    assert "samesite=lax" in same_site.lower()


@pytest.mark.contract  # §18.5 — CSRF enforced on cookie-authenticated POSTs
async def test_csrf_enforced_on_cookie_posts(client, auth_headers):
    """Double-submit: cookie-authenticated non-GET must echo nx_csrf."""
    cookie_only = {"Cookie": auth_headers["Cookie"]}
    missing = await client.post("/api/v1/auth/logout", headers=cookie_only)
    assert missing.status_code == 403

    mismatched = {
        "Cookie": auth_headers["Cookie"],
        "X-CSRF-Token": "not-the-cookie",
    }
    assert (await client.post("/api/v1/auth/logout", headers=mismatched)).status_code == 403

    good = await client.post("/api/v1/auth/logout", headers=auth_headers)
    assert good.status_code == 200


async def test_csrf_does_not_apply_without_cookies(client):
    # Cookie-less requests (login/register/exchange, bearer clients) are
    # not cookie-authenticated — CSRF does not gate them.
    response = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert response.status_code == 401


# ------------------------------------------------------------- tokens (§8)


async def _session_cookie(client, email: str) -> dict:
    registered = await register_user(client, email, PASSWORD)
    return {"Cookie": registered["Cookie"], "X-CSRF-Token": registered["X-CSRF-Token"]}


def _access_token(headers: dict) -> str:
    return headers["Cookie"].split("nx_access=", 1)[1].split(";", 1)[0]


def _refresh_cookie(response) -> str | None:
    for line in response.headers.get_list("set-cookie"):
        if line.startswith("nx_refresh="):
            return line.split("=", 1)[1].split(";", 1)[0]
    return None


@pytest.mark.contract  # §18.1 — forged / wrong-key / garbage tokens rejected
async def test_forged_and_wrong_key_tokens_rejected(client, auth_headers):
    from nx_auth.testing import forge_token

    real = _access_token(auth_headers)
    assert (await client.get("/api/v1/auth/me", headers=auth_headers)).status_code == 200

    forged = forge_token(
        "wrong-key-0123456789abcdefghijklmnop",
        {"sub": user_id_from_headers(auth_headers)},
    )
    probe = {"Cookie": f"nx_access={forged}"}
    assert (await client.get("/api/v1/auth/me", headers=probe)).status_code == 401

    garbage = {"Cookie": "nx_access=not-a-jwt"}
    assert (await client.get("/api/v1/auth/me", headers=garbage)).status_code == 401
    assert real  # the real one verified above


@pytest.mark.contract  # §18.1 + §18.12 — kind mismatch; per-kind key separation
async def test_kind_mismatch_and_key_separation(client, auth_headers):
    """§18.1/§18.12: a refresh token presented as a session token is
    rejected; each kind verifies only under its own key."""
    from nx_auth.tokens import AuthMode, TokenError, TokenKind, mint_token, verify_token

    kit = auth_kit()
    sub = user_id_from_headers(auth_headers)
    refresh_as_access = mint_token(
        kit.ring,
        kit.config,
        kind=TokenKind.REFRESH,
        sub=sub,
        ver=1,
        auth_mode=AuthMode.PASSWORD,
    )
    assert (
        await client.get("/api/v1/auth/me", headers={"Cookie": f"nx_access={refresh_as_access}"})
    ).status_code == 401

    # A refresh token signed with the SESSION key must not verify as a
    # refresh token (key separation).
    wrong_key = mint_token(
        kit.ring,
        kit.config,
        kind=TokenKind.REFRESH,
        sub=sub,
        ver=1,
        auth_mode=AuthMode.PASSWORD,
        key=kit.ring.session_key,
    )
    with pytest.raises(TokenError):
        verify_token(kit.ring, kit.config, kind=TokenKind.REFRESH, token=wrong_key)

    # The DATA key signs nothing and decrypts no JWTs.
    session_token = _access_token(auth_headers)
    with pytest.raises(TokenError):
        verify_token(
            kit.ring,
            kit.config,
            kind=TokenKind.SESSION,
            token=session_token,
            key=kit.ring.data_key,
        )


@pytest.mark.contract  # §18.2 — expired access ⇒ 401; refresh recovers
async def test_expired_access_is_401_and_refresh_recovers(client):
    from nx_auth.tokens import AuthMode, TokenKind, mint_token

    headers = await _session_cookie(client, "expire@example.com")
    kit = auth_kit()
    sub = user_id_from_headers({"Authorization": f"Bearer {_access_token(headers)}"})
    expired = mint_token(
        kit.ring,
        kit.config,
        kind=TokenKind.SESSION,
        sub=sub,
        ver=1,
        auth_mode=AuthMode.PASSWORD,
        ttl_seconds=-60,
    )
    stale = await client.get("/api/v1/auth/me", headers={"Cookie": f"nx_access={expired}"})
    assert stale.status_code == 401

    # The refresh cookie rotates the session back to life (§8/§12).
    refreshed = await client.post("/api/v1/auth/refresh", headers=headers)
    assert refreshed.status_code == 200
    recovered = await client.get("/api/v1/auth/me", headers=session_headers(refreshed))
    assert recovered.status_code == 200


@pytest.mark.contract  # §18.3 — rotation; replay ⇒ family revoked + ver bump
async def test_refresh_rotation_and_reuse_detection(client, db):
    from sqlalchemy import select

    from app.models.user_model import User

    login = await client.post(
        "/api/v1/auth/register",
        json={"email": "rotate@example.com", "password": PASSWORD},
    )
    assert login.status_code == 201
    first_refresh = _refresh_cookie(login)
    assert first_refresh

    rotated = await client.post("/api/v1/auth/refresh", headers=session_headers(login))
    assert rotated.status_code == 200
    second_refresh = _refresh_cookie(rotated)
    assert second_refresh and second_refresh != first_refresh

    # Replay of the rotated-out token: family revoked + ver bump (§8).
    replay = await client.post("/api/v1/auth/refresh", headers=_refresh_headers(first_refresh))
    assert replay.status_code == 423

    user = (
        (await db.execute(select(User).where(User.email == "rotate@example.com"))).scalars().one()
    )
    assert user.token_version == 2, "reuse bumps token_version (global sign-out)"

    # Every outstanding session token is dead now.
    assert (
        await client.get("/api/v1/auth/me", headers=session_headers(rotated))
    ).status_code == 401


async def test_logout_revokes_only_this_family(client):
    """§5/§12: logout revokes the family row — its refresh token dies.
    The 60-minute access tail is legal until expiry; `logout-all` is the
    immediate kill (ver bump, covered below)."""
    mine = await client.post(
        "/api/v1/auth/register",
        json={"email": "mine@example.com", "password": PASSWORD},
    )
    other = await register_user(client, "other@example.com", PASSWORD)
    my_headers = session_headers(mine)
    my_refresh = _refresh_cookie(mine)
    assert my_refresh

    out = await client.post("/api/v1/auth/logout", headers=my_headers)
    assert out.status_code == 200

    rotated = await client.post("/api/v1/auth/refresh", headers=_refresh_headers(my_refresh))
    assert rotated.status_code == 401, "the family is revoked — refresh is dead"
    assert (await client.get("/api/v1/auth/me", headers=other)).status_code == 200, (
        "other families of other users are untouched"
    )


async def test_logout_all_bumps_token_version(client, auth_headers, db):
    from sqlalchemy import select

    from app.models.user_model import User

    same_user_again = mint_session_headers(email="student@example.com")
    out = await client.post("/api/v1/auth/logout-all", headers=auth_headers)
    assert out.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=auth_headers)).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=same_user_again)).status_code == 401, (
        "every session of the user dies (ver bump)"
    )

    user = (
        (await db.execute(select(User).where(User.email == "student@example.com"))).scalars().one()
    )
    assert user.token_version == 2


@pytest.mark.contract  # §18.9 — is_active=false ⇒ 401 everywhere
async def test_inactive_user_is_rejected_everywhere(client, auth_headers):
    kit = auth_kit()
    user_id = user_id_from_headers(auth_headers)
    kit.users.set_active(user_id, False)
    assert (await client.get("/api/v1/auth/me", headers=auth_headers)).status_code == 401
    # Enforced domain routes reject too (§18.9).
    assert (await client.get("/api/v1/me/bootstrap", headers=auth_headers)).status_code == 401
    kit.users.set_active(user_id, True)
    assert (await client.get("/api/v1/auth/me", headers=auth_headers)).status_code == 200


async def test_session_list_and_revoke(client):
    registered = await client.post(
        "/api/v1/auth/register", json={"email": "fam@example.com", "password": PASSWORD}
    )
    headers = session_headers(registered)
    my_refresh = _refresh_cookie(registered)
    assert my_refresh
    listed = await client.get("/api/v1/me/sessions", headers=headers)
    assert listed.status_code == 200
    families = listed.json()
    assert len(families) == 1
    assert families[0]["current"] is True

    revoked = await client.delete(f"/api/v1/me/sessions/{families[0]['id']}", headers=headers)
    assert revoked.status_code == 204
    # The revoked family's refresh token is dead (§12 device revocation).
    rotated = await client.post("/api/v1/auth/refresh", headers=_refresh_headers(my_refresh))
    assert rotated.status_code == 401


async def test_password_change_keeps_caller_and_kills_other_sessions(client):
    headers = await register_user(client, "pw@example.com", PASSWORD)
    second = mint_session_headers(email="pw@example.com")
    changed = await client.patch(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": "brandnewpw1"},
        headers=headers,
    )
    assert changed.status_code == 200
    assert (
        await client.get("/api/v1/auth/me", headers=session_headers(changed))
    ).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=second)).status_code == 401
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "pw@example.com", "password": "brandnewpw1"},
    )
    assert login.status_code == 200


@pytest.mark.contract  # §18.9 — deletion cascades fully
async def test_delete_me_requires_password_and_cascades(client, db):
    from sqlalchemy import select

    from app.models.identity_model import AuthSession
    from app.models.user_model import Profile, User

    headers = await register_user(client, "bye@example.com", PASSWORD)
    user_id = user_id_from_headers(headers)

    wrong = await client.request(
        "DELETE", "/api/v1/me", json={"password": "not-it"}, headers=headers
    )
    assert wrong.status_code == 403

    ok = await client.request("DELETE", "/api/v1/me", json={"password": PASSWORD}, headers=headers)
    assert ok.status_code == 204
    assert (await db.execute(select(User).where(User.id == user_id))).scalars().first() is None
    profiles = (await db.execute(select(Profile).where(Profile.user_id == user_id))).scalars().all()
    assert profiles == []
    families = (
        (await db.execute(select(AuthSession).where(AuthSession.user_id == user_id)))
        .scalars()
        .all()
    )
    assert families == [], "deletion cascades fully (§18.9)"
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


@pytest.mark.contract  # §18.11 — demo login absent on non-demo instances
async def test_demo_login_hidden_on_non_demo_instance(client):
    response = await client.post("/api/v1/auth/demo")
    assert response.status_code == 404, "the demo principal needs demo_mode=true (§13)"


async def test_audit_trail_records_auth_actions(client, db):
    from sqlalchemy import select

    from app.models.identity_model import AuditEvent

    headers = await register_user(client, "audited@example.com", PASSWORD)
    await client.post(
        "/api/v1/auth/login",
        json={"email": "audited@example.com", "password": PASSWORD},
    )
    await client.post("/api/v1/auth/logout", headers=headers)
    actions = {row.action for row in (await db.execute(select(AuditEvent))).scalars().all()}
    assert {"auth.register", "auth.login", "auth.logout"} <= actions
