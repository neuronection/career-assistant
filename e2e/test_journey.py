"""Journey: register → rankings → compare tray → /compare → rate.

The one spec that walks the product's core loop end-to-end over the
mock provider; failure here means a user cannot complete the flow.
"""

from conftest import BASE_URL, register_via_ui


def test_register_rank_compare_rate(page, credentials) -> None:
    register_via_ui(page, credentials)

    page.goto(f"{BASE_URL}/rankings")
    page.wait_for_selector('[data-testid="rankings"]')
    first_add = page.locator('[data-testid^="compare-add-"]').first
    first_add.wait_for(state="visible", timeout=30_000)
    first_add.click()

    second_add = page.locator('[data-testid^="compare-add-"]').nth(1)
    second_add.click()

    page.wait_for_selector('[data-testid="compare-tray"]')
    page.get_by_test_id("compare-open").click()
    page.wait_for_selector('[data-testid="compare-table"]')
    assert "/compare?jobs=" in page.url
    assert page.locator('[data-testid^="compare-col-"]').count() == 2

    page.goto(f"{BASE_URL}/rankings")
    page.locator('[data-testid^="compare-add-"]').first.wait_for(
        state="visible", timeout=30_000
    )
    interested = page.get_by_role("button", name="♥ interested").first
    interested.click()
    page.wait_for_timeout(500)
    assert "bg-primary-600" in interested.get_attribute("class")
