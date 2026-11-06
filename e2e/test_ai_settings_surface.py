"""Plan 26 uniform AI-settings surface: the automatable portion of the
manual UI pass (Phase 6 closeout).

Covers render + wiring of the family assembly with no live vendor key:
the setup wizard (tiles → guided form → back), the tile set (career's
§15 exposure: the seven offered presets — Anthropic is withheld by the
factory delta, TypeSafe is provisional and never on the tiles), and the
TasksTab Decision group (title, the verbatim §13.5 privacy notice, all
four family slots).

What this deliberately does NOT cover — the real-key flows (fetch-first
validation with classified errors, curated-model persistence, gap-fill
bind rows, rebind pickers, the re-run review) — stays on the owner's
manual checklist: the e2e mock carrier is API-bootstrapped and never
rides the wizard, and no spec here may call a live vendor endpoint.
"""

from conftest import BASE_URL

WIZARD_TILES = [
    "OpenAI",
    "Google Gemini",
    "OpenRouter",
    "TypeSafe",
    "Groq",
    "Mistral",
    "DeepSeek",
    "Ollama (local)",
]
PRIVACY_NOTICE = "Decision models run in the cloud"
DECISION_SLOTS = ["Tool dispatch", "Boolean gate", "Choice", "Score"]


def _open_ai_settings(page) -> None:
    page.goto(f"{BASE_URL}/settings/ai")
    page.wait_for_selector('[data-testid="ai-config"]')


def test_setup_wizard_tiles_and_form_shape(page) -> None:
    _open_ai_settings(page)

    # The wizard opens from the providers tab's primary action.
    page.get_by_role("button", name="Add provider").click()
    dialog = page.get_by_role("dialog")
    dialog.wait_for(state="visible")

    # §15 exposure: the eight offered presets render as equal-weight
    # tiles; Anthropic is withheld (career factory delta, plan 26 §14
    # Phase 4). TypeSafe is docs-verified and tiles normally (the §13.3
    # exposure switch flipped 2026-10-13).
    for tile in WIZARD_TILES:
        dialog.get_by_text(tile, exact=True).wait_for(state="visible")
    assert dialog.get_by_text("Anthropic").count() == 0, "withheld preset leaked to tiles"
    assert dialog.get_by_text("TypeSafe", exact=True).count() >= 1, "decision preset missing from tiles"
    dialog.get_by_text("Set up manually").wait_for(state="visible")

    # Tiles → guided form: preset name, vendor key link, the Advanced
    # disclosure (hosting/country/scope ride inside it; a <details>
    # summary, not a button) — no submit yet: validation is fetch-first
    # against the live vendor.
    dialog.get_by_text("OpenAI", exact=True).click()
    dialog.get_by_text("Set up OpenAI").wait_for(state="visible")
    dialog.get_by_role("link", name="Get a key").wait_for(state="visible")
    advanced = dialog.locator("details summary", has_text="Advanced")
    advanced.wait_for(state="visible")

    # Back returns to the neutral tile grid; the dialog stays open.
    dialog.get_by_role("button", name="Choose another provider").click()
    dialog.get_by_text("Set up manually").wait_for(state="visible")

    dialog.get_by_role("button", name="Close").click()
    dialog.wait_for(state="hidden")


def test_tasks_tab_decision_group_renders(page) -> None:
    _open_ai_settings(page)

    page.get_by_role("tab", name="Tasks").click()
    page.wait_for_selector('[data-testid="tasks-tab"]')
    tab = page.locator('[data-testid="tasks-tab"]')

    # The quiet "Decision kinds" group (retitled by the ADR-0037 uniform
    # shape): the verbatim decision privacy notice rides as the group
    # hint, and all four family slots render
    # (open-args is reserved vocabulary and must never render).
    tab.get_by_text("Decision kinds", exact=True).wait_for(state="visible")
    tab.get_by_text(PRIVACY_NOTICE).wait_for(state="visible")
    for slot in DECISION_SLOTS:
        tab.get_by_text(slot, exact=True).wait_for(state="visible")
    assert tab.get_by_text("open-args").count() == 0, "reserved slot must not render"
    assert tab.get_by_text("Open args").count() == 0, "reserved slot must not render"
