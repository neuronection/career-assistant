"""— CV template system: versioning, registry, renderer, AI, review."""

import io
import uuid
from uuid import UUID

from sqlalchemy import select

from app.models.cv_template_model import CvTemplate
from app.schemas.cv_template import CvTemplateExport, TemplateContent
from app.seeds.cv_templates import BANK_TEMPLATES, seed_cv_template_bank
from app.services.cv_blocks import REGISTRY, validate_blocks
from app.services.cv_renderer import render_cv
from app.services.cv_template_service import CvTemplateService
from app.services.engagement_service import canonical_hash


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
    row = (
        (
            await db.execute(
                select(CvTemplate).where(
                    CvTemplate.author_key == "bank",
                    CvTemplate.key == "navy-sidebar",
                    CvTemplate.version == 2,
                )
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    design = row.content["design"]
    assert design["margin_mm"] == 0
    assert design["main_padding_mm"] > 0
    assert design["sidebar_padding_mm"] > 0
    source_keys = [
        block.get("props", {}).get("source_key")
        for block in row.content["blocks"]
        if block.get("kind") == "items"
    ]
    assert "experience" in source_keys and "projects" in source_keys
