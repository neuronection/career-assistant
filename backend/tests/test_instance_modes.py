"""Instance access modes (identity-auth §4) + Desktop Identity Mode (§11).

DB-authoritative, init-only, fail-closed: initialization behavior, env
flip immunity, `local-boot`/`demo` token rejection, the desktop exchange
endpoint (open desktop only) and the per-boot shell-secret request gate.
"""

import pytest
from httpx import ASGITransport

from nx_auth.instance import initialize_instance
from app.auth.stores import CareerInstanceStore
from app.core.config import settings
from app.core.database import AuthSessionLocal
from tests.conftest import CleanJarClient, session_headers

PASSWORD = "supersecret1"

# Every test here implements identity-auth §18.6 (instance modes, §4)
# through career's real boot paths — the family contract drift gate.
pytestmark = pytest.mark.contract


def _store() -> CareerInstanceStore:
    return CareerInstanceStore(AuthSessionLocal)


# ------------------------------------------------------------ initialization


def test_server_defaults_to_authenticated_on_empty_db():
    mode = initialize_instance(
        _store(), identity_mode="server", auth_mode_env="", demo_mode_env=False
    )
    assert mode == "authenticated"
    assert _store().get("auth_mode") == "authenticated"


def test_desktop_defaults_to_open_on_empty_db():
    mode = initialize_instance(
        _store(), identity_mode="desktop", auth_mode_env="", demo_mode_env=False
    )
    assert mode == "open"


def test_init_respects_explicit_auth_mode():
    assert (
        initialize_instance(
            _store(),
            identity_mode="desktop",
            auth_mode_env="authenticated",
            demo_mode_env=False,
        )
        == "authenticated"
    )


def test_server_never_runs_open():
    """§4.4 — even an explicit open request initializes authenticated."""
    mode = initialize_instance(
        _store(), identity_mode="server", auth_mode_env="open", demo_mode_env=False
    )
    assert mode == "authenticated"
    assert _store().get("auth_mode") == "authenticated"


def test_unknown_auth_mode_fails_closed():
    mode = initialize_instance(
        _store(), identity_mode="desktop", auth_mode_env="banana", demo_mode_env=False
    )
    assert mode == "authenticated"


def test_post_init_env_flips_are_ignored():
    """§4.1 — the DB is authoritative; env may set the mode only at init."""
    store = _store()
    initialize_instance(
        store,
        identity_mode="desktop",
        auth_mode_env="authenticated",
        demo_mode_env=False,
    )
    again = initialize_instance(
        store, identity_mode="desktop", auth_mode_env="open", demo_mode_env=False
    )
    assert again == "authenticated"
    assert store.get("auth_mode") == "authenticated", (
        "a launch-time flip cannot disable auth"
    )


def test_demo_mode_is_init_only():
    store = _store()
    initialize_instance(
        store, identity_mode="server", auth_mode_env="", demo_mode_env=True
    )
    assert store.get("demo_mode") == "true"
    initialize_instance(
        store, identity_mode="server", auth_mode_env="", demo_mode_env=False
    )
    assert store.get("demo_mode") == "true", "post-init flips are ignored (§13)"


# --------------------------------------------------- enforcement is stateful


def _mint_token(
    app, *, kind, auth_mode, sub: str = "some-user", ver: int = 1, ttl=None
):
    from nx_auth.tokens import AuthMode, TokenKind, mint_token

    kit = app.state.auth
    return mint_token(
        kit.ring,
        kit.config,
        kind=TokenKind(kind),
        sub=sub,
        ver=ver,
        auth_mode=AuthMode(auth_mode),
        ttl_seconds=ttl,
    )


async def test_local_boot_token_rejected_on_authenticated_instance(client):
    from app.main import app

    token = _mint_token(app, kind="session", auth_mode="local-boot", sub="x")
    response = await client.get(
        "/api/v1/auth/me", headers={"Cookie": f"nx_access={token}"}
    )
    assert response.status_code == 401, "local-boot is open-desktop only (§4.3)"


async def test_demo_token_rejected_on_non_demo_instance(client):
    from app.main import app

    token = _mint_token(app, kind="session", auth_mode="demo", sub="demo-user")
    response = await client.get(
        "/api/v1/auth/me", headers={"Cookie": f"nx_access={token}"}
    )
    assert response.status_code == 401


async def test_exchange_absent_on_server_entrypoint(client):
    response = await client.post(
        "/api/v1/auth/desktop/exchange", headers={"X-Shell-Token": "anything"}
    )
    assert response.status_code == 404, "the server entrypoint never routes DIM (§4.3)"


# ------------------------------------------------------- desktop entrypoint


@pytest.fixture
def desktop_factory(monkeypatch):
    """Build desktop-mode apps (identity_mode=desktop + CAREER_SHELL=1,
    the shell.py attachment flag ⇒ shell secret + DIM exchange). Returns
    make(auth_mode_env) → (app, client, secret)."""
    from app.desktop import shell_token
    from app.main import create_app

    monkeypatch.setattr(settings, "IDENTITY_MODE", "desktop")
    monkeypatch.setenv("CAREER_SHELL", "1")

    def make(auth_mode_env: str = "") -> tuple:
        monkeypatch.setattr(settings, "AUTH_MODE", auth_mode_env)
        application = create_app()
        secret = shell_token.current()
        assert secret
        client = CleanJarClient(
            transport=ASGITransport(app=application), base_url="http://test"
        )
        return application, client, secret

    yield make
    shell_token.reset()


async def test_desktop_open_exchanges_the_implicit_owner(desktop_factory):
    application, client, secret = desktop_factory()

    # The gate is the per-boot shell secret (§11.1): no/wrong token ⇒ 403.
    assert (await client.get("/api/v1/auth/me")).status_code == 403
    assert (
        await client.get("/api/v1/auth/me", headers={"X-Shell-Token": "wrong"})
    ).status_code == 403

    exchange = await client.post(
        "/api/v1/auth/desktop/exchange", headers={"X-Shell-Token": secret}
    )
    assert exchange.status_code == 200, exchange.text
    body = exchange.json()
    assert body["email"] == "owner@local"
    assert body["is_admin"] is True
    assert body["is_active"] is True

    headers = session_headers(exchange)
    me = await client.get(
        "/api/v1/auth/me", headers=headers | {"X-Shell-Token": secret}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "owner@local"

    # DIM mints a session token only (§11.3) — no refresh family.
    assert all(
        not line.startswith("nx_refresh=")
        for line in exchange.headers.get_list("set-cookie")
    )


async def test_desktop_open_needs_no_login_routes_but_mints_local_boot(desktop_factory):
    application, client, secret = desktop_factory()
    exchange = await client.post(
        "/api/v1/auth/desktop/exchange", headers={"X-Shell-Token": secret}
    )
    token = session_headers(exchange)["Authorization"].split(" ", 1)[1]
    from nx_auth.tokens import AuthMode, TokenKind, verify_token

    kit = application.state.auth
    claims = verify_token(kit.ring, kit.config, kind=TokenKind.SESSION, token=token)
    assert claims["auth_mode"] == AuthMode.LOCAL_BOOT.value


async def test_desktop_authenticated_requires_login(desktop_factory):
    application, client, secret = desktop_factory(auth_mode_env="authenticated")

    # DIM does not apply (§4.3) — the exchange endpoint answers 404 …
    exchange = await client.post(
        "/api/v1/auth/desktop/exchange", headers={"X-Shell-Token": secret}
    )
    assert exchange.status_code == 404

    # … and login is the boot flow.
    anonymous = await client.get("/api/v1/auth/me", headers={"X-Shell-Token": secret})
    assert anonymous.status_code == 401
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": "desk@example.com", "password": PASSWORD},
        headers={"X-Shell-Token": secret},
    )
    assert registered.status_code == 201
    me = await client.get(
        "/api/v1/auth/me",
        headers=session_headers(registered) | {"X-Shell-Token": secret},
    )
    assert me.status_code == 200


async def test_desktop_authenticated_rejects_local_boot(desktop_factory):
    application, client, secret = desktop_factory(auth_mode_env="authenticated")
    token = _mint_token(
        application,
        kind="session",
        auth_mode="local-boot",
        sub="owner-id",
    )
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Cookie": f"nx_access={token}", "X-Shell-Token": secret},
    )
    assert response.status_code == 401, "no local-boot token is ever valid here (§11.5)"


async def test_shell_secret_gates_every_api_request(desktop_factory):
    application, client, secret = desktop_factory()
    for method, path in (
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/login"),
        ("GET", "/api/v1/me/bootstrap"),
    ):
        denied = await client.request(method, path, headers={"Cookie": "nx_access=x"})
        assert denied.status_code == 403, f"{method} {path} without the shell secret"
    # The liveness probe stays reachable (outside /api — §11 gates API traffic).
    assert (await client.get("/health")).status_code == 200


async def test_shell_less_desktop_dev_leaves_the_gate_open(monkeypatch):
    """ADR-0023: desktop identity WITHOUT an attached shell (`run-dev.sh`:
    uvicorn + vite — no CAREER_SHELL=1, no `?shell=` carrier) must not arm
    the §11 gate, or the dev SPA could never authenticate."""
    from app.desktop import shell_token
    from app.main import create_app

    monkeypatch.delenv("CAREER_SHELL", raising=False)
    monkeypatch.setattr(settings, "IDENTITY_MODE", "desktop")
    monkeypatch.setattr(settings, "AUTH_MODE", "")
    shell_token.reset()
    try:
        application = create_app()
        client = CleanJarClient(
            transport=ASGITransport(app=application), base_url="http://test"
        )
        # No token is issued and the API answers without X-Shell-Token.
        assert shell_token.current() is None
        me = await client.get("/api/v1/auth/me")
        assert me.status_code != 403, "shell-less desktop dev must not gate the API"
    finally:
        shell_token.reset()


async def test_instance_mode_reads_are_per_request(desktop_factory):
    """§4.2 — enforcement derives from live DB state, never a boot
    snapshot: flipping auth_mode invalidates local-boot immediately."""
    application, client, secret = desktop_factory()
    exchange = await client.post(
        "/api/v1/auth/desktop/exchange", headers={"X-Shell-Token": secret}
    )
    headers = session_headers(exchange) | {"X-Shell-Token": secret}
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200

    _store().set("auth_mode", "authenticated")
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_unknown_stored_mode_fails_closed(client):
    """A garbage `auth_mode` row evaluates as authenticated (§4.1)."""
    _store().set("auth_mode", "sometimes-maybe")
    from app.main import app

    token = _mint_token(app, kind="session", auth_mode="local-boot", sub="x")
    assert (
        await client.get("/api/v1/auth/me", headers={"Cookie": f"nx_access={token}"})
    ).status_code == 401


# ------------------------------------------- S14 / §4.5 admin transitions


async def test_admin_instance_transition_round_trip(desktop_factory):
    """S14 — `PATCH /api/v1/admin/instance` over the career adapters:
    the password-less DIM owner sets credentials and enables login
    (§4.5 `open → authenticated`), then confirms the password to go back
    open; a wrong password never flips anything. Server entrypoints
    refuse `open` outright (pinned in test_server_never_runs_open)."""
    application, client, secret = desktop_factory()
    exchange = await client.post(
        "/api/v1/auth/desktop/exchange", headers={"X-Shell-Token": secret}
    )
    dim_headers = session_headers(exchange) | {"X-Shell-Token": secret}
    assert _store().get("auth_mode") == "open"

    to_auth = await client.patch(
        "/api/v1/admin/instance",
        json={"auth_mode": "authenticated", "password": "supersecret1"},
        headers=dim_headers,
    )
    assert to_auth.status_code == 200, to_auth.text
    assert _store().get("auth_mode") == "authenticated"

    # local-boot dies with the flip (§4.2) — password session from here.
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@local", "password": "supersecret1"},
        headers={"X-Shell-Token": secret},
    )
    assert login.status_code == 200, login.text
    authed_headers = session_headers(login) | {"X-Shell-Token": secret}

    wrong = await client.patch(
        "/api/v1/admin/instance",
        json={"auth_mode": "open", "password": "not-the-password"},
        headers=authed_headers,
    )
    assert wrong.status_code == 403
    assert _store().get("auth_mode") == "authenticated", "wrong password must not flip"

    to_open = await client.patch(
        "/api/v1/admin/instance",
        json={"auth_mode": "open", "password": "supersecret1"},
        headers=authed_headers,
    )
    assert to_open.status_code == 200, to_open.text
    assert _store().get("auth_mode") == "open"


async def test_admin_instance_open_refused_with_other_users(desktop_factory):
    """S14 — multi-user instances cannot go open (§4.5 refusal rail):
    the password-confirmed flip is refused while another user row
    exists, and succeeds once the account is gone."""
    application, client, secret = desktop_factory()
    exchange = await client.post(
        "/api/v1/auth/desktop/exchange", headers={"X-Shell-Token": secret}
    )
    dim_headers = session_headers(exchange) | {"X-Shell-Token": secret}
    assert (
        await client.patch(
            "/api/v1/admin/instance",
            json={"auth_mode": "authenticated", "password": "supersecret1"},
            headers=dim_headers,
        )
    ).status_code == 200

    owner = session_headers(
        await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@local", "password": "supersecret1"},
            headers={"X-Shell-Token": secret},
        )
    ) | {"X-Shell-Token": secret}

    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": "supersecret1"},
        headers={"X-Shell-Token": secret},
    )
    assert registered.status_code == 201, registered.text
    second = session_headers(registered) | {"X-Shell-Token": secret}

    refused = await client.patch(
        "/api/v1/admin/instance",
        json={"auth_mode": "open", "password": "supersecret1"},
        headers=owner,
    )
    assert refused.status_code == 403
    assert _store().get("auth_mode") == "authenticated"

    # the second account removes itself (§12 self-service delete)
    gone = await client.request(
        "DELETE",
        "/api/v1/me",
        json={"password": "supersecret1"},
        headers=second,
    )
    assert gone.status_code == 204, gone.text

    allowed = await client.patch(
        "/api/v1/admin/instance",
        json={"auth_mode": "open", "password": "supersecret1"},
        headers=owner,
    )
    assert allowed.status_code == 200, allowed.text
    assert _store().get("auth_mode") == "open"
