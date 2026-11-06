"""Plan 195 responsive gate: the Market intelligence workspace at every
supported window size, with the chat dock open and closed.

Pins the contract the plan calls out: no horizontal body scroll at any
band (360/390/640/768/1024/1440/1920), a screenshot per tab, the compact
Filters sheet instead of the inline bar, and an axe run at 390 and 1440.
The pywebview desktop minimum is 640×480 — a real product size here.

Note on the chat dock: below 1024 px the global dock is a full-screen
drawer (`max-lg:fixed inset-0`), so the page behind it is not
interactable — an app-wide shell behavior, not this page's. The
interaction matrix therefore runs with the dock closed, and the dock-open
cases assert layout/scroll at ≥1024 where it is a side panel (plus
scroll-only at the small sizes).
"""

import os
from pathlib import Path

import pytest

from conftest import BASE_URL

SHOTS = Path(os.environ.get("E2E_MARKET_SHOTS", "/tmp/e2e-market-intelligence"))
AXE = Path(__file__).resolve().parents[1] / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
TABS = ("overview", "demand", "skills", "pay", "companies")
VIEWPORTS = (
    (360, 640),
    (390, 844),
    (640, 480),
    (768, 1024),
    (1024, 768),
    (1440, 900),
    (1920, 1080),
)


def _no_horizontal_scroll(page) -> None:
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 0, f"horizontal body scroll: {overflow}px"


def _open_market(page, *, chat: str = "closed") -> None:
    if chat == "closed":
        page.add_init_script("localStorage.setItem('ca:chat:mode','bubble')")
    page.goto(f"{BASE_URL}/postings/stats")
    page.get_by_test_id("market-stats").wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("market-stats-tabpanel-overview").wait_for(
        state="visible", timeout=20_000
    )


def _axe(page) -> list[str]:
    # The app ships a strict `script-src 'self'` CSP: serve axe from a
    # same-origin route instead of injecting inline script.
    page.route(
        "**/__e2e_axe.js",
        lambda route: route.fulfill(path=str(AXE), content_type="application/javascript"),
    )
    page.add_script_tag(url=f"{BASE_URL}/__e2e_axe.js")
    result = page.evaluate(
        """async () => {
            const root = document.querySelector("[data-testid='market-stats']");
            return await axe.run(root ?? document, {rules: {
                region: {enabled: false},
                'landmark-one-main': {enabled: false},
            }});
        }"""
    )
    return [
        f"{violation['id']}: {violation['help']} :: "
        + ", ".join(
            node["target"][0] if isinstance(node.get("target"), list) else str(node.get("target"))
            for node in violation["nodes"]
        )
        for violation in result["violations"]
    ]


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_market_intelligence_fits_every_window(page, width: int, height: int) -> None:
    page.set_viewport_size({"width": width, "height": height})
    _open_market(page)
    _no_horizontal_scroll(page)

    SHOTS.mkdir(parents=True, exist_ok=True)
    for tab in TABS:
        page.get_by_test_id(f"market-stats-tab-{tab}").click()
        page.get_by_test_id(f"market-stats-tabpanel-{tab}").wait_for(state="visible")
        _no_horizontal_scroll(page)
        page.evaluate(
            """() => document
                .querySelector("[data-testid^='market-stats-tabpanel-']")
                ?.scrollIntoView({block: 'start'})"""
        )
        page.screenshot(path=str(SHOTS / f"{width}x{height}-{tab}.png"))

    assert page.get_by_test_id("stats-copy-link").is_visible()
    assert page.get_by_test_id("stats-export").is_visible()


@pytest.mark.parametrize(("width", "height"), ((390, 844), (1440, 900)))
def test_market_intelligence_has_no_axe_violations(page, width: int, height: int) -> None:
    page.set_viewport_size({"width": width, "height": height})
    _open_market(page)
    violations = _axe(page)
    assert violations == []


@pytest.mark.parametrize(
    ("width", "height", "interactive"),
    ((360, 640, False), (640, 480, False), (1024, 768, True), (1440, 900, True)),
)
def test_market_intelligence_with_the_chat_dock_open(
    page, width: int, height: int, interactive: bool
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    _open_market(page, chat="open")
    page.get_by_test_id("chat-dock").wait_for(state="visible", timeout=10_000)
    _no_horizontal_scroll(page)
    if interactive:
        page.get_by_test_id("market-stats-tab-demand").click()
        page.get_by_test_id("market-stats-tabpanel-demand").wait_for(state="visible")
        _no_horizontal_scroll(page)


def test_market_intelligence_compact_uses_the_filter_sheet(page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    _open_market(page)
    button = page.get_by_test_id("market-stats-filters-button")
    button.wait_for(state="visible")
    button.click()
    dialog = page.get_by_role("dialog")
    dialog.wait_for(state="visible")
    page.get_by_test_id("market-stats-filter-q").wait_for(state="visible")
    page.get_by_test_id("market-stats-sheet-apply").click()
    dialog.wait_for(state="hidden")


def test_market_intelligence_drill_carries_the_view(page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/postings/stats?window=30d&basis=all")
    page.get_by_test_id("market-stats-tabpanel-overview").wait_for(state="visible")
    page.get_by_test_id("market-stats-tab-demand").click()
    page.locator("[data-testid^='stats-breakdown-row-']").first.click()
    page.wait_for_url("**/postings?**")
    assert "posted_within=30d" in page.url
    assert "basis=all" in page.url
    assert "source=" in page.url


def test_market_intelligence_payload_has_one_as_of(page) -> None:
    _open_market(page)
    payload = page.evaluate(
        """async () => {
            const response = await fetch('/api/v1/postings/stats/dashboard?cards=summary,overview,skills', {
                headers: {'X-Profile-Id': localStorage.getItem('ca-profile-id') || ''},
            });
            return {status: response.status, cache: response.headers.get('cache-control'), body: await response.json()};
        }"""
    )
    assert payload["status"] == 200
    assert payload["cache"] == "private, no-store"
    body = payload["body"]
    assert body["as_of"] == body["summary"]["as_of"] == body["overview"]["as_of"]
