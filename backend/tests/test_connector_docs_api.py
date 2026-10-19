"""The connector documentation surface (plan 34 wave 8 — the
``extensionDocsTree`` form served over the admin surface): tree +
markdown per connector, opening on the landing page, traversal-safe,
raw HTML neutralized. Documented connectors (the unification wave's
set: the three job boards + mcp) serve their trees; connectors without
a tree answer with an honest absence page — never a broken surface.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.extensions.docs import landing_file, strip_raw_html
from tests.conftest import register_user

BUILTIN_ROOT = Path(__file__).resolve().parents[1] / "app" / "extensions" / "builtin"


# ------------------------------------------------------------ unit pieces


def test_landing_rule_prefers_the_index_flag() -> None:
    tree = {
        "categories": [
            {"category": "overview", "items": [{"id": "a", "file": "a.md"}]},
            {
                "category": "usage",
                "items": [{"id": "b", "file": "b.md", "index": True}],
            },
        ]
    }
    assert landing_file(tree) == "b.md"


def test_strip_raw_html_neutralizes_tags_but_spares_fences_and_autolinks() -> None:
    page = (
        "# Title\n\n"
        "<script>alert(1)</script>\n\n"
        "```\n<div>inside a fence stays</div>\n```\n\n"
        "See <https://example.org> and `<b>inline code</b>`.\n"
    )
    out = strip_raw_html(page)
    assert "<script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "<div>inside a fence stays</div>" in out
    assert "<https://example.org>" in out
    assert "<b>inline code</b>" in out


# --------------------------------------------------------------- the endpoint


async def test_documentation_opens_on_the_landing_page(client, auth_headers) -> None:
    response = await client.get(
        "/api/v1/admin/postings/connectors/arbeitnow/documentation",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tree"]["version"] == 1
    assert body["markdown"].startswith("# ")
    landing = landing_file(body["tree"])
    assert landing is not None
    page = (BUILTIN_ROOT / "arbeitnow" / "docs" / landing).read_text(encoding="utf-8")
    assert body["markdown"] == strip_raw_html(page)


async def test_documentation_serves_requested_pages(client, auth_headers) -> None:
    response = await client.get(
        "/api/v1/admin/postings/connectors/arbeitnow/documentation",
        params={"file": "usage.md"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["markdown"], "the requested page renders"


async def test_documentation_traversal_is_pinned_to_the_docs_dir(client, auth_headers) -> None:
    response = await client.get(
        "/api/v1/admin/postings/connectors/arbeitnow/documentation",
        params={"file": "../../core/config.py"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    markdown = response.json()["markdown"]
    assert "Could not find file" in markdown
    assert "class Settings" not in markdown


async def test_documentation_404_for_unknown_connectors(client, auth_headers) -> None:
    response = await client.get(
        "/api/v1/admin/postings/connectors/no-such/documentation",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_documentation_honest_absence_without_a_tree(client, auth_headers) -> None:
    """csv + jsonld ship no docs pointer (honest absence — plan 35 wave B
    documented the other seven builtins) — an absence page, not an error."""
    for key in ("csv", "jsonld"):
        response = await client.get(
            f"/api/v1/admin/postings/connectors/{key}/documentation",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["tree"] is None
        assert "No documentation provided" in body["markdown"]


# ------------------------------------------------- page-locale convention


def test_resolve_page_serves_the_default_page_when_no_locale_asked() -> None:
    from app.extensions.docs import resolve_page

    docs_dir = BUILTIN_ROOT / "rss" / "docs"
    tree = json.loads((docs_dir / "docs-tree.json").read_text())
    served_file, served_locale = resolve_page(docs_dir, tree, None, None)
    assert (served_file, served_locale) == ("overview.md", "en")


def test_resolve_page_falls_back_honestly_without_a_sibling(tmp_path: Path) -> None:
    """A requested locale the tree does not note (or that has no sibling)
    serves the default page and SAYS so — never a 404, never a silent
    impersonation (§10.9: best-locale → defaultLocale, honest)."""
    from app.extensions.docs import resolve_page

    docs_dir = BUILTIN_ROOT / "rss" / "docs"
    tree = json.loads((docs_dir / "docs-tree.json").read_text())
    for locale in ("de", "zz"):
        served_file, served_locale = resolve_page(docs_dir, tree, "overview.md", locale)
        assert served_file == "overview.md"
        assert served_locale == "en"


def test_resolve_page_serves_a_noted_sibling(tmp_path: Path) -> None:
    """A noted locale with its sibling serves the sibling and names the
    locale it served (the machinery ships now; bundles ship translated
    pages later — this is the recorded decision's proof)."""
    from app.extensions.docs import resolve_page

    docs_dir = BUILTIN_ROOT / "rss" / "docs"
    tree = json.loads((docs_dir / "docs-tree.json").read_text())
    tree["categories"][0]["items"][0]["locales"] = ["de"]
    (docs_dir / "overview.de.md").write_text("# Übersicht\n\nTest.\n", encoding="utf-8")
    try:
        served_file, served_locale = resolve_page(docs_dir, tree, "overview.md", "de")
        assert served_file == "overview.de.md"
        assert served_locale == "de"
    finally:
        (docs_dir / "overview.de.md").unlink()


async def test_documentation_endpoint_reports_what_it_served(client, auth_headers) -> None:
    """The response carries served_file/served_locale — additive keys;
    the frontend is untouched and keeps reading markdown/tree."""
    response = await client.get(
        "/api/v1/admin/postings/connectors/rss/documentation",
        params={"locale": "de"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["served_file"] == "overview.md"
    assert body["served_locale"] == "en"  # honest fallback, no de sibling ships


def test_mcp_docs_render_the_t3_perimeter_disclosure_verbatim() -> None:
    """The mcp connector's security page embeds the charter's T3
    disclosure verbatim (charter copy is data, not prose) — the serve
    path for the allowlist-gated mcp connector shares arbeitnow's."""
    import json

    charter = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts" / "extension-charter.json").read_text(
            encoding="utf-8"
        )
    )
    page = (BUILTIN_ROOT / "mcp" / "docs" / "security.md").read_text(encoding="utf-8")
    disclosure = str(charter["consent"]["t3PerimeterDisclosure"])
    assert disclosure in page
    assert page.count(disclosure) == 1


async def test_documentation_rides_the_admin_surface(client, auth_headers) -> None:
    """A non-admin session is rejected — the endpoint extends the
    connectors catalog's surface, dependency contract included."""
    fresh = await register_user(client, "docs-reader@example.com", "supersecret1")
    response = await client.get(
        "/api/v1/admin/postings/connectors/arbeitnow/documentation",
        headers=fresh,
    )
    assert response.status_code in (401, 403)
