"""E2E fixtures.

The suite runs against a REAL server booted by `scripts/run-e2e.sh`:
built SPA mounted by FastAPI, scratch database, mock AI provider
auto-provisioned under APP_ENV=test. The app is single-user (the
login/register screens are gone): every spec starts at `/` as the
default user, and an autouse fixture resets the workspace through the
API so specs stay independent and order-free.
"""

import os

import pytest
from playwright.sync_api import Page

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8111")
API = f"{BASE_URL}/api/v1"

# (list path, key) — `key` for payloads wrapping the rows ("items",
# "proposals"); None for bare-array payloads. Single-user mode means no
# Authorization header: requests without a token resolve to the default
# user.
_COLLECTIONS = (
    ("/cv", None),
    ("/cv/synth", None),
    ("/chat/sessions", None),
    ("/me/experience", "items"),
    # HITL cards (plan 77): dismissible only while pending — resolved
    # rows 4xx harmlessly and never affect other specs.
    ("/me/profile-proposals", "proposals"),
)


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
            page.request.delete(f"{API}{path}/{row['id']}")


@pytest.fixture(autouse=True)
def clean_workspace(page: Page):
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
        import os

        path = f"/tmp/e2e-fail-{request.node.name}.png"
        try:
            page.screenshot(path=path, full_page=True)
            print(f"SCREENSHOT {os.path.abspath(path)}")
        except Exception:  # noqa: BLE001
            pass
        for line in console[-25:]:
            print("CONSOLE", line)
