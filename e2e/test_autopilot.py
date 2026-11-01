"""Autopilot: create a goal → run it now → the findings workspace.

The mock autopilot planner/curator only see candidates from connected
sources, so the seeded E2E postings are the grounding pack — `E2E00002`
stays unapplied (the tracker journey applies to `E2E00001` first, and the
run's seen/applied exclusions are real behavior). The run is synchronous
(`POST /autopilot/goals/{id}/run`), which lets the spec assert findings
without polling a background job. Plan 175 rebuilt the page as a findings
workspace: a flat feed of job cards, a runs rail on the right (rows with
counts — the run page arrives with the next slice), and the goal
switcher; the inline per-run timeline toggle is gone.
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

    goal_chip = page.get_by_test_id("goal-chip-all")
    expect(page.locator('[data-testid^="goal-chip-"]').filter(has_text=goal_text)).to_be_visible(
        timeout=20_000
    )
    page.locator('[data-testid^="goal-chip-"]').filter(has_text=goal_text).click()
    goal_card = page.locator('[data-testid^="goal-card-"]').first
    expect(goal_card).to_be_visible(timeout=20_000)
    goal_card.locator('[data-testid^="run-now-"]').click()

    # "Found N new matches" (or the quiet variant) — either way the run
    # completed through the graph; findings render when the seeded posting
    # made the shortlist.
    expect(page.get_by_test_id("autopilot-notice")).to_be_visible(timeout=120_000)

    # The workspace: the flat feed renders the finding as a job card with
    # its evidence row, and the runs rail carries the run with counts.
    finding_card = page.locator('[data-testid^="finding-card-"]').first
    expect(finding_card).to_be_visible(timeout=20_000)
    expect(page.locator('[data-testid^="finding-evidence-"]').first).to_be_visible()
    rail_row = page.locator('[data-testid^="runs-rail-row-"]').first
    expect(rail_row).to_be_visible(timeout=20_000)
    expect(rail_row.locator('[data-testid^="runs-rail-counts-"]')).to_contain_text("finding")

    goals = page.request.get(f"{BASE_URL}/api/v1/autopilot/goals", headers=api_headers())
    assert goals.ok, goals.text()
    assert any(goal["goal_text"] == goal_text for goal in goals.json())
