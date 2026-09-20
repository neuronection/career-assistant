"""HITL profile proposals (plan 77): a chat-proposed edit becomes a
review card, approving applies it, and the experience workspace shows
the result — the full propose → review → apply loop on the mock
provider."""

import json
import re

from conftest import API, BASE_URL


def test_chat_proposes_and_approval_applies(page) -> None:
    page.goto(f"{BASE_URL}/")

    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)

    dock.get_by_role("button", name="New chat").click()
    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)
    composer.fill("Add a project where I built a chatbot")
    composer.press("Enter")

    # The card stack renders once the turn completes (proposal events
    # ride right before `done`, then the persisted metadata takes over).
    cards = page.get_by_test_id("hitl-cards")
    cards.wait_for(state="visible", timeout=60_000)
    card = page.locator('[data-as="hitl-proposal-card"]', has_text=re.compile("Add experience"))
    card.wait_for(state="visible", timeout=10_000)
    assert page.get_by_text("New project").count() >= 1

    cards.get_by_role("button", name="Approve").click()
    page.get_by_text("Approved").wait_for(state="visible", timeout=20_000)

    # Applied through the same service the forms use: the experience
    # workspace lists the approved item.
    page.goto(f"{BASE_URL}/profile/experience")
    page.get_by_text("New project").wait_for(state="visible", timeout=20_000)


def test_destructive_card_requires_confirm(page) -> None:
    """Seed one item, ask to delete it: the card arms a confirm step and
    rejecting keeps the item."""
    response = page.request.post(
        f"{API}/me/experience",
        data=json.dumps(
            {"title": "Keep me", "kind": "project", "open_ended": True}
        ),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()

    page.goto(f"{BASE_URL}/")
    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)
    dock.get_by_role("button", name="New chat").click()
    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)
    composer.fill("delete that project please")
    composer.press("Enter")

    cards = page.get_by_test_id("hitl-cards")
    cards.wait_for(state="visible", timeout=60_000)

    # Destructive: first click arms, nothing applies yet.
    cards.get_by_role("button", name="Approve").click()
    cards.get_by_role("button", name="Confirm delete").wait_for(
        state="visible", timeout=10_000
    )
    cards.get_by_role("button", name="Cancel").click()

    cards.get_by_role("button", name="Reject").click()
    page.get_by_text("Rejected").wait_for(state="visible", timeout=20_000)

    listing = page.request.get(f"{API}/me/experience").json()
    assert any(item["title"] == "Keep me" for item in listing["items"])


def test_anchored_append_preview_and_revert(page) -> None:
    """Plan-99 golden (the OTE-shaped failure, made impossible): the mock
    reads the item first, proposes an ANCHORED append — the existing
    bullet survives in the diff AND the applied item — the preview shows
    the rendered item with the changed span highlighted, and revert
    restores the original description round-trip.
    """
    response = page.request.post(
        f"{API}/me/experience",
        data=json.dumps(
            {
                "title": "Sample data internship",
                "kind": "project",
                "org_name": "Sample Logistics GmbH",
                "open_ended": True,
                "description": "Kept the pipelines healthy.",
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()
    item = response.json()
    assert item["description"] == "Kept the pipelines healthy."

    page.goto(f"{BASE_URL}/")
    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)
    dock.get_by_role("button", name="New chat").click()
    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)
    composer.fill("append a sentence to my experience item")
    composer.press("Enter")

    cards = page.get_by_test_id("hitl-cards")
    cards.wait_for(state="visible", timeout=60_000)
    card = page.locator('[data-as="hitl-proposal-card"]', has_text="Update experience")
    card.wait_for(state="visible", timeout=10_000)
    # Lossless diff: the existing bullet is intact, not replaced.
    assert "Kept the pipelines healthy." in card.inner_text()

    cards.get_by_role("button", name="Approve").click()
    page.get_by_text("Approved").wait_for(state="visible", timeout=20_000)

    listing = page.request.get(f"{API}/me/experience").json()
    applied = next(row for row in listing["items"] if row["id"] == item["id"])
    
    assert "Kept the pipelines healthy." in applied["description"]
    assert "Optimized the nightly batch queries." in applied["description"]

    # Preview from the persisted approved card: rendered after-side with
    # the appended sentence highlighted.
    preview_testid = page.locator(
        "[data-hitl-action='preview']"
    ).first.get_attribute("data-testid")
    page.get_by_test_id(preview_testid).click()
    modal = page.get_by_test_id("hitl-preview-modal")
    modal.wait_for(state="visible", timeout=10_000)
    after = page.get_by_test_id("hitl-preview-after")
    after.wait_for(state="visible", timeout=10_000)
    assert "Kept the pipelines healthy." in after.inner_text()
    assert "Optimized the nightly batch queries." in after.inner_text()
    highlights = after.get_by_test_id("hitl-highlight")
    assert highlights.count() == 1
    assert "Optimized the nightly batch queries." in highlights.first.inner_text()

    # Close the preview before driving the revert row.
    page.keyboard.press("Escape")
    modal.wait_for(state="hidden", timeout=10_000)

    # Revert round-trip through the armed confirm.
    revert = page.get_by_test_id(
        page.locator("[data-testid^='hitl-revert-']")
        .first.get_attribute("data-testid")
    )
    revert.click()
    revert.click()
    page.get_by_text("Reverted").wait_for(state="visible", timeout=20_000)

    listing = page.request.get(f"{API}/me/experience").json()
    reverted = next(row for row in listing["items"] if row["id"] == item["id"])
    assert reverted["description"] == "Kept the pipelines healthy."
    assert "Optimized the nightly batch queries." not in reverted["description"]



def _workspace_chat(page, message: str):
    page.goto(f"{BASE_URL}/")
    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)
    dock.get_by_role("button", name="New chat").click()
    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)
    composer.fill(message)
    composer.press("Enter")
    cards = page.get_by_test_id("hitl-cards")
    cards.wait_for(state="visible", timeout=60_000)
    return cards


def test_variant_card_resolved_labels_and_drafts(page) -> None:
    """Plan-101 golden: a variant ask names its source items in the card
    (no raw uuids), the preview lists the sources before-only, approval
    drafts rows in the Synth Library and there is no revert row."""
    response = page.request.post(
        f"{API}/me/experience",
        data=json.dumps(
            {
                "title": "Sample data internship",
                "kind": "project",
                "org_name": "Sample Logistics GmbH",
                "open_ended": True,
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()

    cards = _workspace_chat(page, "create a variant for my sample data internship")
    variant_card = page.locator(
        '[data-as="hitl-proposal-card"]', has_text="Add CV variants"
    )
    variant_card.wait_for(state="visible", timeout=10_000)
    assert "Sample data internship" in variant_card.inner_text()
    assert "experience:" not in variant_card.inner_text()

    variant_card.get_by_role("button", name="Preview").click()
    modal = page.get_by_test_id("hitl-preview-modal")
    modal.wait_for(state="visible", timeout=10_000)
    sources = page.get_by_test_id("hitl-preview-sources-heading")
    sources.wait_for(state="visible", timeout=10_000)
    row = page.get_by_test_id("hitl-preview-source-projects")
    row.wait_for(state="visible", timeout=10_000)
    assert "Sample data internship" in row.inner_text()
    assert page.get_by_test_id("hitl-preview-variant-note").is_visible()
    page.keyboard.press("Escape")
    modal.wait_for(state="hidden", timeout=10_000)

    # No revert row for variant cards — approve drafts the library rows.
    assert page.locator("[data-testid^='hitl-revert-']").count() == 0
    variant_card.get_by_role("button", name=re.compile("Draft variants")).click()
    page.get_by_text("Activated — see the Synth Library").wait_for(
        state="visible", timeout=20_000
    )

    page.goto(f"{BASE_URL}/cv/synth")
    library = page.get_by_test_id("synth-library")
    library.wait_for(state="visible", timeout=20_000)
    # The library rows load asynchronously — waiting on the container
    # alone races the fetch and reads the "Loading…" placeholder.
    library.get_by_text("Sample data internship").wait_for(
        state="visible", timeout=20_000
    )
    assert "Sample data internship" in library.inner_text()


def test_education_finish_golden(page) -> None:
    """Plan-101 education golden: a scalar patch closes an open-ended
    education entry (card → approve → workspace shows the finished
    date) and the preview renders the school card while the card is
    approved and the revert round-trips."""
    response = page.request.post(
        f"{API}/me/education",
        data=json.dumps(
            {
                "institution": "TU Munich",
                "program": "BSc Informatics",
                "level": "bachelor",
                "in_progress": True,
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()
    entry = response.json()

    cards = _workspace_chat(page, "finish my education entry")
    card = page.locator(
        '[data-as="hitl-proposal-card"]', has_text="Update education"
    )
    card.wait_for(state="visible", timeout=10_000)

    card.get_by_role("button", name="Preview").click()
    modal = page.get_by_test_id("hitl-preview-modal")
    modal.wait_for(state="visible", timeout=10_000)
    before = page.get_by_test_id("hitl-preview-before")
    before.wait_for(state="visible", timeout=10_000)
    assert "TU Munich" in before.inner_text()
    page.keyboard.press("Escape")
    modal.wait_for(state="hidden", timeout=10_000)

    card.get_by_role("button", name="Approve").click()
    page.get_by_text("Approved").wait_for(state="visible", timeout=20_000)

    listing = page.request.get(f"{API}/me/education").json()
    applied = next(row for row in listing if row["id"] == entry["id"])
    assert applied["in_progress"] is False
    assert applied["end"] == "2026-07-31"

    revert = page.get_by_test_id(
        page.locator("[data-testid^='hitl-revert-']")
        .first.get_attribute("data-testid")
    )
    revert.click()
    revert.click()
    page.get_by_text("Reverted").wait_for(state="visible", timeout=20_000)

    listing = page.request.get(f"{API}/me/education").json()
    reverted = next(row for row in listing if row["id"] == entry["id"])
    assert reverted["in_progress"] is True
    assert reverted["end"] is None
