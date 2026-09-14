"""CV Studio: create → builder opens with the live preview frame.

The renderer's one-path rule means the preview iframe IS the
export/print path — no server PDF dependency asserted here.
"""

from conftest import BASE_URL, API
from playwright.sync_api import expect


def test_cv_studio_create_and_preview(page) -> None:
    page.goto(f"{BASE_URL}/cv")
    page.wait_for_selector('[data-testid="cv-studio"]')
    page.get_by_test_id("new-cv").click()
    page.get_by_test_id("new-cv-title").fill("E2E Résumé")
    page.get_by_test_id("create-cv").click()

    page.wait_for_selector('[data-testid="preview-frame"]', timeout=30_000)
    assert "/cv/" in page.url


def test_cv_synth_library_empty_state_smoke(page) -> None:
    """Plan 62: the synth library is reachable from CV Studio and renders
    its empty state for a pristine workspace (variants arrive via AI
    generation; the conftest reset guarantees the emptiness)."""
    page.goto(f"{BASE_URL}/cv")
    page.wait_for_selector('[data-testid="cv-studio"]')
    page.get_by_test_id("synth-library-link").click()
    page.wait_for_selector('[data-testid="synth-library"]')
    # Auto-waiting assertion: the container mounts before the fetch
    # resolves, so a synchronous is_visible() races the network.
    expect(page.get_by_text("No synthesized variants yet")).to_be_visible(
        timeout=10_000
    )


# Synth-variant reuse at generate time was replaced by explicit
# builder-side pins (`synth_pins`, plan 72) — the generate flow no longer
# reuses active variants implicitly. The pin behavior is covered by
# frontend/src/tests/cvStudio.test.tsx ("pins a variant per item...");
# generate → builder navigation stays covered by the spec below.


def test_generate_splits_experience_family(page) -> None:
    """Plan 70: work, projects and volunteering render as three separate
    sections in the generated CV preview."""
    for kind, title, org, description in (
        ("internship", "Backend Intern", "Sample Corp", "Built QA tooling"),
        ("project", "Campus app", "", "Shipped a campus events app"),
        ("volunteer", "Food bank helper", "Food Bank", "Organized food drives"),
    ):
        made = page.request.post(
            f"{API}/me/experience",
            data={
                "title": title,
                "kind": kind,
                "org_name": org,
                "start": "2024-06-01",
                "end": "2024-09-01",
                "description": description,
                "status": "active",
            },
        )
        assert made.ok, made.text()

    page.goto(f"{BASE_URL}/cv?generate=1")
    page.get_by_test_id("cv-generate-submit").click()
    # No synth contribution → the flow navigates straight to the builder
    # (the finished screen only appears when the library contributed).
    frame_el = page.get_by_test_id("preview-frame")
    expect(frame_el).to_be_visible(timeout=120_000)
    srcdoc = ""
    for _ in range(40):
        srcdoc = frame_el.get_attribute("srcdoc") or ""
        if "Work Experience" in srcdoc and "Projects" in srcdoc:
            break
        page.wait_for_timeout(500)
    assert "Work Experience" in srcdoc, "the work section renders"
    assert "Projects" in srcdoc, "the projects section renders"
    assert "Volunteering" in srcdoc, "the volunteering section renders"
    assert srcdoc.index("Work Experience") < srcdoc.index("Projects") < (
        srcdoc.index("Volunteering")
    ), "the three sections render as separate headings"
