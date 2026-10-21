"""Autopilot: create a goal → run it now → findings land on the page.

The mock autopilot planner/curator only see candidates from connected
sources, so the seeded `E2E00001` posting is the grounding pack. The run
is synchronous (`POST /autopilot/goals/{id}/run`), which lets the spec
assert findings without polling a background job.
"""

from conftest import BASE_URL, api_headers
from playwright.sync_api import expect


def test_autopilot_goal_run_returns_findings(page) -> None:
    page.goto(f"{BASE_URL}/autopilot")
    page.wait_for_selector('[data-testid="autopilot-page"]')

    page.get_by_test_id("new-goal").click()
    goal_text = "Find junior devops roles with docker exposure"
    page.get_by_test_id("goal-text").fill(goal_text)
    page.get_by_test_id("goal-save").click()

    goal_card = page.locator('[data-testid^="goal-card-"]').filter(has_text=goal_text).first
    expect(goal_card).to_be_visible(timeout=20_000)

    goal_card.locator('[data-testid^="run-now-"]').click()

    # "Found N new matches" (or the quiet variant) — either way the run
    # completed through the graph; findings render when the seeded posting
    # made the shortlist.
    expect(page.get_by_test_id("autopilot-notice")).to_be_visible(timeout=120_000)

    # Run telemetry: the ledger row expands into the searched-queries timeline.
    toggle = page.locator('[data-testid^="timeline-toggle-"]').first
    expect(toggle).to_be_visible(timeout=20_000)
    toggle.click()
    expect(page.locator('[data-testid^="run-timeline-"]').first).to_be_visible(timeout=20_000)

    goals = page.request.get(f"{BASE_URL}/api/v1/autopilot/goals", headers=api_headers())
    assert goals.ok, goals.text()
    assert any(goal["goal_text"] == goal_text for goal in goals.json())
