"""Plan 225 S2: the CV-template bank — create, conflict, retire, list vs render."""

from __future__ import annotations

import copy
import uuid

from sqlalchemy import select

from app.models.cv_template_model import CvTemplate
from app.services.cv.cv_template_service import CvTemplateService
from tests.seed_pack_fixture import apply_bank_pack, bank_items
from tests.test_seed_apply import _service, _source, _store, _version
from tests.test_seed_pack import _envelope, _pack

CV_CONTENT = {
    "blocks": [
        {"kind": "header", "props": {"show_links": True}},
        {"kind": "summary", "props": {"title": "Profile"}},
        {"kind": "items", "props": {"title": "Experience", "source_key": "experience"}},
    ],
    "design": {"accent_color": "#1d4ed8", "font_stack": "sans"},
    "pages": {"default_max_pages": 1, "overflow_policy": "warn"},
    "prompts": {},
}

CV_TEMPLATE = {
    "seed_key": "cv-template:synthetic-layout/v1",
    "key": "synthetic-layout",
    "version": 1,
    "title": "Synthetic Layout",
    "description": "A minimal single-column layout.",
    "language": "en",
    "page_size": "a4",
    "ats_safe": True,
    "content": CV_CONTENT,
}


def _cv_pack(items: list | None, *, version: str = "1.0.0") -> dict[str, bytes]:
    return _pack(
        {"items/cv_templates/templates.json": _envelope("cv_templates", items or [])},
        manifest={"version": version, "replaces": []},
    )


def _bank_items() -> list[dict]:
    items = []
    for spec in bank_items("cv_templates"):
        version = spec["version"]
        items.append(
            {
                "seed_key": f"cv-template:{spec['key']}/v{version}",
                "key": spec["key"],
                "version": version,
                "title": spec["title"],
                "description": spec["description"],
                "language": "en",
                "page_size": spec.get("page_size", "a4"),
                "ats_safe": spec.get("ats_safe", False),
                "content": spec["content"],
            }
        )
    return items


def _changed_content() -> dict:
    content = copy.deepcopy(CV_CONTENT)
    content["blocks"][1]["props"]["title"] = "Changed profile"
    return content


async def _operator_source(db):
    source = await _source(db)
    source.trust_tier = "operator"
    await db.commit()
    await db.refresh(source)
    return source


async def _applied_row(db, store, source) -> CvTemplate:
    first = await _version(db, store, source, _cv_pack([CV_TEMPLATE]))
    applied = await _service(db, store).apply(source, first)
    assert applied.status == "applied", applied.error
    row = await db.scalar(
        select(CvTemplate).where(CvTemplate.seed_key == "cv-template:synthetic-layout/v1")
    )
    assert row is not None
    return row


async def test_cv_template_pack_parses_plans_applies_noops_and_retires(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(db, store, source, _cv_pack([CV_TEMPLATE]))

    plan = await _service(db, store).build_plan(source, first)
    assert plan.status == "ok"
    [item] = [row for row in plan.items if row.entity_type == "cv_template"]
    assert item.action == "create"
    assert item.preview == {
        "title": "Synthetic Layout",
        "version": 1,
        "page_size": "a4",
    }

    applied = await _service(db, store).apply(source, first)
    assert applied.status == "applied", applied.error
    row = await db.scalar(
        select(CvTemplate).where(CvTemplate.seed_key == "cv-template:synthetic-layout/v1")
    )
    assert row is not None
    assert row.seed_key == "cv-template:synthetic-layout/v1"
    assert row.author_key == "bank" and row.source == "bank"
    assert row.status == "published" and row.visibility == "private"
    assert row.content_hash and row.version == 1
    assert row.ats_safe is True
    original_id = row.id

    again = await _service(db, store).apply(source, first)
    assert again.status == "noop"
    await db.refresh(row)
    assert row.id == original_id

    removed = await _version(db, store, source, _cv_pack([], version="2.0.0"))
    retired = await _service(db, store).apply(source, removed)
    assert retired.status == "applied", retired.error
    await db.refresh(row)
    assert row.status == "retired"
    assert await CvTemplateService(db).list_templates(uuid.uuid4()) == []


async def test_a_changed_body_at_the_same_version_is_refused(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    row = await _applied_row(db, store, source)
    original = dict(row.content)
    original_title = row.title

    changed = dict(CV_TEMPLATE, content=_changed_content())
    second = await _version(db, store, source, _cv_pack([changed], version="2.0.0"))
    plan = await _service(db, store).build_plan(source, second)
    assert plan.status == "conflicted"
    assert any("immutable" in conflict["reason"] for conflict in plan.conflicts)

    refused = await _service(db, store).apply(source, second)
    assert refused.status == "conflicted"
    await db.refresh(row)
    assert row.content == original
    assert row.title == original_title


async def test_a_new_version_is_created_and_the_old_stays_readable(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    old = await _applied_row(db, store, source)
    old_id = old.id

    second_item = {
        **CV_TEMPLATE,
        "seed_key": "cv-template:synthetic-layout/v2",
        "version": 2,
        "title": "Synthetic Layout v2",
        "content": _changed_content(),
    }
    second = await _version(db, store, source, _cv_pack([second_item], version="2.0.0"))
    plan = await _service(db, store).build_plan(source, second)
    actions = {
        item.seed_key: item.action for item in plan.items if item.entity_type == "cv_template"
    }
    assert actions == {
        "cv-template:synthetic-layout/v1": "retire",
        "cv-template:synthetic-layout/v2": "create",
    }

    applied = await _service(db, store).apply(source, second)
    assert applied.status == "applied", applied.error
    rows = {
        row.seed_key: row
        for row in (await db.execute(select(CvTemplate).where(CvTemplate.author_key == "bank")))
        .scalars()
        .all()
    }
    assert rows["cv-template:synthetic-layout/v1"].status == "retired"
    assert rows["cv-template:synthetic-layout/v2"].status == "published"

    listed = await CvTemplateService(db).list_templates(uuid.uuid4())
    assert [template.seed_key for template in listed] == ["cv-template:synthetic-layout/v2"]
    readable = await CvTemplateService(db).get_readable(old_id, uuid.uuid4())
    assert readable.id == old_id and readable.status == "retired"


async def test_a_pack_adopts_the_reference_bank_without_duplicates(db, tmp_path):
    fixture = await apply_bank_pack(db)
    before = {
        row.seed_key: row.id
        for row in (await db.execute(select(CvTemplate).where(CvTemplate.author_key == "bank")))
        .scalars()
        .all()
    }
    assert len(before) == len(_bank_items())
    assert None not in before

    version = await _version(db, fixture.store, fixture.source, _cv_pack(_bank_items()))

    plan = await _service(db, fixture.store).build_plan(fixture.source, version)
    assert not [item for item in plan.items if item.action in ("create", "retire", "delete")]
    assert {item.action for item in plan.items if item.entity_type == "cv_template"} <= {
        "update",
        "noop",
    }

    applied = await _service(db, fixture.store).apply(fixture.source, version)
    assert applied.status in ("applied", "noop"), applied.error
    again = await _service(db, fixture.store).apply(fixture.source, version)
    assert again.status == "noop"
    rows = (
        (await db.execute(select(CvTemplate).where(CvTemplate.author_key == "bank")))
        .scalars()
        .all()
    )
    assert len(rows) == len(_bank_items())
    assert {row.id for row in rows} == set(before.values())
    assert {row.seed_key for row in rows} == set(before)
    assert {row.status for row in rows} == {"published"}


async def test_a_retired_template_is_hidden_from_listing_but_still_renders(
    client, db, auth_headers, profile_ready, fixture_banks
):
    store = fixture_banks.store
    source = await _operator_source(db)
    row = await _applied_row(db, store, source)
    template_id = row.id

    listed = await client.get("/api/v1/cv/templates", headers=auth_headers)
    assert listed.status_code == 200
    assert str(template_id) in {template["id"] for template in listed.json()}

    created = await client.post(
        "/api/v1/cv",
        json={"title": "Retired template CV", "template_id": str(template_id)},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    cv_id = created.json()["id"]

    removed = await _version(db, store, source, _cv_pack([], version="2.0.0"))
    applied = await _service(db, store).apply(source, removed)
    assert applied.status == "applied", applied.error

    listed = await client.get("/api/v1/cv/templates", headers=auth_headers)
    assert listed.status_code == 200
    assert str(template_id) not in {template["id"] for template in listed.json()}

    template_preview = await client.get(
        f"/api/v1/cv/templates/{template_id}/preview", headers=auth_headers
    )
    assert template_preview.status_code == 200, template_preview.text
    assert "<html" in template_preview.text.lower()

    cv_preview = await client.post(f"/api/v1/cv/{cv_id}/preview", headers=auth_headers)
    assert cv_preview.status_code == 200, cv_preview.text
    assert "<html" in cv_preview.json()["html"].lower()
