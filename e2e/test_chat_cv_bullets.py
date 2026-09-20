"""Plan 107: the chat rewrites an attached CV's bullets — read-grounded
read_cv_items → cv_set_bullets card → approve → the CV carries the
override in the plan-106 canonical shape."""

import json
import re

from conftest import API, BASE_URL


def _make_experience_with_bullet(page) -> None:
    created = page.request.post(
        f"{API}/me/experience",
        data=json.dumps(
            {
                "title": "Bullet Intern",
                "kind": "internship",
                "org_name": "Acme",
                "start": "2025-06-01",
                "open_ended": True,
                "achievements": [{"text": "Original profile bullet"}],
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert created.ok, created.text()


def _make_cv(page, title: str) -> str:
    created = page.request.post(
        f"{API}/cv",
        data=json.dumps({"title": title}),
        headers={"Content-Type": "application/json"},
    )
    assert created.ok, created.text()
    return created.json()["id"]


def test_chat_rewrites_attached_cv_bullets(page) -> None:
    _make_experience_with_bullet(page)
    cv_id = _make_cv(page, "E2E Bullets CV")

    page.goto(f"{BASE_URL}/cv/{cv_id}")
    page.get_by_test_id("cv-ask-ai").click()
    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)
    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)

    attached = dock.locator(f'[data-testid="chat-attachment-{cv_id}"]')
    if attached.count() == 0:
        try:
            dock.get_by_test_id("chat-attach-cv").click(timeout=5_000)
        except Exception:
            pass
    attached.wait_for(state="visible", timeout=10_000)

    composer.fill("update the bullets on this cv")
    composer.press("Enter")

    # The composer remount race can swallow the first Enter (documented
    # in test_chat_cv_reference) — recover the way a user would.
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    user_bubble = page.get_by_text("update the bullets on this cv")
    for _ in range(3):
        try:
            user_bubble.first.wait_for(state="visible", timeout=5_000)
            break
        except PlaywrightTimeoutError:
            if user_bubble.count() == 0:
                composer.fill("update the bullets on this cv")
                composer.press("Enter")
    else:
        if user_bubble.count() == 0:
            composer.fill("update the bullets on this cv")
            composer.press("Enter")
        user_bubble.first.wait_for(state="visible", timeout=5_000)

    cards = page.get_by_test_id("hitl-cards")
    cards.wait_for(state="visible", timeout=60_000)
    card = page.locator(
        '[data-as="hitl-proposal-card"]', has_text=re.compile("Bullets of")
    )
    card.wait_for(state="visible", timeout=20_000)

    cards.get_by_role("button", name="Approve").click()
    page.get_by_text("Approved").wait_for(state="visible", timeout=20_000)

    fetched = page.request.get(f"{API}/cv/{cv_id}")
    assert fetched.ok, fetched.text()
    # Since the two-layer model (plan 107: bullets become variants) the
    # approved rewrite lands as a :bullets synth variant pinned on the
    # CV — never a working_content override.
    pins = (fetched.json().get("context") or {}).get("synth_pins") or {}
    keys = [k for k in pins if k.startswith("experience:") and k.endswith(":bullets")]
    assert keys, "the approved bullets variant pin landed on the CV"
    variant_id = pins[keys[0]]
    variant = page.request.get(f"{API}/cv/synth/{variant_id}")
    assert variant.ok, variant.text()
    achievements = variant.json()["payload"]["achievements"]
    assert achievements == [{"text": "Bullet Intern — tailored for this CV"}]
