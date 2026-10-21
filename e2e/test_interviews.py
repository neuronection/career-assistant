"""Interview practice: a generated plan → practice loop in the chat surface.

The session is created through the API (the mock `INTERVIEW_PLAN` fixture
drafts the plan deterministically) so the spec focuses on the practice
loop: the plan renders, practice opens the bound chat session, and one
answered question comes back as a coached turn with a rubric.
"""

import re
import time

import pytest
from conftest import API, BASE_URL, api_headers
from playwright.sync_api import expect


@pytest.fixture()
def interview_session(page) -> dict:
    response = page.request.post(
        f"{API}/interview/sessions",
        data={"job_code": "data-scientist", "kind": "behavioral"},
        headers=api_headers(),
    )
    if not response.ok:
        pytest.skip(f"interview session unavailable: {response.status} {response.text()[:200]}")
    return response.json()


def test_interview_plan_and_practice_loop(page, interview_session) -> None:
    page.goto(f"{BASE_URL}/interviews")
    page.wait_for_selector('[data-testid="interviews-page"]')

    rail_entry = page.get_by_test_id(f"interview-session-{interview_session['id']}")
    expect(rail_entry).to_be_visible(timeout=30_000)
    rail_entry.click()

    expect(page.get_by_test_id("interview-detail")).to_be_visible(timeout=30_000)
    expect(page.get_by_test_id("interview-plan")).to_be_visible()
    assert page.locator('[data-testid^="plan-item-"]').count() > 0

    page.get_by_test_id("practice-interview").click()
    page.get_by_role("textbox", name="Message").wait_for(state="visible", timeout=60_000)
    # The start call binds the session, then the surface navigates — wait for
    # the route commit instead of racing it.
    expect(page).to_have_url(re.compile(r"/chat$"), timeout=30_000)

    composer = page.locator('[data-as="chat-composer"] textarea').last
    composer.wait_for(state="visible", timeout=30_000)
    composer.fill("I shipped a container pipeline that cut deploy time in half.")
    send = page.get_by_role("button", name="Send message")
    expect(send).to_be_enabled(timeout=10_000)
    send.click()

    # The interview graph persists its turn through the builder-turn path
    # (no chat trace block); the coached mock reply is the completion signal.
    expect(page.get_by_text("One improvement").first).to_be_visible(timeout=90_000)

    # The rubric is committed when the interview node records the turn —
    # poll instead of racing the persistence commit that follows the trace.
    deadline = time.monotonic() + 30
    scored: list = []
    while time.monotonic() < deadline:
        detail = page.request.get(
            f"{API}/interview/sessions/{interview_session['id']}", headers=api_headers()
        )
        assert detail.ok, detail.text()
        scored = detail.json()["rubric_scores"]
        if scored:
            break
        page.wait_for_timeout(500)
    assert scored, "the answered question is scored"
