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
