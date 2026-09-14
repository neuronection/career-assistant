"""Plan 78: one chat — CVs as references, builder on demand.

A: Studio → Ask AI opens the NORMAL chat with the CV attached; a question
turn answers grounded in the document (mock provider) with a CV chip.
B: An edit-intent message with the attachment hands the turn to the
builder loop IN THE SAME session (no session re-routing).
"""

import json
import re

from conftest import API, BASE_URL


def _make_cv(page, title: str) -> str:
    created = page.request.post(
        f"{API}/cv",
        data=json.dumps({"title": title}),
        headers={"Content-Type": "application/json"},
    )
    assert created.ok, created.text()
    cv_id = created.json()["id"]
    patched = page.request.patch(
        f"{API}/cv/{cv_id}",
        data=json.dumps(
            {
                "working_content": {
                    "blocks": [
                        {"kind": "header", "props": {}},
                        {
                            "kind": "summary",
                            "props": {"text": "E2E summary marker text"},
                        },
                    ],
                    "overrides": {},
                }
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert patched.ok, patched.text()
    return cv_id


def test_studio_ask_ai_references_cv_in_normal_chat(page) -> None:
    cv_id = _make_cv(page, "E2E Ref CV")

    page.goto(f"{BASE_URL}/cv/{cv_id}")
    page.get_by_test_id("cv-ask-ai").click()

    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)

    # The open CV is suggested in the composer; the pending-attach bridge
    # may already have attached it — either way it rides the message.
    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)
    attached = dock.locator(f'[data-testid="chat-attachment-{cv_id}"]')
    if attached.count() == 0:
        dock.get_by_test_id("chat-attach-cv").click()
        attached.wait_for(state="visible", timeout=10_000)

    composer.fill("which jobs fit this CV?")
    composer.press("Enter")

    # Mock answer: grounded in the title, explicitly read-only.
    page.get_by_text(re.compile("Grounded in your E2E Ref CV")).wait_for(
        state="visible", timeout=60_000
    )
    # Both chips render once the persisted pair lands (post-turn
    # refresh): the user message's attachment chip + the reply's
    # reference chip share the testid.
    chips = page.get_by_test_id(f"cv-ref-chip-{cv_id}")
    chips.first.wait_for(state="visible", timeout=20_000)

    # The session stayed normal — no builder binding (AD1).
    sessions = page.request.get(f"{API}/chat/sessions").json()
    active = next(s for s in sessions if s["id"])
    assert active["context"] is None


def test_edit_intent_hands_off_to_builder_in_same_session(page) -> None:
    cv_id = _make_cv(page, "E2E Build CV")

    page.goto(f"{BASE_URL}/")
    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)
    dock.get_by_role("button", name="New chat").click()
    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)

    dock.get_by_test_id("chat-attach-open").click()
    row = dock.get_by_test_id(f"chat-attach-cv-{cv_id}")
    row.wait_for(state="visible", timeout=10_000)
    row.click()

    composer.fill("rewrite the summary section please")
    composer.press("Enter")

    # The copilot loop runs for THIS turn; the trace (tool cards) renders
    # from the persisted turn once it completes.
    page.get_by_test_id("chat-message-trace").wait_for(
        state="visible", timeout=120_000
    )

    # One session, still normal; the turn ran the builder surface.
    sessions = page.request.get(f"{API}/chat/sessions").json()
    active = next(s for s in sessions if s["id"])
    assert active["context"] is None
    listed = page.request.get(f"{API}/chat/sessions/{active['id']}/messages").json()
    assistant = [m for m in listed if m["role"] == "assistant"][-1]
    assert assistant["metadata_json"]["surface"] == "cv_builder"
