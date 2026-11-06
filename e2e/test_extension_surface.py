"""E2E: the declarative extension surface (plan 32 Phase 4 / ADR-0040
clause 16). The reference CV-utility mini-app is imported through the
real Phase-3 pipeline (local git source = the sibling template repo),
consented as T0, enabled — and then RENDERED in the browser: the routed
page is the career host's JavaScript SurfaceRenderer consuming the
backend's render view. DOM-structure assertions prove the SAME manifest
renders host-side (no raw extension markup ever mounts)."""

import json
import subprocess

import pytest
from playwright.sync_api import Page

from conftest import API, BASE_URL, api_headers

TEMPLATE_REPO_REL = "../../career-connector-template"
MINIAPP_ID = "career-cv-gallery"


def _api_call(page: Page, method: str, path: str, payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = api_headers()
    if body:
        headers = {**headers, "Content-Type": "application/json"}
    request = page.request.fetch(
        f"{API}{path}",
        method=method,
        data=body,
        headers=headers,
        timeout=30_000,
    )
    return request


def _import_gallery(page: Page) -> str:
    """Source → sync → consent install → enable. Returns the install id."""
    from pathlib import Path

    repo = (Path(__file__).resolve().parent / TEMPLATE_REPO_REL).resolve()
    if not (repo / "manifest.json").is_file():
        pytest.skip("sibling template repo not checked out")
    subprocess.run(
        ["git", "-C", str(repo), "add", "."],
        check=False,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "gallery import", "--allow-empty"],
        check=False,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "e2e",
            "GIT_AUTHOR_EMAIL": "e2e@example.com",
            "GIT_COMMITTER_NAME": "e2e",
            "GIT_COMMITTER_EMAIL": "e2e@example.com",
            "HOME": str(repo.parent),
        },
    )
    branch = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() or "main"
    created = _api_call(
        page,
        "POST",
        "/admin/extensions/sources",
        {
            "descriptor": {
                "local": {"path": str(repo)},
                "ref": {"strategy": "branch", "value": branch},
            }
        },
    )
    if created.status != 201:
        already = created.text()
        if "already exists" in already:
            listed = _api_call(page, "GET", "/admin/extensions/sources")
            [source] = [
                s for s in listed.json() if "template" in (s.get("origin") or "")
            ]
        else:
            pytest.fail(f"source add failed: {already}")
    else:
        source = created.json()
    source_id = source["id"]

    sync = _api_call(page, "POST", f"/admin/extensions/sources/{source_id}/sync")
    assert sync.status == 200, sync.text()
    report = sync.json()
    assert report.get("ok") is not False, report
    preview = _api_call(
        page,
        "GET",
        f"/admin/extensions/sources/{source_id}/preview/{MINIAPP_ID}",
    )
    assert preview.status == 200, preview.text()
    installed = _api_call(
        page,
        "POST",
        f"/admin/extensions/sources/{source_id}/install",
        {"extension_id": MINIAPP_ID, "consent": preview.json()["echo"]},
    )
    assert installed.status == 201, installed.text()
    install = installed.json()
    assert install["tier"] == "T0", install
    enabled = _api_call(
        page, "POST", f"/admin/extensions/installs/{install['id']}/enabled", {"enabled": True}
    )
    assert enabled.status == 200, enabled.text()
    return install["id"]


def test_career_renders_the_same_mini_app_production_page(page: Page, clean_workspace):
    """The live render: nav from the sidebar, page DOM structure, evidence
    drilldown, typed actions, then the kill switch pulls the route."""
    install_id = _import_gallery(page)

    cards = _api_call(page, "GET", "/extensions/surfaces").json()
    assert [c["extensionId"] for c in cards] == [MINIAPP_ID]
    card = cards[0]
    assert card["surfaces"]["honored"] == ["page", "panel"]
    assert card["surfaces"]["degrades"] == {"window": "page"}
    assert card["routes"] == f"/extensions/{MINIAPP_ID}"

    page.goto(f"{BASE_URL}/extensions/{MINIAPP_ID}")
    surface = page.locator('[data-testid="surface"]')
    surface.wait_for()
    assert page.locator('[data-testid="surface-status"]').inner_text() != ""
    rows = page.locator('[data-testid^="surface-row-"]')
    assert rows.count() >= 4, "the gallery cards render from the manifest data"
    assert page.locator('[data-testid^="surface-evidence-"]').count() >= 1
    # no extension markup ever mounts (D17)
    assert page.locator('[data-testid="surface"] script').count() == 0
    assert page.locator('[data-testid="surface"] iframe').count() == 0
    assert page.locator('[data-testid="surface"] img').count() == 0

    # a host-side degrade chip records the declined window surface
    assert page.locator('[data-testid="surface-degrade-chip"]').count() == 1

    # typed action binding: item:open leaves for the CV studio
    page.locator('[data-testid^="surface-action-item:open-"]').first.click()
    page.wait_for_url("**/cv")

    # the kill switch pulls the route (disable → registry + page die)
    disabled = _api_call(
        page,
        "POST",
        f"/admin/extensions/installs/{install_id}/enabled",
        {"enabled": False},
    )
    assert disabled.status == 200
    try:
        assert (
            _api_call(page, "GET", "/extensions/surfaces").json() == []
        )
        page.goto(f"{BASE_URL}/extensions/{MINIAPP_ID}")
        page.locator('[data-testid="surface-page-missing"]').wait_for()
    finally:
        reenabled = _api_call(
            page,
            "POST",
            f"/admin/extensions/installs/{install_id}/enabled",
            {"enabled": True},
        )
        assert reenabled.status == 200
