"""Interview practice: a generated plan → practice loop in the chat surface.

The session is created through the API (the mock `INTERVIEW_PLAN` fixture
drafts the plan deterministically) so the spec focuses on the practice
loop: the plan renders, practice opens the bound chat session, and one
answered question comes back as a coached turn with a rubric.
"""

import pytest
from conftest import API, BASE_URL, api_headers
from playwright.sync_api import expect


@pytest.fixture()
def interview_session(page) -> dict:
    response = page.request.post(
        f"{API}/interviews/sessions",
        data={"job_code": "E2E-INTERVIEW", "kind": "behavioral"},
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
    expect(page.get_by_role("textbox", name="Message")).to_be_visible(timeout=60_000)
    assert page.url.endswith("/chat")

    composer = page.get_by_role("textbox", name="Message")
    composer.fill("I shipped a container pipeline that cut deploy time in half.")
    composer.press("Enter")

    expect(page.get_by_test_id("chat-message-trace")).to_be_visible(timeout=90_000)

    detail = page.request.get(
        f"{API}/interviews/sessions/{interview_session['id']}", headers=api_headers()
    )
    assert detail.ok, detail.text()
    assert detail.json()["rubric_scores"], "the answered question is scored"
