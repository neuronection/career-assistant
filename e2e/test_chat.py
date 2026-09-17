"""Chat: one streamed turn through the mock provider.

Proves the SSE contract end-to-end on the docked surface (the plan-75
default; the bubble is opt-in via the view switcher) — same provider,
session store and transport as the other shapes.
"""

from conftest import BASE_URL


def test_chat_streamed_turn_docked(page) -> None:
    page.goto(f"{BASE_URL}/")

    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)

    # Fresh session so the composer mounts (the surface shows the
    # session picker until a session is active).
    dock.get_by_role("button", name="New chat").click()
    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)
    composer.fill("What jobs fit someone who likes data?")
    composer.press("Enter")

    # The persisted trace block renders only after the turn completes —
    # the strongest signal that validate → persist → audit all ran.
    page.wait_for_selector('[data-testid="chat-message-trace"]', timeout=60_000)


def test_chat_bubble_is_opt_in_via_switcher(page) -> None:
    """Plan 75 + the plan-98 switcher contract: docked is the default
    surface; the popup button is an explicit open gesture (the floating
    window expands immediately — the launcher FAB's label is the close
    label while it is open), and the bubble panel's header actions stay
    mouse-clickable (the old overlaid-close regression)."""
    page.goto(f"{BASE_URL}/")

    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)
    assert page.get_by_test_id("chat-widget").count() == 0

    dock.get_by_test_id("chat-view-popup").click()
    panel = page.get_by_role("complementary", name="Open chat assistant")
    panel.wait_for(state="visible", timeout=20_000)
    # The regression guard: the header's "New chat" must be mouse-clickable
    # (the old overlaid close intercepted the click right here).
    panel.get_by_role("button", name="New chat").click(timeout=10_000)

    panel.get_by_role("button", name="Close panel").click()
    panel.wait_for(state="detached", timeout=10_000)
    # Closing hands the conversation back to the collapsed launcher FAB.
    page.get_by_role("button", name="Open chat assistant").wait_for(
        state="visible", timeout=10_000
    )
