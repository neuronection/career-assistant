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

# (list path, wrapped) — `wrapped` for payloads shaped {"items": [...]}.
# Single-user mode means no Authorization header: requests without a
# token resolve to the default user.
_COLLECTIONS = (
    ("/cv", False),
    ("/cv/synth", False),
    ("/chat/sessions", False),
    ("/me/experience", True),
)


def reset_workspace(page: Page) -> None:
    """Delete every workspace artifact (CVs, synth variants, chat
    sessions, experience entries) so each spec starts pristine."""
    for path, wrapped in _COLLECTIONS:
        response = page.request.get(f"{API}{path}")
        if not response.ok:
            continue
        payload = response.json()
        rows = payload["items"] if wrapped else payload
        for row in rows:
            page.request.delete(f"{API}{path}/{row['id']}")


@pytest.fixture(autouse=True)
def clean_workspace(page: Page):
    reset_workspace(page)
    yield
    reset_workspace(page)
