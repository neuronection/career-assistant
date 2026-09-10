"""E2E fixtures.

The suite runs against a REAL server booted by `scripts/run-e2e.sh`:
built SPA mounted by FastAPI, scratch database, mock AI provider
auto-provisioned under APP_ENV=test. Each spec registers a fresh user
so specs stay independent and order-free.
"""

import os
import uuid

import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8111")


@pytest.fixture()
def credentials() -> tuple[str, str]:
    return (f"e2e-{uuid.uuid4().hex[:10]}@example.com", "e2e-password-1")


def register_via_ui(page: Page, credentials: tuple[str, str]) -> None:
    """Fresh user through the real register form (lands on /onboarding)."""
    email, password = credentials
    page.goto(f"{BASE_URL}/register")
    page.get_by_placeholder("Full name").fill("E2E Runner")
    page.get_by_placeholder("Email").fill(email)
    page.get_by_placeholder("Password (min 8 chars)").fill(password)
    page.get_by_role("button", name="Register").click()
    expect(page).to_have_url(f"{BASE_URL}/onboarding")


def login_via_ui(page: Page, credentials: tuple[str, str]) -> None:
    email, password = credentials
    page.goto(f"{BASE_URL}/login")
    page.get_by_placeholder("Email").fill(email)
    page.get_by_placeholder("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{BASE_URL}/")
