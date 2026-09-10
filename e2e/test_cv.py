"""CV Studio: create → builder opens with the live preview frame.

The renderer's one-path rule means the preview iframe IS the
export/print path — no server PDF dependency asserted here.
"""

from conftest import BASE_URL, register_via_ui


def test_cv_studio_create_and_preview(page, credentials) -> None:
    register_via_ui(page, credentials)

    page.goto(f"{BASE_URL}/cv")
    page.wait_for_selector('[data-testid="cv-studio"]')
    page.get_by_test_id("new-cv").click()
    page.get_by_test_id("new-cv-title").fill("E2E Résumé")
    page.get_by_test_id("create-cv").click()

    page.wait_for_selector('[data-testid="preview-frame"]', timeout=30_000)
    assert "/cv/" in page.url
