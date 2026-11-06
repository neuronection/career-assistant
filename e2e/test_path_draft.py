"""Career-path draft flow (plan 125): chat draft → review → save →
activate → rendered in the /paths explorer. Runs against the mock
provider; the draft is the review artifact."""

from conftest import BASE_URL


def test_chat_path_draft_review_save_activate(page) -> None:
    page.goto(f"{BASE_URL}/")

    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)
    dock.get_by_role("button", name="New chat").click()
    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)
    composer.fill("I want to become a software developer — draft a career path")
    composer.press("Enter")

    # The embedded PathRenderer review card rides the assistant message.
    card = page.get_by_test_id("path-draft-card")
    card.wait_for(state="visible", timeout=90_000)
    preview = card.get_by_test_id("path-renderer")
    preview.wait_for(state="visible", timeout=30_000)

    # Review-first: the save creates a DRAFT path, never an active one.
    card.get_by_test_id("path-draft-save").click()
    card.get_by_test_id("path-draft-saved").wait_for(state="visible", timeout=30_000)

    page.goto(f"{BASE_URL}/paths")
    rail = page.get_by_test_id("paths-rail")
    rail.wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("paths-page").wait_for(state="visible", timeout=20_000)
    draft_item = (
        page.locator('[data-testid^="path-item-"]').filter(has_text="Chat draft").first
    )
    draft_item.wait_for(state="visible", timeout=30_000)
    draft_item.click()

    page.get_by_test_id("path-header").wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("path-renderer").wait_for(state="visible", timeout=20_000)

    # Activate is the owner's review action (never automatic).
    activate = page.get_by_test_id("path-activate")
    activate.wait_for(state="visible", timeout=20_000)
    activate.click()
    page.get_by_text("Active", exact=True).first.wait_for(state="visible", timeout=30_000)

    # The graph discipline renders the saved path (default view).
    page.get_by_test_id("path-view-graph").wait_for(state="visible", timeout=20_000)
