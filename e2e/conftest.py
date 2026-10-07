"""E2E fixtures.

The suite runs against a REAL server booted by `scripts/run-e2e.sh`:
built SPA mounted by FastAPI, scratch database, mock AI provider
auto-provisioned under CAREER_APP_ENV=test. The server runs the `authenticated`
instance mode (identity-auth §4 — fail-closed; server entrypoints never
run `open`), so every spec runs as the logged-in e2e user: a
session-scoped bootstrap registers/logs in once over the real auth API
and hands the session cookies to each spec's browser context. An autouse
fixture resets the workspace through the API so specs stay independent
and order-free.
"""

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable

import pytest
from playwright.sync_api import APIResponse, Page

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8111")
API = f"{BASE_URL}/api/v1"

E2E_EMAIL = os.environ.get("E2E_USER_EMAIL", "e2e@example.com")
E2E_PASSWORD = os.environ.get("E2E_USER_PASSWORD", "e2e-supersecret1")
# The CSRF cookie is JS-readable by design (identity-auth §10 double
# submit) — the suite pins its own value and echoes it on every request.
E2E_CSRF = "e2e-csrf-double-submit"

# (list path, key) — `key` for payloads wrapping the rows ("items",
# "proposals"); None for bare-array payloads.
_COLLECTIONS = (
    ("/cv", None),
    ("/cv/synth", None),
    ("/chat/sessions", None),
    ("/me/experience", "items"),
    # HITL cards (plan 77): dismissible only while pending — resolved
    # rows 4xx harmlessly and never affect other specs.
    ("/me/profile-proposals", "proposals"),
)


def _post_json(path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, {}
    except urllib.error.HTTPError as error:  # noqa: PERF203 — 4xx is data here
        return error.code, {}


@pytest.fixture(scope="session")
def e2e_session_cookies() -> list[dict]:
    """The e2e user's session cookies, minted once per run (identity-auth
    §10): register (first run) → login → the kit's Set-Cookie session."""
    _post_json(
        "/auth/register",
        {"email": E2E_EMAIL, "password": E2E_PASSWORD, "full_name": "E2E"},
    )
    request = urllib.request.Request(
        f"{API}/auth/login",
        data=json.dumps({"email": E2E_EMAIL, "password": E2E_PASSWORD}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        set_cookies = response.headers.get_all("Set-Cookie") or []
    if not set_cookies:
        raise RuntimeError("e2e login produced no session cookies")
    cookies = []
    for line in set_cookies:
        name, _, rest = line.partition("=")
        value = rest.split(";", 1)[0]
        cookies.append(
            {
                "name": name.strip(),
                "value": value,
                "domain": "127.0.0.1",
                "path": "/api/v1/auth" if name.strip() == "nx_refresh" else "/",
                "httpOnly": name.strip() != "nx_csrf",
                "secure": False,
                "sameSite": "Lax",
            }
        )
    cookies.append(
        {
            "name": "nx_csrf",
            "value": E2E_CSRF,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": False,
            "secure": False,
            "sameSite": "Lax",
        }
    )
    return cookies


#: The e2e user's Default profile id (identity-auth §6/§15) — resolved
#: once from `GET /profiles`; every raw API call must scope to it.
_E2E_PROFILE_ID: str | None = None


def api_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Headers for raw `page.request` calls: CSRF echo + profile scope.

    `X-Profile-Id` is mandatory on non-exempt `/api/` paths in
    authenticated (server) mode — the SPA sends it, so every direct API
    call in a spec must too.
    """
    headers = {"X-CSRF-Token": E2E_CSRF}
    if _E2E_PROFILE_ID:
        headers["X-Profile-Id"] = _E2E_PROFILE_ID
    if extra:
        headers.update(extra)
    return headers


@pytest.fixture(autouse=True)
def authed_context(context, e2e_session_cookies):
    """Every spec's browser context carries the e2e session + CSRF echo."""
    global _E2E_PROFILE_ID
    context.add_cookies(e2e_session_cookies)
    context.set_extra_http_headers({"X-CSRF-Token": E2E_CSRF})
    if _E2E_PROFILE_ID is None:
        response = context.request.get(f"{API}/profiles")
        if response.ok:
            profiles = response.json()
            fallback = profiles[0] if profiles else None
            default = next((p for p in profiles if p.get("is_default")), fallback)
            if default:
                _E2E_PROFILE_ID = str(default["id"])
    return context


def _cleanup_request(
    call: Callable[[], APIResponse], *, best_effort: bool
) -> APIResponse | None:
    """Run one workspace-cleanup request, retrying once on a dropped
    connection (the documented plan-20 teardown flake:
    `APIRequestContext.get: read ECONNRESET`). In best-effort mode a
    request that still fails is swallowed — cleanup must never fail a
    spec that already passed; strict mode re-raises after the retry."""
    for attempt in (0, 1):
        try:  # noqa: PERF203 — the retry loop lives here on purpose
            return call()
        except Exception:  # noqa: BLE001 — Playwright surfaces every transport failure as Error
            if attempt == 0:
                time.sleep(0.25)
                continue
            if not best_effort:
                raise
            return None
    return None


def reset_workspace(page: Page, *, best_effort: bool = False) -> None:
    """Delete every workspace artifact (CVs, synth variants, chat
    sessions, experience entries, pending HITL cards) so each spec
    starts pristine.

    The pre-test pass is strict (a spec that cannot start pristine must
    say so instead of asserting against leftovers); the post-test pass is
    pure cleanup and best-effort."""
    for path, key in _COLLECTIONS:
        response = _cleanup_request(
            lambda path=path: page.request.get(f"{API}{path}", headers=api_headers()),
            best_effort=best_effort,
        )
        if response is None or not response.ok:
            continue
        payload = response.json()
        rows = payload[key] if key else payload
        for row in rows:
            _cleanup_request(
                lambda path=path, row=row: page.request.delete(
                    f"{API}{path}/{row['id']}", headers=api_headers()
                ),
                best_effort=best_effort,
            )


@pytest.fixture(autouse=True)
def clean_workspace(page: Page, authed_context):
    reset_workspace(page)
    yield
    # Teardown is pure cleanup: a connection the server dropped mid-run
    # must never fail a spec whose body already passed (plan 20 flake).
    reset_workspace(page, best_effort=True)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture(autouse=True)
def _screenshot_on_failure(page, request):
    console: list[str] = []
    page.on("console", lambda msg: console.append(f"{msg.type}: {msg.text[:200]}"))
    page.on("pageerror", lambda error: console.append(f"pageerror: {error}"))
    yield page
    if getattr(request.node, "rep_call", None) is not None and (
        request.node.rep_call.failed
    ):
        import os as _os

        path = f"/tmp/e2e-fail-{request.node.name}.png"
        try:
            page.screenshot(path=path, full_page=True)
            print(f"SCREENSHOT {_os.path.abspath(path)}")
        except Exception:  # noqa: BLE001
            pass
        for line in console[-25:]:
            print("CONSOLE", line)
