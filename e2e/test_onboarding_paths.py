"""Onboarding start paths: the hero picker resolves WHY the user came and
each path opens its own wizard shape.

`target` hands over to the express intake, `explore` opens the shared
profile-section wizard, and `browse` is the skip path that lands on the
dashboard. The stored path is reset through the API before each assertion
so the spec is independent of the path a previous run stored (a stored
`target` path redirects straight to the express page, never the picker).
"""

from conftest import API, BASE_URL, api_headers
from playwright.sync_api import expect


def _reset_path(page) -> None:
    response = page.request.put(
        f"{API}/me/onboarding-path", data={"path": None}, headers=api_headers()
    )
    assert response.ok, response.text()


def _open_picker(page) -> None:
    _reset_path(page)
    page.goto(f"{BASE_URL}/onboarding")
    expect(page.get_by_test_id("path-picker")).to_be_visible(timeout=30_000)


def test_onboarding_paths(page) -> None:
    _open_picker(page)
    expect(page.get_by_test_id("path-hero")).to_be_visible()

    page.get_by_test_id("path-explore").click()
    expect(page.get_by_test_id("onboarding")).to_be_visible(timeout=30_000)
    expect(page.get_by_test_id("step-content")).to_be_visible()
    expect(page.get_by_test_id("change-start")).to_be_visible()

    _open_picker(page)
    page.get_by_test_id("path-target").click()
    expect(page.get_by_test_id("express-onboarding")).to_be_visible(timeout=30_000)
    expect(page.get_by_test_id("express-query")).to_be_visible()

    _open_picker(page)
    page.get_by_test_id("path-browse").click()
    expect(page.get_by_test_id("path-picker")).to_be_hidden(timeout=30_000)
    assert page.url.rstrip("/") == BASE_URL.rstrip("/")
