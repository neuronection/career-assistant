"""Applications (plan 116): the tracker journey — track a posting, nudge
configuration, stage moves and the dashboard funnel — plus a chat
confirmation card resolving a stage change."""

import json
import re

from conftest import API, BASE_URL, api_headers


def _posting(page) -> dict:
    listing = page.request.get(f"{API}/postings", headers=api_headers()).json()
    return next(item for item in listing["items"] if item.get("ref") == "E2E00001")


def _track(page) -> dict:
    posting = _posting(page)
    response = page.request.post(
        f"{API}/me/applications",
        data=json.dumps(
            {
                "posting_id": posting["id"],
                "applied_via": "url",
                "applied_via_url": posting.get("url") or "",
            }
        ),
        headers=api_headers({"Content-Type": "application/json"}),
    )
    assert response.ok, response.text()
    return response.json()


def test_tracker_journey_apply_nudge_interview_offer(page) -> None:
    application = _track(page)
    app_id = application["id"]

    page.goto(f"{BASE_URL}/applications")
    page.wait_for_selector('[data-testid="applications-board"]')
    card = page.get_by_test_id(f"application-card-{app_id}")
    card.wait_for(state="visible", timeout=20_000)

    # Nudge configuration: the follow-up block writes a new cadence.
    page.get_by_test_id("applications-followup-settings").click()
    page.get_by_test_id("followup-rules").wait_for(state="visible", timeout=20_000)
    day = page.get_by_test_id("followup-cadence-day-0")
    day.fill("2")
    page.get_by_test_id("followup-rules-save").click()
    page.get_by_test_id("followup-rules-saved").wait_for(state="visible", timeout=20_000)
    page.keyboard.press("Escape")

    card.click()
    drawer = page.get_by_test_id("application-drawer-body")
    drawer.wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("application-event-stage_change").first.wait_for(
        state="visible", timeout=20_000
    )

    page.get_by_test_id("application-note-input").fill("Recruiter call booked")
    page.get_by_test_id("application-note-save").click()
    page.get_by_test_id("application-event-note").first.wait_for(
        state="visible", timeout=20_000
    )

    page.get_by_test_id("application-stage-select").select_option("interview")
    page.get_by_test_id("application-stage-save").click()
    page.get_by_test_id("application-drawer-stage").filter(
        has_text=re.compile("Interview")
    ).wait_for(state="visible", timeout=20_000)

    page.get_by_test_id("application-stage-select").select_option("offer")
    page.get_by_test_id("application-stage-save").click()
    page.get_by_test_id("application-drawer-stage").filter(
        has_text=re.compile("Offer")
    ).wait_for(state="visible", timeout=20_000)

    detail = page.request.get(
        f"{API}/me/applications/{app_id}", headers=api_headers()
    ).json()
    assert detail["stage"] == "offer"
    assert [event["stage_to"] for event in detail["timeline"] if event["kind"] == "stage_change"] == [
        "applied",
        "interview",
        "offer",
    ]

    # Dashboard funnel reflects the pipeline.
    page.goto(f"{BASE_URL}/")
    page.wait_for_selector('[data-testid="applications-widget"]', timeout=30_000)
    page.get_by_test_id("funnel-interviewing").wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("funnel-offers").wait_for(state="visible", timeout=20_000)


def test_chat_stage_change_resolves_through_a_confirmation_card(page) -> None:
    application = _track(page)

    page.goto(f"{BASE_URL}/")
    dock = page.get_by_test_id("chat-dock")
    dock.wait_for(state="visible", timeout=20_000)
    dock.get_by_role("button", name="New chat").click()
    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)
    composer.fill("Move my application to interview")
    composer.press("Enter")

    cards = page.get_by_test_id("hitl-cards")
    cards.wait_for(state="visible", timeout=60_000)
    card = page.locator('[data-as="hitl-proposal-card"]').first
    card.wait_for(state="visible", timeout=10_000)

    before = page.request.get(
        f"{API}/me/applications/{application['id']}", headers=api_headers()
    ).json()
    assert before["stage"] == "applied", "nothing applies before approval"

    cards.get_by_role("button", name="Approve").first.click()
    page.get_by_text("Approved", exact=True).first.wait_for(
        state="visible", timeout=20_000
    )

    after = page.request.get(
        f"{API}/me/applications/{application['id']}", headers=api_headers()
    ).json()
    assert after["stage"] == "interview"
    assert after["timeline"][0]["actor"] == "assistant"
