"""CV Studio: create → builder opens with the live preview frame.

The renderer's one-path rule means the preview iframe IS the
export/print path — no server PDF dependency asserted here.
"""

from conftest import BASE_URL, register_via_ui
from playwright.sync_api import expect


def test_cv_studio_create_and_preview(page, credentials) -> None:
    register_via_ui(page, credentials)

    page.goto(f"{BASE_URL}/cv")
    page.wait_for_selector('[data-testid="cv-studio"]')
    page.get_by_test_id("new-cv").click()
    page.get_by_test_id("new-cv-title").fill("E2E Résumé")
    page.get_by_test_id("create-cv").click()

    page.wait_for_selector('[data-testid="preview-frame"]', timeout=30_000)
    assert "/cv/" in page.url


def test_cv_synth_library_empty_state_smoke(page, credentials) -> None:
    """Plan 62: the synth library is reachable from CV Studio and renders
    its empty state for a fresh user (variants arrive via AI generation)."""
    register_via_ui(page, credentials)

    page.goto(f"{BASE_URL}/cv")
    page.wait_for_selector('[data-testid="cv-studio"]')
    page.get_by_test_id("synth-library-link").click()
    page.wait_for_selector('[data-testid="synth-library"]')
    # Auto-waiting assertion: the container mounts before the fetch
    # resolves, so a synchronous is_visible() races the network.
    expect(page.get_by_text("No synthesized variants yet")).to_be_visible(
        timeout=10_000
    )


def test_generate_with_synth_prefer_reuse(page, credentials) -> None:
    """Plan 69: the generate flow reuses an active library variant —
    the toggle shows the match hint, and the drafted CV renders the
    variant's tailored text instead of the profile verbatim."""
    register_via_ui(page, credentials)
    token = page.evaluate("localStorage.getItem('career_token')")
    assert token, "the SPA session stores a bearer token"
    headers = {"Authorization": f"Bearer {token}"}
    api = f"{BASE_URL}/api/v1"

    item = page.request.post(
        f"{api}/me/experience",
        headers=headers,
        data={
            "title": "Backend Intern",
            "kind": "internship",
            "org_name": "Sample Corp",
            "start": "2024-06-01",
            "end": "2024-09-01",
            "description": "Built QA tooling",
            "status": "active",
        },
    )
    assert item.ok, item.text()
    item_id = item.json()["id"]

    draft = page.request.post(
        f"{api}/cv/synth/generate",
        headers=headers,
        data={
            "refs": [{"source_key": "experience", "item_id": item_id}],
            "action": "summarize",
        },
    )
    assert draft.ok, draft.text()
    row = draft.json()["items"][0]
    activate = page.request.patch(
        f"{api}/cv/synth/{row['id']}",
        headers=headers,
        data={"status": "active"},
    )
    assert activate.ok, activate.text()
    tailored_text = row["payload"]["description"]

    page.goto(f"{BASE_URL}/cv?generate=1")
    page.get_by_test_id("cv-generate-advanced").click()
    page.get_by_role("switch", name="Prefer synthesized items").click()
    expect(
        page.get_by_test_id("cv-generate-synth-hint")
    ).to_contain_text("1 of your synthesized variants")

    page.get_by_test_id("cv-generate-submit").click()
    expect(page.get_by_test_id("cv-generate-finished")).to_be_visible(
        timeout=120_000
    )
    expect(page.get_by_test_id("cv-generate-finished")).to_contain_text(
        "1 of your synthesized variants were used"
    )
    page.get_by_test_id("cv-generate-open-finished").click()

    frame_el = page.get_by_test_id("preview-frame")
    srcdoc = ""
    for _ in range(40):
        srcdoc = frame_el.get_attribute("srcdoc") or ""
        if "measurable outcomes" in srcdoc:
            break
        page.wait_for_timeout(500)
    assert tailored_text in srcdoc, (
        "the rendered CV shows the variant's tailored text"
    )


def test_generate_splits_experience_family(page, credentials) -> None:
    """Plan 70: work, projects and volunteering render as three separate
    sections in the generated CV preview."""
    register_via_ui(page, credentials)
    token = page.evaluate("localStorage.getItem('career_token')")
    assert token, "the SPA session stores a bearer token"
    headers = {"Authorization": f"Bearer {token}"}
    api = f"{BASE_URL}/api/v1"

    for kind, title, org, description in (
        ("internship", "Backend Intern", "Sample Corp", "Built QA tooling"),
        ("project", "Campus app", "", "Shipped a campus events app"),
        ("volunteer", "Food bank helper", "Food Bank", "Organized food drives"),
    ):
        made = page.request.post(
            f"{api}/me/experience",
            headers=headers,
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
