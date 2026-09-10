"""Template design system: themes, tokens, date formats, card style."""

import pytest
from pydantic import ValidationError

from app.services.cv_renderer import format_period, render_cv
from app.schemas.cv_template import TemplateContent


def _content(**design) -> TemplateContent:
    return TemplateContent.model_validate(
        {
            "blocks": [
                {"kind": "header"},
                {
                    "kind": "items",
                    "props": {
                        "title": "Experience",
                        "source_key": "experience",
                        "date_format": "iso",
                        "show_org": True,
                    },
                },
            ],
            "design": design,
        }
    )


async def test_themes_endpoint_lists_predefined_sets(client, auth_headers):
    response = await client.get("/api/v1/cv/templates/themes", headers=auth_headers)
    assert response.status_code == 200, response.text
    themes = response.json()
    assert len(themes) >= 6
    cobalt = next(theme for theme in themes if theme["key"] == "cobalt_cards")
    assert cobalt["design"]["section_style"] == "card"
    assert cobalt["accent_color"].startswith("#")


def test_date_formats():
    assert format_period("2024-06", "2025-01", "mon_yyyy") == "Jun 2024 – Jan 2025"
    assert format_period("2024-06", None, "iso") == "2024-06"
    assert format_period("2024-06", None, "eu") == "06/2024"
    assert format_period("2024-06", None, "year") == "2024"


async def test_card_style_radius_and_heading_tokens():
    content = _content(
        section_style="card",
        corner_radius=4,
        heading_case="title",
        heading_weight=700,
        accent_color="#0f766e",
    )
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    html = render_cv(content, SAMPLE_SNAPSHOT).html
    assert "class='cv-block cv-card'" in html
    assert "border-radius: 4mm" in html
    assert "font-weight: 700" in html
    assert "capitalize" in html
    assert "#0f766e" in html


async def test_flat_default_has_no_cards():
    content = _content()
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    html = render_cv(content, SAMPLE_SNAPSHOT).html
    assert "class='cv-block cv-card'" not in html


@pytest.mark.parametrize(
    ("density", "margin_mm"),
    [("compact", 8), ("normal", 12), ("roomy", 16)],
)
def test_page_margin_mirrored_in_screen_media(density, margin_mm):
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    html = render_cv(_content(density=density), SAMPLE_SNAPSHOT).html
    assert f"@page {{ size: 210mm 297mm; margin: {margin_mm}mm; }}" in html
    screen = html.split("@media screen", 1)[1]
    assert f"padding: {margin_mm}mm" in screen
    assert "width: 210mm" in screen
    assert "min-height: 297mm" in screen


def test_template_margin_override_beats_density():
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    html = render_cv(_content(density="roomy", margin_mm=5), SAMPLE_SNAPSHOT).html
    assert "@page { size: 210mm 297mm; margin: 5mm; }" in html
    assert "padding: 5mm" in html.split("@media screen", 1)[1]


def test_margin_mm_out_of_bounds_rejected():
    with pytest.raises(ValidationError):
        _content(margin_mm=30)
    with pytest.raises(ValidationError):
        _content(margin_mm=-1)


def test_margin_override_feeds_pagination_heuristic():
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    zero = render_cv(_content(margin_mm=0), SAMPLE_SNAPSHOT)
    default = render_cv(_content(), SAMPLE_SNAPSHOT)
    assert zero.metrics.lines_per_page > default.metrics.lines_per_page


def test_contact_fields_are_links_and_schemes_are_allowlisted():
    import copy

    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    snapshot = copy.deepcopy(SAMPLE_SNAPSHOT)
    snapshot["basics"]["links"] = [
        {"kind": "website", "url": "https://alexsample.dev", "label": "portfolio"},
        {"kind": "website", "url": "javascript:alert(1)", "label": "evil"},
    ]
    html = render_cv(_content(), snapshot).html
    assert 'href="mailto:alex@example.com"' in html
    assert 'href="tel:+305550100"' in html
    assert ">alex@example.com</a>" in html
    assert ">+30 555 0100</a>" in html
    assert 'href="https://alexsample.dev"' in html
    assert 'href="javascript:' not in html
    assert ">evil</span>" in html


async def test_custom_text_inline_markup_is_escaped():
    content = TemplateContent.model_validate(
        {
            "blocks": [
                {
                    "kind": "custom_text",
                    "props": {
                        "title": "Note",
                        "text": "**bold** and *italic* <script>x</script>",
                    },
                }
            ]
        }
    )
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    html = render_cv(content, SAMPLE_SNAPSHOT).html
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert "&lt;script&gt;" in html and "<script>" not in html


def test_custom_text_paragraphs_bullets_and_links():
    content = TemplateContent.model_validate(
        {
            "blocks": [
                {
                    "kind": "custom_text",
                    "props": {
                        "title": "About me",
                        "text": (
                            "Curious **engineer** from Athens.\n"
                            "- *Ships* fast\n"
                            "- Loves [Python](https://python.org)\n"
                            "\n"
                            "Reach me at [me@mail.com](mailto:me@mail.com)\n"
                            "No [x](javascript:alert(1)) injection"
                        ),
                    },
                }
            ]
        }
    )
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    html = render_cv(content, SAMPLE_SNAPSHOT).html
    assert "<p>Curious <strong>engineer</strong> from Athens.</p>" in html
    assert "<ul><li><em>Ships</em> fast</li>" in html
    assert '<li>Loves <a href="https://python.org">Python</a></li></ul>' in html
    assert '<a href="mailto:me@mail.com">me@mail.com</a>' in html
    assert 'href="javascript:' not in html
    assert "No [x](javascript:alert(1)) injection" in html


def test_custom_text_blank_is_skipped_and_validates_empty():
    content = TemplateContent.model_validate(
        {
            "blocks": [
                {"kind": "custom_text", "props": {"title": "About me", "text": ""}},
                {"kind": "custom_text", "props": {"title": "About me"}},
            ]
        }
    )
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    result = render_cv(content, SAMPLE_SNAPSHOT)
    assert "About me" not in result.html
    assert result.metrics.empty_blocks == ["custom_text", "custom_text"]


async def test_preview_draft_renders_unsaved_content(client, auth_headers):
    response = await client.post(
        "/api/v1/cv/templates/preview-draft",
        json={
            "content": {
                "blocks": [{"kind": "header"}, {"kind": "skills"}],
                "design": {"accent_color": "#b45309"},
            }
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert "#b45309" in response.text

    bad = await client.post(
        "/api/v1/cv/templates/preview-draft",
        json={"content": {"blocks": [{"kind": "nope"}]}},
        headers=auth_headers,
    )
    assert bad.status_code == 400


def test_sidebar_layout_renders_two_columns():
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    content = TemplateContent.model_validate(
        {
            "blocks": [
                {"kind": "header"},
                {"kind": "skills", "column": "sidebar"},
                {
                    "kind": "items",
                    "props": {"title": "Experience", "source_key": "experience"},
                },
            ],
            "design": {"layout": "sidebar", "sidebar_color": "#16324f"},
        }
    )
    html = render_cv(content, SAMPLE_SNAPSHOT).html
    assert "class='cv-columns'" in html and "class='cv-sidebar'" in html
    assert "background: #16324f" in html


def test_single_layout_ignores_column_marks():
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    content = TemplateContent.model_validate(
        {
            "blocks": [{"kind": "skills", "column": "sidebar"}],
        }
    )
    html = render_cv(content, SAMPLE_SNAPSHOT).html
    assert "class='cv-columns'" not in html


def test_timeline_items_and_skill_bars():
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    content = TemplateContent.model_validate(
        {
            "blocks": [
                {
                    "kind": "items",
                    "props": {
                        "title": "Experience",
                        "source_key": "experience",
                        "style": "timeline",
                    },
                },
                {"kind": "skills", "props": {"display": "bars", "show_levels": True}},
            ],
        }
    )
    html = render_cv(content, SAMPLE_SNAPSHOT).html
    assert "items-timeline" in html
    assert "bar-fill" in html and "width:70%" in html  # sample SQL level 5 → 50%
    assert "width:50%" in html


def test_per_block_containers_override_design():
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    content = TemplateContent.model_validate(
        {
            "blocks": [
                {
                    "kind": "summary",
                    "props": {
                        "container": {
                            "container": "outline",
                            "border_color": "#111111",
                            "radius": 5,
                            "padding_mm": 4,
                        }
                    },
                },
                {
                    "kind": "interests",
                    "props": {
                        "container": {
                            "container": "card",
                            "background": "#f0f9ff",
                        }
                    },
                },
            ],
            "design": {"section_style": "flat"},
        }
    )
    html = render_cv(content, SAMPLE_SNAPSHOT).html
    assert "cv-outline" in html
    assert "border:0.4mm solid #111111" in html
    assert "border-radius:5mm" in html
    assert "padding:4mm" in html
    assert "background:#f0f9ff" in html
    assert html == render_cv(content, SAMPLE_SNAPSHOT).html


def test_spacing_tokens_and_icons():
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    content = TemplateContent.model_validate(
        {
            "blocks": [
                {"kind": "header"},
                {"kind": "summary"},
            ],
            "design": {
                "show_icons": True,
                "section_gap_mm": 8,
                "item_gap_mm": 4,
                "heading_rule": "accent",
            },
        }
    )
    html = render_cv(content, SAMPLE_SNAPSHOT).html
    assert "contact-icons" in html and "icn" in html
    assert "margin-bottom: 8mm" in html
    assert "border-bottom:1px solid var(--accent)" in html

    legacy = TemplateContent.model_validate(
        {"blocks": [{"kind": "summary"}], "design": {}}
    )
    legacy_html = render_cv(legacy, SAMPLE_SNAPSHOT).html
    assert "margin-bottom: calc(0.8em * var(--spacing))" in legacy_html
    assert "margin-bottom: 8mm" not in legacy_html


def test_icon_size_token_controls_css():
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    content = TemplateContent.model_validate(
        {"blocks": [{"kind": "header"}], "design": {"icon_size_mm": 5.0}}
    )
    html = render_cv(content, SAMPLE_SNAPSHOT).html
    assert "width: 5.0mm; height: 5.0mm" in html


async def test_profile_photo_upload_render_and_unset(
    client, auth_headers, profile_ready, seeded_catalog
):
    import io

    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d4944415478da63fcffff3f0300050001ff9bae8700"
        "00000049454e44ae426082"
    )
    upload = await client.put(
        "/api/v1/me/photo",
        files={"file": ("me.png", io.BytesIO(png), "image/png")},
        headers=auth_headers,
    )
    assert upload.status_code == 200, upload.text

    cv = await client.post(
        "/api/v1/cv", json={"title": "Photo CV"}, headers=auth_headers
    )
    preview = await client.post(
        f"/api/v1/cv/{cv.json()['id']}/preview", headers=auth_headers
    )
    assert preview.status_code == 200
    assert "<img class='cv-photo'" not in preview.json()["html"], (
        "show_photo defaults off"
    )

    unset = await client.delete("/api/v1/me/photo", headers=auth_headers)
    assert unset.status_code == 204


def test_photo_renders_when_enabled_with_shape_and_size():
    from app.services.cv_blocks import SAMPLE_SNAPSHOT

    snapshot = dict(SAMPLE_SNAPSHOT)
    snapshot["basics"] = {
        **snapshot["basics"],
        "photo": "data:image/png;base64,AAA",
    }
    content = TemplateContent.model_validate(
        {
            "blocks": [{"kind": "header"}],
            "design": {
                "show_photo": True,
                "photo_shape": "rounded",
                "photo_size_mm": 30,
            },
        }
    )
    html = render_cv(content, snapshot).html
    assert "<img class='cv-photo'" in html
    assert "width:30mm;height:30mm" in html
    assert "border-radius:3mm" in html
    assert "src='data:image/png;base64,AAA'" in html

    off = TemplateContent.model_validate({"blocks": [{"kind": "header"}], "design": {}})
    assert "<img class='cv-photo'" not in render_cv(off, snapshot).html


def test_template_prompts_merge_into_system_prompt():
    from app.ai.agents.cv_suggester import compose_system

    merged = compose_system(
        "summary",
        {"__handling__": "Never mention age.", "summary": "Lead with internships."},
    )
    assert "Never mention age." in merged
    assert "Lead with internships." in merged
    bare = compose_system("summary")
    assert "Never mention age." not in bare
    bullet = compose_system(
        "bullet", {"__handling__": "H", "summary": "Lead with internships."}
    )
    assert "H" in bullet and "Lead with internships." not in bullet


async def test_photo_state_endpoint_roundtrip(
    client, auth_headers, profile_ready, seeded_catalog
):
    import io

    state = await client.get("/api/v1/me/photo", headers=auth_headers)
    assert state.status_code == 200
    assert state.json() == {"photo_document_id": None}

    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d4944415478da63fcffff3f0300050001ff9bae8700"
        "00000049454e44ae426082"
    )
    upload = await client.put(
        "/api/v1/me/photo",
        files={"file": ("me.png", io.BytesIO(png), "image/png")},
        headers=auth_headers,
    )
    document_id = upload.json()["document_id"]
    state = await client.get("/api/v1/me/photo", headers=auth_headers)
    assert state.json()["photo_document_id"] == document_id

    await client.delete("/api/v1/me/photo", headers=auth_headers)
    state = await client.get("/api/v1/me/photo", headers=auth_headers)
    assert state.json()["photo_document_id"] is None


async def test_photo_gallery_and_per_cv_photo_override(
    client, auth_headers, profile_ready, seeded_catalog
):
    import io

    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d4944415478da63fcffff3f0300050001ff9bae8700"
        "00000049454e44ae426082"
    )

    def _upload(name: str):
        return client.put(
            "/api/v1/me/photo",
            files={"file": (name, io.BytesIO(png), "image/png")},
            headers=auth_headers,
        )

    first = (await _upload("one.png")).json()["document_id"]
    second = (await _upload("two.png")).json()["document_id"]

    gallery = await client.get("/api/v1/me/photo/gallery", headers=auth_headers)
    assert gallery.status_code == 200, gallery.text
    photos = gallery.json()
    assert len(photos) == 2
    assert photos[0]["is_default"] is True, "latest upload becomes the default"
    assert photos[1]["is_default"] is False

    switched = await client.put(
        f"/api/v1/me/photo/gallery/{photos[1]['document_id']}/default",
        headers=auth_headers,
    )
    assert switched.status_code == 200

    cv = await client.post(
        "/api/v1/cv",
        json={"title": "Photo CV", "photo_document_id": first},
        headers=auth_headers,
    )
    assert cv.status_code == 201, cv.text
    assert cv.json()["photo_document_id"] == first

    await client.patch(
        f"/api/v1/cv/{cv.json()['id']}",
        json={"photo_document_id": second},
        headers=auth_headers,
    )

    foreign = await client.patch(
        f"/api/v1/cv/{cv.json()['id']}",
        json={"photo_document_id": "00000000-0000-0000-0000-000000000001"},
        headers=auth_headers,
    )
    assert foreign.status_code == 404

    removed = await client.delete(
        f"/api/v1/me/photo/gallery/{second}", headers=auth_headers
    )
    assert removed.status_code == 204
    after = await client.get(f"/api/v1/cv/{cv.json()['id']}", headers=auth_headers)
    assert after.json()["photo_document_id"] is None, "deleted photo SET NULLs"


async def test_gallery_upload_keeps_profile_default_unchanged(
    client, auth_headers, profile_ready, seeded_catalog
):
    """POST /me/photo/gallery adds a photo without touching profile default."""
    import io

    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d4944415478da63fcffff3f0300050001ff9bae8700"
        "00000049454e44ae426082"
    )

    default = await client.put(
        "/api/v1/me/photo",
        files={"file": ("default.png", io.BytesIO(png), "image/png")},
        headers=auth_headers,
    )
    assert default.status_code == 200, default.text
    default_id = default.json()["document_id"]

    added = await client.post(
        "/api/v1/me/photo/gallery",
        files={"file": ("studio.png", io.BytesIO(png), "image/png")},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["is_default"] is False
    assert body["filename"] == "studio.png"

    state = await client.get("/api/v1/me/photo", headers=auth_headers)
    assert state.json()["photo_document_id"] == default_id, (
        "gallery upload must not move the profile default"
    )

    bad = await client.post(
        "/api/v1/me/photo/gallery",
        files={"file": ("x.txt", io.BytesIO(b"nope"), "text/plain")},
        headers=auth_headers,
    )
    assert bad.status_code == 400

    await client.delete("/api/v1/me/photo", headers=auth_headers)
