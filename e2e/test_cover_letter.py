"""Cover letters: posting detail → letter builder → brief → AI draft → apply.

The mock provider serves the deterministic CV_COVER_LETTER fixture, so the
paragraphs are stable: the first two rest on evidence and the third is
flagged. Applying keeps only the chosen (verified) paragraphs.
"""

from conftest import BASE_URL
from playwright.sync_api import expect


def test_cover_letter_from_posting_to_ai_draft(page) -> None:
    page.goto(f"{BASE_URL}/postings/feed")
    page.wait_for_selector('[data-testid="postings"]')
    details = page.get_by_test_id("posting-details").first
    details.wait_for(state="visible", timeout=30_000)
    details.click()

    page.wait_for_selector('[data-testid="posting-detail"]')
    page.get_by_test_id("draft-cover-letter").click()

    expect(page.get_by_test_id("letter-brief")).to_be_visible(timeout=30_000)
    expect(page.get_by_test_id("preview-frame")).to_be_visible(timeout=30_000)

    page.get_by_test_id("draft-letter").click()
    slideover = page.get_by_test_id("letter-slideover")
    expect(slideover).to_be_visible(timeout=120_000)
    expect(slideover.get_by_test_id("letter-paragraph-0")).to_be_visible()

    page.get_by_test_id("apply-letter-draft").click()
    expect(slideover).to_be_hidden(timeout=30_000)

    frame = page.get_by_test_id("preview-frame")
    drafted = ""
    for _ in range(40):
        srcdoc = frame.get_attribute("srcdoc") or ""
        if "letter" in srcdoc and "Dear" in srcdoc:
            drafted = srcdoc
            break
        page.wait_for_timeout(500)
    assert "Dear" in drafted, "the applied letter body renders in the preview"
