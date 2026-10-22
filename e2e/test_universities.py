"""Universities intake: upload a catalog export → parse → review → apply.

The mock `UNIVERSITY_PARSE` fixture reads the document text: the first
line carrying "university" becomes the institution, "school of"/"faculty
of" lines become departments and a `baseline YYYY: score` clause becomes
an admission baseline. Applying materialises the rows into the catalog
(find-or-create, so the spec is re-runnable).
"""

from conftest import API, BASE_URL, api_headers
from playwright.sync_api import expect

UNIVERSITY = "Sample Technical University"

CATALOG_TEXT = f"""{UNIVERSITY}
School of Computing — baseline 2025: 82.5 quota: 40
Deadline: 2026-07-15
"""


def test_university_catalog_upload_review_and_apply(page) -> None:
    page.goto(f"{BASE_URL}/catalog/universities")
    page.wait_for_selector('[data-testid="universities"]')

    page.set_input_files(
        'input[type="file"]',
        files=[
            {
                "name": "sample-catalog.txt",
                "mimeType": "text/plain",
                "buffer": CATALOG_TEXT.encode("utf-8"),
            }
        ],
    )

    expect(page.get_by_text("sample-catalog.txt")).to_be_visible(timeout=60_000)
    expect(page.get_by_text("parsed", exact=True)).to_be_visible(timeout=120_000)

    page.get_by_role("button", name="Review extraction").click()
    expect(page.get_by_text(UNIVERSITY)).to_be_visible(timeout=20_000)
    expect(page.get_by_text("School of Computing")).to_be_visible()

    page.get_by_role("button", name="Apply to catalog").click()

    card = page.locator("a", has_text=UNIVERSITY).first
    expect(card).to_be_visible(timeout=30_000)
    expect(page.get_by_text("1 department")).to_be_visible()

    documents = page.request.get(f"{API}/documents", headers=api_headers())
    assert documents.ok, documents.text()
    applied = [
        row
        for row in documents.json()
        if row.get("filename") == "sample-catalog.txt" and row.get("status") == "applied"
    ]
    assert applied, "the uploaded document records the applied status"
