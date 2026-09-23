"""— CV template system: versioning, registry, renderer, AI, review."""

import pytest
import copy
import io
import uuid
from uuid import UUID

from sqlalchemy import select

from app.models.cv_model import CvDocument
from app.models.cv_template_model import CvTemplate
from app.schemas.cv_template import CvTemplateExport, TemplateContent
from app.seeds.cv_templates import BANK_TEMPLATES, seed_cv_template_bank
from app.services.cv_blocks import REGISTRY, SAMPLE_SNAPSHOT, validate_blocks
from app.services.cv_renderer import render_cv
from app.services.cv_template_service import CvTemplateService
from app.services.engagement_service import canonical_hash
from tests.conftest import _uid


VALID_CONTENT = {
    "blocks": [
        {"kind": "header", "props": {"show_links": True, "show_location": True}},
        {"kind": "summary", "props": {"title": "Summary", "max_chars": 600}},
        {
            "kind": "items",
            "props": {
                "title": "Experience",
                "source_key": "experience",
                "max_items": 8,
                "show_skills": True,
                "show_achievements": True,
            },
        },
        {"kind": "skills", "props": {"display": "chips", "max_items": 18}},
    ],
    "design": {"accent_color": "#1d4ed8", "font_stack": "sans", "density": "normal"},
    "pages": {"default_max_pages": 1, "overflow_policy": "warn"},
    "prompts": {"field_prompts": {"summary": "Keep it short."}, "field_handling": ""},
}


async def _make_template(client, headers, **overrides) -> dict:
    payload = {"title": "My Layout", "content": VALID_CONTENT, **overrides}
    response = await client.post("/api/v1/cv/templates", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _drain(db):
    from app.services.job_worker import JobWorker

    worker = JobWorker(db)
    while await worker.run_once():
        pass


def test_block_registry_contract_kit():
    """Every registered kind validates its sample props and the bank."""
    assert set(REGISTRY) >= {
        "header",
        "summary",
        "items",
        "skills",
        "languages",
        "achievements",
        "interests",
        "custom_text",
        "spacer",
    }
    for spec in REGISTRY.values():
        spec.props_schema.model_validate(spec.sample)


def test_renderer_deterministic_and_escapes():
    content = TemplateContent.model_validate(VALID_CONTENT)
    snapshot = {
        "basics": {"name": "Jane <b>Doe</b>", "email": "j@x.io"},
        "summary": "Summary & notes",
        "experience": [
            {
                "title": "Dev <script>",
                "org": "Acme",
                "start": "2024-06",
                "end": "2025-01",
                "description": "Built things",
                "skills": ["Python"],
                "achievements": [{"text": "Cut costs 10%"}],
            }
        ],
        "skills": [{"label": "Python", "level": 7}],
        "languages": [{"code": "en", "label": "English", "level": "advanced"}],
    }
    first = render_cv(content, snapshot)
    second = render_cv(content, snapshot)
    assert first.html == second.html, "same inputs must render byte-equal"
    assert "<script>" not in first.html
    assert "&lt;script&gt;" in first.html
    assert "Jun 2024 – Jan 2025" in first.html
    assert not first.metrics.overflow


def test_renderer_overflow_lint_and_policies():
    wall = {"title": "Wall", "text": "word " * 390}
    fat_content = {
        "blocks": [
            {"kind": "header", "props": {}},
            {"kind": "summary", "props": {}},
            {"kind": "custom_text", "props": dict(wall)},
            {"kind": "custom_text", "props": dict(wall)},
            {"kind": "custom_text", "props": dict(wall)},
            {"kind": "custom_text", "props": dict(wall)},
            {"kind": "spacer", "props": {"height_mm": 20}},
        ],
        "pages": {"default_max_pages": 1, "overflow_policy": "warn"},
    }
    content = TemplateContent.model_validate(fat_content)
    result = render_cv(content, {}, max_pages=1)
    assert result.metrics.overflow

    shrink = TemplateContent.model_validate(
        {**fat_content, "pages": {"default_max_pages": 1, "overflow_policy": "shrink"}}
    )
    shrunk = render_cv(shrink, {}, max_pages=1)
    assert shrunk.html != result.html, "shrink must change typography"


def test_renderer_hides_empty_blocks():
    content = TemplateContent.model_validate(VALID_CONTENT)
    result = render_cv(content, {"basics": {"name": "Jane"}})
    assert set(result.metrics.empty_blocks) == {"summary", "items", "skills"}


def test_prompt_merge_template_overrides_globals():
    content = TemplateContent.model_validate(VALID_CONTENT)
    merged = content.merged_prompts()
    assert "Use only the facts" in merged["__handling__"]
    assert merged["summary"].endswith("Keep it short.")


async def test_template_crud_versions_and_ownership(client, db, auth_headers):
    template = await _make_template(client, auth_headers)
    assert template["version"] == 1
    assert template["status"] == "draft"

    edited = dict(VALID_CONTENT)
    edited["blocks"] = VALID_CONTENT["blocks"] + [
        {"kind": "interests", "props": {"max_items": 6}}
    ]
    v2 = await client.patch(
        f"/api/v1/cv/templates/{template['id']}",
        json={"title": "My Layout 2", "description": "", "content": edited},
        headers=auth_headers,
    )
    assert v2.status_code == 201, v2.text
    assert v2.json()["version"] == 2
    assert v2.json()["title"] == "My Layout 2"

    listing = await client.get("/api/v1/cv/templates", headers=auth_headers)
    mine = [t for t in listing.json() if t["key"] == template["key"]]
    assert len(mine) == 1, "latest version per key only"
    assert mine[0]["version"] == 2

    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "tmpler@example.com", "password": "supersecret1"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    steal = await client.patch(
        f"/api/v1/cv/templates/{template['id']}",
        json={"title": "X", "content": VALID_CONTENT},
        headers=other_headers,
    )
    assert steal.status_code == 404

    delete = await client.delete(
        f"/api/v1/cv/templates/{template['id']}", headers=auth_headers
    )
    assert delete.status_code == 204
    rows = await db.execute(select(CvTemplate).where(CvTemplate.key == template["key"]))
    assert rows.scalars().all() == []


async def test_template_export_import_round_trip(client, db, auth_headers):
    template = await _make_template(client, auth_headers)
    export = await client.get(
        f"/api/v1/cv/templates/{template['id']}/export", headers=auth_headers
    )
    assert export.status_code == 200
    package = export.json()
    assert package["content_hash"]

    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "importer@example.com", "password": "supersecret1"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    tampered = {**package, "content": {**package["content"], "design": {}}}
    rejected = await client.post(
        "/api/v1/cv/templates/import", json=tampered, headers=other_headers
    )
    assert rejected.status_code == 400, "hash mismatch must reject"

    imported = await client.post(
        "/api/v1/cv/templates/import", json=package, headers=other_headers
    )
    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert body["source"] == "imported"
    assert body["visibility"] == "private"
    assert body["content_hash"] == package["content_hash"]


async def test_template_import_rejects_unknown_block_kind(client, auth_headers):
    content = {
        "blocks": [{"kind": "hologram", "props": {}}],
        "design": {},
        "pages": {},
        "prompts": {},
    }
    package = CvTemplateExport(
        metadata={"title": "Bad"},
        content=content,
        content_hash=canonical_hash(content),
    ).model_dump(mode="json")
    response = await client.post(
        "/api/v1/cv/templates/import", json=package, headers=auth_headers
    )
    assert response.status_code == 400
    assert "unknown kind" in response.json()["detail"]


def test_validate_blocks_heals_missing_required_props_from_the_registry():
    """AI-drafted blocks may omit required fields with clean schema
    defaults (the template designer's `items` block with empty props):
    the validator HEALS them from the registry sample — required-field
    backfill only — instead of failing the whole AI task."""
    validated = validate_blocks(
        [
            {"kind": "items", "props": {}},
            {"kind": "items"},
            {"kind": "skills", "props": {"source_key": "ignored"}},
        ]
    )
    items_props = [props for kind, props in validated[:2]]
    assert all(props.source_key == "experience" for props in items_props)
    assert items_props[0].max_items > 0, "sample defaults ride along"
    skills_props = validated[2][1]
    assert skills_props.display == "chips", "optional props stay defaulted"


def test_validate_blocks_still_rejects_genuinely_bad_props():
    from app.core.errors import ValidationError as DomainValidationError

    with pytest.raises(DomainValidationError):
        validate_blocks([{"kind": "skills", "props": {"display": "magnetic"}}])


async def test_template_public_visibility_unreachable(client, db, auth_headers):
    from app.models.enums import CvTemplateVisibility

    assert CvTemplateVisibility.PUBLIC.value == "public"
    template = await _make_template(client, auth_headers)
    assert template["visibility"] == "private"
    listing = await client.get("/api/v1/cv/templates", headers=auth_headers)
    assert all(t["visibility"] != "public" for t in listing.json())


async def test_suggest_templates_via_mock(client, db, auth_headers):
    """Deterministic candidate scores, then AI ranks refs best-first."""
    await seed_cv_template_bank(db)
    response = await client.post(
        "/api/v1/cv/templates/suggest",
        json={"language": "en"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidates_considered"] >= 5
    assert body["picks"], "the mock ranks at least one pick"
    titles = {pick["title"] for pick in body["picks"]}
    listing = await client.get("/api/v1/cv/templates", headers=auth_headers)
    known = {t["title"] for t in listing.json()}
    assert titles <= known, "picks are real template rows"


async def test_suggest_templates_no_candidates(client, db, auth_headers):
    from tests.conftest import _uid

    result = await CvTemplateService(db).suggest(
        UUID(_uid(auth_headers)), language="en"
    )
    assert result == {"picks": [], "candidates_considered": 0}


async def test_ai_template_draft_via_mock(client, db, auth_headers):
    response = await client.post(
        "/api/v1/cv/templates/draft-ai",
        json={"brief": "green modern layout for a design intern", "page_budget": 1},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "ai"
    assert body["status"] == "draft"
    assert body["content"]["design"]["accent_color"] == "#0f766e"
    validate_blocks(body["content"]["blocks"])


async def test_visual_review_lint_and_mock_vision(client, db, auth_headers):
    template = await _make_template(client, auth_headers)

    lint_only = await client.post(
        f"/api/v1/cv/templates/{template['id']}/visual-review?page_count=1",
        headers=auth_headers,
    )
    assert lint_only.status_code == 200, lint_only.text
    body = lint_only.json()
    assert body["lint"]["lines_per_page"] > 0
    assert body["issues"], "mock critique always reports the spacing issue"
    assert body["safe_token_fixes"]

    png = io.BytesIO(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
            "53de0000000c4944415408d763f8cfc00000030101"
        )
    )
    vision = await client.post(
        f"/api/v1/cv/templates/{template['id']}/visual-review?page_count=1",
        files=[("files", ("page-0.png", png, "image/png"))],
        headers=auth_headers,
    )
    assert vision.status_code == 200, vision.text


async def test_bank_templates_seed_and_preview(client, db, auth_headers):
    added = await seed_cv_template_bank(db)
    assert added == len(BANK_TEMPLATES)
    again = await seed_cv_template_bank(db)
    assert again == 0, "seeding must be idempotent"

    listing = await client.get("/api/v1/cv/templates", headers=auth_headers)
    bank = [t for t in listing.json() if t["source"] == "bank"]
    assert {t["key"] for t in bank} >= {
        "ats-classic",
        "modern-two-column",
        "compact-onepage",
        "academic",
        "student-first",
    }

    for template in bank:
        preview = await client.get(
            f"/api/v1/cv/templates/{template['id']}/preview", headers=auth_headers
        )
        assert preview.status_code == 200, template["key"]
        assert "<h1>" in preview.text
        assert "color-mix" in preview.text

    classic = next(t for t in bank if t["key"] == "ats-classic")
    assert classic["ats_safe"] is True
    rows = await db.execute(select(CvTemplate).where(CvTemplate.key == "ats-classic"))
    service = CvTemplateService(db)
    lint = service.lint(rows.scalars().first())
    assert not lint["overflow"]

    duplicate = await client.post(
        f"/api/v1/cv/templates/{classic['id']}/duplicate",
        json={"title": "My classic"},
        headers=auth_headers,
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["source"] == "duplicated"

    edit_bank = await client.patch(
        f"/api/v1/cv/templates/{classic['id']}",
        json={"title": "X", "content": VALID_CONTENT},
        headers=auth_headers,
    )
    assert edit_bank.status_code == 400, "bank templates are read-only"


def test_skills_block_renders_only_selected_ids():
    """`SkillsProps.selected` lists context item ids (plan 68): only the
    chosen skills render; an empty/absent list keeps all skills."""
    from app.schemas.cv_template import TemplateContent
    from app.services.cv_renderer import render_cv

    snapshot = {
        "basics": {"name": "Jane Doe", "email": "j@x.io"},
        "skills": [
            {"id": "sk-1", "label": "Python", "level": 7},
            {"id": "sk-2", "label": "SQL", "level": 5},
        ],
    }
    content = TemplateContent.model_validate(VALID_CONTENT)
    full = render_cv(content, snapshot).html
    assert "Python" in full and "SQL" in full

    picked_data = dict(VALID_CONTENT)
    picked_data = []
    for block in VALID_CONTENT["blocks"]:
        if block["kind"] == "skills":
            picked_data.append(
                {"kind": "skills", "props": {**block["props"], "selected": ["sk-1"]}}
            )
        else:
            picked_data.append(block)
    picked = TemplateContent.model_validate({**VALID_CONTENT, "blocks": picked_data})
    narrowed = render_cv(picked, snapshot).html
    assert "Python" in narrowed
    assert ">SQL<" not in narrowed

    void = TemplateContent.model_validate(
        {
            **VALID_CONTENT,
            "blocks": [
                {"kind": "skills", "props": {"selected": ["no-such-id"]}},
                {"kind": "skills", "props": {"display": "chips", "max_items": 18}},
            ],
        }
    )
    strict = render_cv(void, snapshot).html
    # The broken-selected skills block renders nothing (strict); only the
    # second, selection-free block contributes its chips.
    assert strict.count("Python") == 1, "unknown ids render nothing — no fallback"


async def test_bank_seed_bumps_insert_new_versions_and_list_dedupes(db):
    """Plan 70: edited bank specs ship as version 2 — the seeder inserts
    the new immutable row alongside a pre-existing v1 and the listing
    dedupes to the highest version."""
    from datetime import datetime, timezone

    db.add(
        CvTemplate(
            key="ats-classic",
            version=1,
            title="ATS-Safe Classic",
            description="legacy v1",
            author_user_id=None,
            author_key="bank",
            source="bank",
            visibility="private",
            language="en",
            page_size="a4",
            ats_safe=True,
            schema_version=1,
            content_hash="legacy",
            status="published",
            content=TemplateContent.model_validate(
                {
                    "blocks": [{"kind": "header"}],
                    "design": {},
                    "pages": {"default_max_pages": 1},
                    "prompts": {},
                }
            ).model_dump(mode="json"),
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    )
    await db.commit()

    await seed_cv_template_bank(db)
    rows = {
        (row.key, row.version): row
        for row in (
            await db.execute(
                select(CvTemplate).where(
                    CvTemplate.author_key == "bank", CvTemplate.key == "ats-classic"
                )
            )
        )
        .scalars()
        .all()
    }
    assert set(rows) == {("ats-classic", 1), ("ats-classic", 2)}
    assert (
        rows[("ats-classic", 2)].content["blocks"]
        != rows[("ats-classic", 1)].content["blocks"]
    ), "v2 carries the plan-70 content"
    assert rows[("ats-classic", 1)].content_hash == "legacy", "v1 rows are immutable"

    service = CvTemplateService(db)
    listing = await service.list_templates(uuid.uuid4())
    by_key = {row.key: row for row in listing if row.author_key == "bank"}
    assert by_key["ats-classic"].version == 2


async def test_sidebar_bank_template_uses_area_paddings(db):
    await seed_cv_template_bank(db)
    rows = (
        (
            await db.execute(
                select(CvTemplate).where(
                    CvTemplate.author_key == "bank",
                    CvTemplate.key == "navy-sidebar",
                )
            )
        )
        .scalars()
        .all()
    )
    row = max(rows, key=lambda template: template.version)
    assert row.version == 4
    design = row.content["design"]
    assert design["margin_mm"] == 0
    assert design["main_padding_mm"] > 0
    assert design["sidebar_padding_mm"] > 0
    assert design["show_heading_icons"] is True
    assert design["running_footer"] == "name"
    blocks = row.content["blocks"]
    assert all(block.get("area") in {"main", "sidebar"} for block in blocks)
    source_keys = [
        block.get("props", {}).get("source_key")
        for block in blocks
        if block.get("kind") == "items"
    ]
    assert "experience" in source_keys and "projects" in source_keys
    assert "certifications" in source_keys
    teal_rows = (
        (
            await db.execute(
                select(CvTemplate).where(
                    CvTemplate.author_key == "bank",
                    CvTemplate.key == "teal-sidebar",
                )
            )
        )
        .scalars()
        .all()
    )
    teal = max(teal_rows, key=lambda r: r.version)
    assert teal.version == 4
    assert teal.content["design"]["show_photo"] is True
    assert teal.content["design"]["show_heading_icons"] is True
    skills = next(
        block for block in teal.content["blocks"] if block.get("kind") == "skills"
    )
    assert skills["props"]["display"] == "bars"
    modern_rows = (
        (
            await db.execute(
                select(CvTemplate).where(
                    CvTemplate.author_key == "bank",
                    CvTemplate.key == "modern-two-column",
                )
            )
        )
        .scalars()
        .all()
    )
    modern = max(modern_rows, key=lambda r: r.version)
    modern_skills = next(
        block for block in modern.content["blocks"] if block.get("kind") == "skills"
    )
    assert modern_skills["props"]["display"] == "grouped"


async def test_new_reference_templates_seed_and_render(db):
    """The bank grows with photo + skill-bar layouts inspired by popular
    magazine CVs: a coral banner (header band in the main column) and a
    charcoal-amber split (header living inside the dark sidebar)."""
    from app.services.cv_renderer import render_cv

    await seed_cv_template_bank(db)
    for key in ("coral-banner", "charcoal-amber"):
        rows = (
            (
                await db.execute(
                    select(CvTemplate).where(
                        CvTemplate.author_key == "bank",
                        CvTemplate.key == key,
                    )
                )
            )
            .scalars()
            .all()
        )
        row = max(rows, key=lambda r: r.version)
        content = TemplateContent.model_validate(row.content)
        assert content.design.layout == "sidebar"
        assert content.design.show_photo is True
        assert content.design.show_heading_icons is True
        result = render_cv(content, SAMPLE_SNAPSHOT)
        assert "<aside class='cv-sidebar'>" in result.html
        assert "h-icn" in result.html, "heading glyphs render"
        assert not result.metrics.overflow

    snapshot = copy.deepcopy(SAMPLE_SNAPSHOT)
    snapshot["basics"]["photo"] = "data:image/svg+xml,svg"
    coral = next(t for t in BANK_TEMPLATES if t["key"] == "coral-banner")
    html = render_cv(TemplateContent.model_validate(coral["content"]), snapshot).html
    assert "padding: 4mm 5mm" in html, "band header paints its accent panel"
    assert "<img class='cv-photo'" in html
    charcoal = next(t for t in BANK_TEMPLATES if t["key"] == "charcoal-amber")
    html = render_cv(TemplateContent.model_validate(charcoal["content"]), snapshot).html
    sidebar = html.split("<aside class='cv-sidebar'>", 1)[1].split("</aside>", 1)[0]
    assert "<img class='cv-photo'" in sidebar, "photo lives in the dark sidebar"
    assert "cv-header" in sidebar
    assert "color: inherit" in html, "sidebar header text inherits column color"
    assert "data:image/svg+xml;charset=utf-8" in sidebar, "QR panel in the sidebar"
    coral = TemplateContent.model_validate(coral["content"])
    assert coral.design.name_style == "accent_surname"
    assert coral.design.photo_shape == "arch"


async def test_ai_draft_assigns_areas_and_normalizes_layout(client, db, auth_headers):
    """The designer is area-capable: a sidebar brief yields sidebar-
    assigned compact blocks with layout=sidebar, and a draft that
    declares a layout its blocks contradict gets normalized."""
    from app.ai.gateway import MOCK_FIXTURES
    from app.ai.agents.cv_template_designer import draft_template
    from app.models.enums import AITaskType
    from app.schemas.cv_template import TemplateContent

    response = await client.post(
        "/api/v1/cv/templates/draft-ai",
        json={"brief": "two-column sidebar layout for a dev intern", "page_budget": 1},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert content["design"]["layout"] == "sidebar"
    sidebar_kinds = {
        block["kind"] for block in content["blocks"] if block.get("area") == "sidebar"
    }
    assert sidebar_kinds, "the sidebar brief assigns blocks to the sidebar"
    assert sidebar_kinds <= {"skills", "languages", "interests", "certifications", "qr"}

    def _contradictory(schema, prompt):
        return {
            "blocks": [
                {"kind": "header", "props": {}},
                {"kind": "summary", "props": {"title": "Summary"}},
            ],
            "design": {"layout": "sidebar"},
            "pages": {"default_max_pages": 1, "overflow_policy": "warn"},
            "prompts": {"field_prompts": {}},
        }

    monkey_style = MOCK_FIXTURES
    previous = monkey_style.get(AITaskType.CV_TEMPLATE_DESIGN.value)
    monkey_style[AITaskType.CV_TEMPLATE_DESIGN.value] = _contradictory
    try:
        draft = await draft_template(
            db, UUID(_uid(auth_headers)), brief="any", page_budget=1
        )
    finally:
        if previous is not None:
            monkey_style[AITaskType.CV_TEMPLATE_DESIGN.value] = previous
    assert draft.design.layout == "single", "no sidebar blocks → single layout"
    TemplateContent.model_validate(draft.model_dump(mode="json"))


async def test_suggest_passes_candidate_thumbnails_when_engine_available(
    client, db, auth_headers, monkeypatch
):
    """Visual pick: with the PDF engine present the top candidates'
    sample renders ride to the ranking as page images; the metadata-only
    path stays the fallback (engine off → no images)."""
    import app.ai.agents.cv_template_advisor as advisor
    import app.services.cv_pdf_service as pdf_service
    from tests.conftest import _uid

    await seed_cv_template_bank(db)
    real_rank = advisor.rank_templates
    seen: dict[str, object] = {}

    async def _spy_rank(db, user_id, candidates, target=None, images=None):
        seen["images"] = images
        return await real_rank(db, user_id, candidates, target)

    async def _png(html: str, page_size: str = "a4", max_images: int = 4):
        return pdf_service.PageMeasure(
            pages=1, source="pdf", images=[("image/png", b"\x89PNG-fake")]
        )

    monkeypatch.setattr(pdf_service, "measure_pages", _png)
    monkeypatch.setattr(advisor, "rank_templates", _spy_rank)
    result = await CvTemplateService(db).suggest(
        UUID(_uid(auth_headers)), language="en"
    )
    assert result["picks"]
    images = seen["images"]
    assert images and all(mime == "image/png" for mime, _data in images)

    async def _unavailable(*_args, **_kwargs):
        from app.services.cv_pdf_service import PDFEngineUnavailable

        raise PDFEngineUnavailable("Server PDF engine not installed")

    monkeypatch.setattr(pdf_service, "measure_pages", _unavailable)
    seen.clear()
    result = await CvTemplateService(db).suggest(
        UUID(_uid(auth_headers)), language="en"
    )
    assert result["picks"]
    assert seen.get("images") in (None, []), "engine off degrades to metadata-only"


async def test_suggest_carries_the_emphasis_notes_into_the_ranking(
    client, db, auth_headers, monkeypatch
):
    """The generate modal's "what should this CV emphasize" notes reach
    the ranking call's target context — the AI ranks on the request,
    not metadata alone."""
    import app.ai.agents.cv_template_advisor as advisor

    await seed_cv_template_bank(db)
    seen: dict[str, object] = {}
    real_rank = advisor.rank_templates

    async def _spy(db, user_id, candidates, target=None, images=None):
        seen["target"] = target
        return await real_rank(db, user_id, candidates, target)

    monkeypatch.setattr(advisor, "rank_templates", _spy)
    await CvTemplateService(db).suggest(
        UUID(_uid(auth_headers)),
        language="en",
        notes="Emphasize open-source projects and MCP tooling",
    )
    target = seen["target"] or {}
    assert target.get("notes") == "Emphasize open-source projects and MCP tooling"


async def test_suggest_layout_hint_boosts_sidebar_candidates(client, db, auth_headers):
    """A 'modern / sidebar' brief is a layout preference: the
    deterministic baseline promotes sidebar-layout candidates to the
    top instead of the ATS-safe single-column default."""
    await seed_cv_template_bank(db)
    result = await CvTemplateService(db).suggest(
        UUID(_uid(auth_headers)),
        language="en",
        notes="make it very modern, follow best practices",
    )
    assert result["picks"], "the mock still ranks picks"
    top_id = result["picks"][0]["template_id"]
    top = await db.get(CvTemplate, UUID(top_id))
    content = TemplateContent.model_validate(top.content)
    assert content.design.layout == "sidebar", "the layout hint wins the baseline"


async def test_suggest_demotes_recently_used_templates(
    client, db, auth_headers, monkeypatch
):
    """Variety lever, not a ban: the templates the user's recent CVs
    already showcase drop below fresh candidates in the determinstic
    baseline, and the advisor target names them for the AI ranking."""
    from app.models.cv_model import CvDocument

    await seed_cv_template_bank(db)
    template = await db.execute(
        select(CvTemplate).where(CvTemplate.author_key == "bank")
    )
    template = template.scalars().first()
    db.add(
        CvDocument(
            user_id=UUID(_uid(auth_headers)),
            title="Previous CV",
            kind="resume",
            language="en",
            page_size="a4",
            max_pages=1,
            status="draft",
            template_id=template.id,
        )
    )
    await db.commit()

    import app.ai.agents.cv_template_advisor as advisor

    seen: dict[str, object] = {}
    real_rank = advisor.rank_templates

    async def _spy(db, user_id, candidates, target=None, images=None):
        seen["target"] = target
        return await real_rank(db, user_id, candidates, target)

    monkeypatch.setattr(advisor, "rank_templates", _spy)
    result = await CvTemplateService(db).suggest(
        UUID(_uid(auth_headers)), language="en"
    )
    target = seen["target"] or {}
    assert template.title in (target.get("recently_used") or [])
    top = await db.get(CvTemplate, UUID(result["picks"][0]["template_id"]))
    assert top.id != template.id, "a repeat is demoted below every fresh pick"


async def test_suggest_never_ranks_the_user_s_own_templates(
    client, db, auth_headers, monkeypatch
):
    """A fresh generate's auto pick ranges over curated bank templates
    only: private copies (tests, one-offs, older styled duplicates)
    must not win by recency luck when the brief asks for a look they
    don't express. The explicit picker reaches them instead."""
    await seed_cv_template_bank(db)
    own = await _make_template(client, auth_headers)
    result = await CvTemplateService(db).suggest(
        UUID(_uid(auth_headers)), language="en", notes="modern and elegant"
    )
    assert result["picks"]
    picked = {pick["template_id"] for pick in result["picks"]}
    assert own["id"] not in picked


async def test_preview_with_uses_the_own_snapshot(client, db, auth_headers):
    """preview-with renders the template against one of the caller's CVs —
    an empty profile falls back to the deterministic sample (the gallery
    never renders a blank page) and a filled one renders THAT data."""
    from app.models.user_model import Profile
    from app.services.cv_builder_service import CvBuilderService

    await seed_cv_template_bank(db)
    listing = await client.get("/api/v1/cv/templates", headers=auth_headers)
    template = [t for t in listing.json() if t["source"] == "bank"][0]

    created = await client.post(
        "/api/v1/cv", json={"title": "Preview me"}, headers=auth_headers
    )
    assert created.status_code == 201, created.text
    cv_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/cv/templates/{template['id']}/preview-with",
        json={"cv_id": cv_id},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "<h1>" in body["html"]
    assert "Alex Sample" in body["html"], "empty profile falls back to the sample"
    assert "metrics" in body

    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == _uid(auth_headers))))
        .scalars()
        .first()
    )
    profile.aspirations = [
        {"label": "Backend intern", "notes": "I care about the details."}
    ]
    db.add(profile)
    await db.commit()
    response = await client.post(
        f"/api/v1/cv/templates/{template['id']}/preview-with",
        json={"cv_id": cv_id},
        headers=auth_headers,
    )
    body = response.json()
    assert "Backend intern" in body["html"], "the own snapshot renders"

    cv_row = (
        (await db.execute(select(CvDocument).where(CvDocument.id == UUID(cv_id))))
        .scalars()
        .one()
    )
    snapshot = await CvBuilderService(db).snapshot_for_cv(cv_row)
    assert "Backend intern" in str(snapshot.get("summary"))

    # foreign CVs are unreachable (404, not a leak)
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "supersecret1"},
    )
    other_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
    other_cv = await client.post(
        "/api/v1/cv", json={"title": "Theirs"}, headers=other_headers
    )
    assert other_cv.status_code == 201, other_cv.text
    leak = await client.post(
        f"/api/v1/cv/templates/{template['id']}/preview-with",
        json={"cv_id": other_cv.json()["id"]},
        headers=auth_headers,
    )
    assert leak.status_code == 404, "other users' CVs are unreachable"


async def test_template_stats_admin_only(client, db, auth_headers):
    from app.models.user_model import User

    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "admin-stats@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201, first.text
    row = (
        (await db.execute(select(User).where(User.email == "admin-stats@example.com")))
        .scalars()
        .first()
    )
    row.is_admin = True
    await db.commit()
    admin = {"Authorization": f"Bearer {first.json()['access_token']}"}
    allowed = await client.get("/api/v1/cv/templates/stats", headers=admin)
    assert allowed.status_code == 200, allowed.text
    assert isinstance(allowed.json(), list)
    # a second user (registered after the admin) is not an admin
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "stat-nonadmin@example.com", "password": "supersecret1"},
    )
    if second.status_code == 201:
        denied = await client.get(
            "/api/v1/cv/templates/stats",
            headers={"Authorization": f"Bearer {second.json()['access_token']}"},
        )
        assert denied.status_code == 403, denied.text


async def test_refreshed_bank_lints_and_prints_within_budget(db):
    """79.5 bank v4 refresh: every bank spec lints clean on the sample
    snapshot, and the refreshed photo/sidebar layouts print within their
    page budget on a real engine (plan-76 truth; skips without one)."""
    import pytest as _pytest

    from app.services.cv_pdf_service import PDFEngineUnavailable, measure_pages

    refreshed = {"navy-sidebar", "teal-sidebar", "coral-banner", "charcoal-amber"}
    for spec in BANK_TEMPLATES:
        content = TemplateContent.model_validate(spec["content"])
        result = render_cv(content, SAMPLE_SNAPSHOT)
        assert not result.metrics.overflow, (
            f"{spec['key']} overflows its own budget on the sample snapshot"
        )
        if spec["key"] in refreshed:
            try:
                measure = await measure_pages(
                    result.html, page_size=spec.get("page_size", "a4"), max_images=0
                )
            except (PDFEngineUnavailable, RuntimeError):
                _pytest.skip("no PDF engine on this host")
            assert measure.pages is not None
            budget = content.pages.default_max_pages
            assert measure.pages <= budget, (
                f"{spec['key']} prints {measure.pages} pages over budget {budget}"
            )


async def test_template_version_listing_and_diff(client, db, auth_headers):
    """79.2.6 stretch: version rows list newest-first and the diff
    endpoint reports deterministic token/block changes (no prose)."""
    import copy

    template = await _make_template(client, auth_headers)
    edited = copy.deepcopy(VALID_CONTENT)
    edited["design"]["accent_color"] = "#0f766e"
    edited["design"]["heading_rule"] = "accent"
    edited["blocks"].append({"kind": "interests", "props": {"max_items": 4}})
    updated = await client.patch(
        f"/api/v1/cv/templates/{template['id']}",
        json={"title": "My Layout", "content": edited},
        headers=auth_headers,
    )
    assert updated.status_code == 201, updated.text

    versions = await client.get(
        f"/api/v1/cv/templates/{template['id']}/versions", headers=auth_headers
    )
    assert versions.status_code == 200, versions.text
    listed = versions.json()
    assert [row["version"] for row in listed] == [2, 1]

    diff = await client.get(
        f"/api/v1/cv/templates/{updated.json()['id']}/diff", headers=auth_headers
    )
    assert diff.status_code == 200, diff.text
    body = diff.json()
    assert body["from_version"] == 1 and body["to_version"] == 2
    paths = {change["path"]: change for change in body["token_changes"]}
    assert paths["design.accent_color"]["to"] == "#0f766e"
    assert paths["design.heading_rule"]["to"] == "accent"
    assert "interests:" in body["block_changes"]["added"][0]

    first = await client.get(
        f"/api/v1/cv/templates/{template['id']}/diff", headers=auth_headers
    )
    assert first.status_code == 400, "v1 has no earlier version to diff against"
    explicit = await client.get(
        f"/api/v1/cv/templates/{updated.json()['id']}/diff?against={template['id']}",
        headers=auth_headers,
    )
    assert explicit.status_code == 200, explicit.text
    assert explicit.json()["from_version"] == 1


def test_items_block_links_opt_in_and_print_safe():
    """`show_links` renders per-item links print-first (short urls, max 3)
    and defaults OFF so existing templates never shift."""
    from app.schemas.cv_template import TemplateContent
    from app.services.cv_renderer import render_cv

    snapshot = {
        "basics": {"name": "Jane Doe"},
        "experience": [
            {
                "title": "Neuronection",
                "org": "",
                "description": "Ecosystem of assistants.",
                "links": [
                    {"url": "https://github.com/you/app?tab=readme", "label": "Repo"},
                    {"url": "https://neuronection.com"},
                    {"url": "https://x.io/3"},
                    {"url": "https://x.io/4"},
                ],
            }
        ],
    }
    content = TemplateContent.model_validate(VALID_CONTENT)
    default_html = render_cv(content, snapshot).html
    assert "github.com/you/app" not in default_html  # off by default

    links_on = dict(VALID_CONTENT)
    links_on["blocks"] = [
        (
            {"kind": "items", "props": {**b["props"], "show_links": True}}
            if b["kind"] == "items"
            else b
        )
        for b in VALID_CONTENT["blocks"]
    ]
    html = render_cv(TemplateContent.model_validate(links_on), snapshot).html
    assert "item-links" in html
    # print-first: scheme/www/query stripped, label wins over raw url
    assert "github.com/you/app" in html
    assert "https://" not in html.split("item-links")[1].split("</p>")[0]
    assert "x.io/3" in html
    assert "x.io/4" not in html  # capped at 3


async def test_preview_png_cached_and_capability_gated(
    client, db, auth_headers, monkeypatch
):
    """Plan 83B: the PNG route renders once, caches by content hash, and
    answers 503 with the capability message when the engine is missing."""
    from app.services.cv_pdf_service import PDFEngineUnavailable
    from app.services.cv_template_service import CvTemplateService

    await seed_cv_template_bank(db)
    listing = await client.get("/api/v1/cv/templates", headers=auth_headers)
    template = next(t for t in listing.json() if t["key"] == "ats-classic")

    calls = {"n": 0}

    async def fake_first_page_png(self, template_row):
        calls["n"] += 1
        return b"png-bytes-1"

    monkeypatch.setattr(CvTemplateService, "first_page_png", fake_first_page_png)

    first = await client.get(
        f"/api/v1/cv/templates/{template['id']}/preview.png", headers=auth_headers
    )
    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "image/png"
    etag = first.headers["etag"]

    second = await client.get(
        f"/api/v1/cv/templates/{template['id']}/preview.png", headers=auth_headers
    )
    assert second.status_code == 200
    assert second.headers["etag"] == etag
    assert calls["n"] == 1, "the content-hash cache must skip the second render"

    fresh = next(t for t in listing.json() if t["key"] == "modern-two-column")

    async def render_failed(self, template_row):
        return None

    monkeypatch.setattr(CvTemplateService, "first_page_png", render_failed)
    missing = await client.get(
        f"/api/v1/cv/templates/{fresh['id']}/preview.png", headers=auth_headers
    )
    assert missing.status_code == 503
    assert "engine" in missing.json()["detail"].lower()

    async def engine_missing(self, template_row):
        raise PDFEngineUnavailable("The print engine is not installed.")

    monkeypatch.setattr(CvTemplateService, "first_page_png", engine_missing)
    uncached = next(t for t in listing.json() if t["key"] == "compact-onepage")
    capability = await client.get(
        f"/api/v1/cv/templates/{uncached['id']}/preview.png", headers=auth_headers
    )
    assert capability.status_code == 503
    assert "print engine" in capability.json()["detail"]


async def test_preview_png_hides_foreign_templates(db, auth_headers):
    """A private template owned by someone else is invisible to the PNG
    route exactly like the HTML preview (404, not 403)."""
    from app.core.config import settings
    from app.core.errors import NotFoundError
    from app.models.user_model import User
    from app.services.cv_template_service import CvTemplateService

    owner_rows = await db.execute(
        select(User).where(User.email == settings.DEFAULT_USER_EMAIL)
    )
    owner = owner_rows.scalars().first()
    private = await CvTemplateService(db).create(
        owner.id,
        title="Private template",
        content=TemplateContent.model_validate(VALID_CONTENT),
    )

    outsider = User(email=f"prev-{uuid.uuid4().hex[:8]}@example.com")
    outsider.password_hash = "x"
    db.add(outsider)
    await db.commit()

    service = CvTemplateService(db)
    with pytest.raises(NotFoundError):
        await service.preview_png_cached(private.id, outsider.id)
