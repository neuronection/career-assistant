"""Plan 121 e2e: language switch, overlay approval, draft suppression.

The browser half pins the user-visible contract: switching to German
re-renders the shell in German (and sets `<html lang>`), an AI-drafted
catalog label never renders before approval, and approving it changes the
catalog title on the job page. The locale is reset to English in a
`finally` so the shared e2e user never leaks state into other specs.
"""

from conftest import API, BASE_URL, api_headers


def _set_locale(page, locale: str) -> None:
    response = page.request.put(
        f"{API}/me/locale", data={"locale": locale}, headers=api_headers()
    )
    assert response.ok, response.text()


def test_language_switch_and_overlay_review(page) -> None:
    page.goto(f"{BASE_URL}/settings/account")
    page.get_by_test_id("account-appearance").wait_for(state="visible")

    try:
        page.get_by_test_id("locale-de").click()
        page.wait_for_function(
            "() => document.documentElement.lang === 'de'", timeout=15_000
        )
        page.get_by_text("Einstellungen").first.wait_for(state="visible", timeout=15_000)

        drafted = page.request.post(
            f"{API}/admin/i18n/overlays/draft",
            data={"locale": "de", "entity_kinds": ["job"], "limit": 5},
            headers=api_headers(),
        )
        assert drafted.ok, drafted.text()
        assert drafted.json()["drafted"]["job"] > 0

        queue = page.request.get(
            f"{API}/admin/i18n/overlays?locale=de&status=draft&limit=200",
            headers=api_headers(),
        )
        rows = [row for row in queue.json() if row["entity_kind"] == "job"]
        assert rows, "the draft batch produced job overlays"
        title_row = next(row for row in rows if row["field"] == "label")

        jobs = page.request.get(f"{API}/jobs?page_size=100", headers=api_headers())
        payload = jobs.json()
        job_rows = payload["items"] if isinstance(payload, dict) else payload
        target = next(job for job in job_rows if job["id"] == title_row["entity_id"])
        assert target["title"] == title_row["base_value"], "drafts never render"

        page.goto(f"{BASE_URL}/jobs/{target['code']}")
        base_title = page.get_by_role("heading", name=title_row["base_value"])
        base_title.wait_for(state="visible", timeout=15_000)
        assert page.get_by_text(title_row["value"]).count() == 0, "draft suppressed"

        approved = page.request.post(
            f"{API}/admin/i18n/overlays/{title_row['id']}/approve",
            headers=api_headers(),
        )
        assert approved.ok, approved.text()

        page.reload()
        page.get_by_role("heading", name=title_row["value"]).wait_for(
            state="visible", timeout=15_000
        )
    finally:
        _set_locale(page, "en")
