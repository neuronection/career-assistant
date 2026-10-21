"""Plan 118 — first-run AI setup on a fresh instance.

The scratch server boots with the mock carrier already configured
(`e2e/seed_ai.py`). This spec unconfigures the instance through the API,
proves the app lands on the setup step and walks the wizard (manual
provider — the only key-free path in a smoke run) through the connection
test and the task assignment step, then proves chat works.

No spec here may call a live vendor endpoint: the provider registered by
the wizard is the deterministic mock type.
"""

import re

from conftest import API, BASE_URL, api_headers


def _unconfigure(page) -> None:
    """Deactivate every provider so the instance reports unconfigured.

    Deleting them instead would let the dev mock carrier auto-provision on
    the next AI call; an inactive row keeps the app honestly unconfigured
    for the length of the spec.
    """
    providers = page.request.get(f"{API}/ai/providers", headers=api_headers())
    assert providers.ok, providers.text()
    for provider in providers.json():
        if not provider["is_active"]:
            continue
        updated = page.request.put(
            f"{API}/ai/providers/{provider['id']}",
            data={"is_active": False},
            headers=api_headers(),
        )
        assert updated.ok, updated.text()
    cleared = page.request.put(
        f"{API}/me/preferences/ai-setup",
        data={"dismissed": False},
        headers=api_headers(),
    )
    assert cleared.ok, cleared.text()
    assert _bootstrap(page)["ai"]["configured"] is False


def _bootstrap(page) -> dict:
    response = page.request.get(f"{API}/me/bootstrap", headers=api_headers())
    assert response.ok, response.text()
    return response.json()


def _seed_mock_carrier(page, name: str) -> None:
    """Re-configure a mock carrier so later specs run on a configured app."""
    provider = page.request.post(
        f"{API}/ai/providers",
        data={"name": name, "provider_type": "mock", "scope": "system"},
        headers=api_headers(),
    )
    assert provider.status == 201, provider.text()
    model = page.request.post(
        f"{API}/ai/providers/{provider.json()['id']}/models",
        data={"name": "mock-large", "model_name": "mock-large", "caps": ["text"]},
        headers=api_headers(),
    )
    assert model.status == 201, model.text()
    for slot in ("text", "vision", "stt", "embeddings"):
        bound = page.request.put(
            f"{API}/ai/assignments/{slot}",
            data={"scope": "system", "model_id": model.json()["id"]},
            headers=api_headers(),
        )
        assert bound.ok, bound.text()


def test_first_run_setup_wizard_connects_and_chats(page) -> None:
    _unconfigure(page)

    # Boot of an unconfigured instance lands on the system-setup step.
    page.goto(f"{BASE_URL}/")
    page.wait_for_url(re.compile(r"/onboarding/setup$"), timeout=30_000)
    page.wait_for_selector('[data-testid="ai-setup-page"]')
    page.get_by_role("heading", name="Set up AI").wait_for(state="visible")
    page.wait_for_selector('[data-testid="provider-setup-wizard"]')

    # Manual path: the wizard hands off to the provider form (mock type is
    # the only key-free provider — dev/test only on the backend).
    page.get_by_role("button", name="Set up manually").click()
    dialog = page.get_by_role("dialog")
    dialog.wait_for(state="visible")
    dialog.get_by_role("combobox").filter(has_text="OpenAI").click()
    page.get_by_role("option").filter(has_text="Mock").click()
    dialog.get_by_role("textbox", name="Name").fill("First-run mock")
    dialog.get_by_role("button", name="Save provider").click()
    dialog.wait_for(state="hidden", timeout=15_000)

    page.wait_for_selector('[data-testid="ai-setup-verify"]')
    page.wait_for_selector('[data-testid="ai-setup-no-models"]')

    # The manual form registers the connection only; models are added in AI
    # settings. Seed one through the API and pick it up with Refresh.
    providers = page.request.get(f"{API}/ai/providers", headers=api_headers()).json()
    provider = next(row for row in providers if row["name"] == "First-run mock")
    assert provider["provider_type"] == "mock"
    model = page.request.post(
        f"{API}/ai/providers/{provider['id']}/models",
        data={"name": "mock-large", "model_name": "mock-large", "caps": ["text", "vision"]},
        headers=api_headers(),
    )
    assert model.status == 201, model.text()

    page.get_by_test_id("ai-setup-refresh").click()
    page.get_by_text("Connected").wait_for(state="visible", timeout=20_000)

    # Task assignments: the chat default is what makes AI configured.
    page.get_by_role("combobox", name="Text", exact=True).click()
    page.get_by_role("option").filter(has_text="mock-large").click()
    page.wait_for_selector('[data-testid="ai-setup-finish"]:not([disabled])', timeout=20_000)
    page.get_by_test_id("ai-setup-finish").click()
    page.wait_for_selector('[data-testid="path-picker"]', timeout=20_000)

    assert _bootstrap(page)["ai"]["configured"] is True

    # And the feature that needs a provider now works end-to-end.
    page.goto(f"{BASE_URL}/")
    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)
    dock.get_by_role("button", name="New chat").click()
    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)
    composer.fill("What jobs fit someone who likes data?")
    composer.press("Enter")
    page.wait_for_selector('[data-testid="chat-message-trace"]', timeout=60_000)


def test_skipping_setup_persists_and_the_prompt_stays(page) -> None:
    """Skip is a persisted choice; the setup prompt remains until configured."""
    _unconfigure(page)

    page.goto(f"{BASE_URL}/")
    page.wait_for_url(re.compile(r"/onboarding/setup$"), timeout=30_000)
    page.get_by_test_id("ai-setup-skip").click()
    page.wait_for_url(re.compile(r"/onboarding$"), timeout=20_000)

    dismissed = _bootstrap(page)["ai"]
    assert dismissed["setup_dismissed"] is True
    assert dismissed["configured"] is False

    # A later boot no longer bounces, but every AI surface still offers the
    # setup affordance (Autopilot start here).
    page.goto(f"{BASE_URL}/autopilot")
    page.wait_for_selector('[data-testid="ai-setup-prompt-banner"]', timeout=20_000)
    assert "/onboarding/setup" not in page.url

    _seed_mock_carrier(page, "Smoke mock")
