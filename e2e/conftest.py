"""E2E fixtures.

The suite runs against a REAL server booted by `scripts/run-e2e.sh`:
built SPA mounted by FastAPI, scratch database, mock AI provider
auto-provisioned under APP_ENV=test. The server runs the `authenticated`
instance mode (identity-auth §4 — fail-closed; server entrypoints never
run `open`), so every spec runs as the logged-in e2e user: a
session-scoped bootstrap registers/logs in once over the real auth API
and hands the session cookies to each spec's browser context. An autouse
fixture resets the workspace through the API so specs stay independent
and order-free.
"""

import json
import os
import urllib.error
import urllib.request

import pytest
from playwright.sync_api import Page

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


@pytest.fixture(autouse=True)
def authed_context(context, e2e_session_cookies):
    """Every spec's browser context carries the e2e session + CSRF echo."""
    context.add_cookies(e2e_session_cookies)
    context.set_extra_http_headers({"X-CSRF-Token": E2E_CSRF})
    return context


def reset_workspace(page: Page) -> None:
    """Delete every workspace artifact (CVs, synth variants, chat
    sessions, experience entries, pending HITL cards) so each spec
    starts pristine."""
    for path, key in _COLLECTIONS:
        response = page.request.get(f"{API}{path}")
        if not response.ok:
            continue
        payload = response.json()
        rows = payload[key] if key else payload
        for row in rows:
            page.request.delete(f"{API}{path}/{row['id']}", headers={"X-CSRF-Token": E2E_CSRF})


@pytest.fixture(autouse=True)
def clean_workspace(page: Page, authed_context):
    reset_workspace(page)
    yield
    reset_workspace(page)


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
