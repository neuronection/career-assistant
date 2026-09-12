"""Plan 72.1: item ordering prop + the synth snapshot key + the
`synth_items` block (renderer, exports, estimator)."""

import uuid
from datetime import date

from app.models.cv_model import CvVersion
from app.models.experience_model import ExperienceItem
from app.services.cv_export_service import to_ats_text, to_markdown
from app.services.cv_renderer import _block_lines
from sqlalchemy import select


async def _make_item(
    db,
    uid: str,
    *,
    title: str = "Backend Intern",
    start: date = date(2024, 6, 1),
    kind: str = "internship",
) -> ExperienceItem:
    item = ExperienceItem(
        user_id=uuid.UUID(uid),
        kind=kind,
        title=title,
        org_name="Sample Corp",
        start=start,
        end=date(2024, 9, 1),
        description="Built QA tooling",
        status="active",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


def _uid_of(headers) -> str:
    import base64
    import json

    token = headers["Authorization"].split(" ", 1)[1]
    return str(json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))["sub"])


async def _cv(client, auth_headers, *, synth_mode="off") -> dict:
    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "Main", "kind": "resume"},
            headers=auth_headers,
        )
    ).json()
    await client.put(
        f"/api/v1/cv/{cv['id']}/context",
        json={"mode": "all", "synth_mode": synth_mode},
        headers=auth_headers,
    )
    return cv


async def _set_blocks(client, auth_headers, cv: dict, blocks: list) -> dict:
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={"working_content": {"blocks": blocks, "overrides": {}}},
        headers=auth_headers,
    )
    return cv


async def _preview(client, auth_headers, cv: dict) -> dict:
    response = await client.post(
        "/api/v1/cv/" + cv["id"] + "/preview", json={}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _synth_block_preview(client, auth_headers, cv: dict, props: dict) -> dict:
    await _set_blocks(
        client, auth_headers, cv, [{"kind": "synth_items", "props": props}]
    )
    return await _preview(client, auth_headers, cv)


async def _create_variant(
    client, auth_headers, items, *, variant_key="default", language="en"
) -> dict:
    response = await client.post(
        "/api/v1/cv/synth",
        json={
            "refs": [
                {"source_key": "experience", "item_id": str(item.id)} for item in items
            ],
            "payload": {
                "description": f"Tailored text for {items[0].title}",
                "bullets": ["Shipped the QA harness"],
            },
            "variant_key": variant_key,
            "voice": {"language": language},
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _synth_snapshot_of(client, auth_headers, db, cv: dict) -> list:
    """Compile the CV and read the stored snapshot's `synth` key."""
    compiled = await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    assert compiled.status_code == 201, compiled.text
    version = (await db.execute(select(CvVersion))).scalars().first()
    assert version is not None
    return version.content["snapshot"].get("synth", [])


async def test_synth_snapshot_lists_winner_per_ref(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    default_variant = await _create_variant(client, auth_headers, [item])
    alt = await _create_variant(client, auth_headers, [item], variant_key="alt")
    cv = await _cv(client, auth_headers)
    snapshot = await _synth_snapshot_of(client, auth_headers, db, cv)
    assert [entry["id"] for entry in snapshot] == [str(default_variant["id"])], (
        "variant_key 'default' beats 'alt' per the matching precedence"
    )
    assert alt["id"] not in [entry["id"] for entry in snapshot]
    assert snapshot[0]["title"] == "Backend Intern"
    assert snapshot[0]["description"] == "Tailored text for Backend Intern"
    assert snapshot[0]["source_refs"][0]["label"] == "Backend Intern"


async def test_synth_snapshot_gates_on_language(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    await _create_variant(client, auth_headers, [item], language="de")
    cv = await _cv(client, auth_headers)
    snapshot = await _synth_snapshot_of(client, auth_headers, db, cv)
    assert snapshot == [], "a variant under a foreign voice language never applies"


async def test_synth_snapshot_dedupes_multi_ref_variant(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    project = await _make_item(
        db, uid, title="Campus App", start=date(2023, 2, 1), kind="project"
    )
    variant = await _create_variant(client, auth_headers, [item, project])
    cv = await _cv(client, auth_headers)
    snapshot = await _synth_snapshot_of(client, auth_headers, db, cv)
    assert len(snapshot) == 1
    assert snapshot[0]["id"] == str(variant["id"])
    assert len(snapshot[0]["source_refs"]) == 2


async def test_synth_items_block_renders_entries_and_chips(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    await _create_variant(client, auth_headers, [item])
    cv = await _cv(client, auth_headers)
    preview = await _synth_block_preview(
        client, auth_headers, cv, {"title": "Highlights"}
    )
    assert "Tailored text for Backend Intern" in preview["html"]
    assert "item-detail" in preview["html"]
    assert ">Backend Intern<" in preview["html"], "source chip label renders"
    assert "<div class='chips'>" in preview["html"]


async def test_synth_items_block_without_source_chips(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    await _create_variant(client, auth_headers, [item])
    cv = await _cv(client, auth_headers)
    preview = await _synth_block_preview(
        client, auth_headers, cv, {"title": "Highlights", "show_source_chips": False}
    )
    assert "item-detail" in preview["html"]
    assert "<div class='chips'>" not in preview["html"]


async def test_synth_items_selected_excludes_others(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    other = await _make_item(db, uid, title="Frontend Intern", start=date(2025, 1, 1))
    pinned_variant = await _create_variant(client, auth_headers, [item])
    other_variant = await _create_variant(
        client, auth_headers, [other], variant_key="other"
    )
    cv = await _cv(client, auth_headers)
    exclusive = await _synth_block_preview(
        client,
        auth_headers,
        cv,
        {"title": "Highlights", "selected": [str(other_variant["id"])]},
    )
    assert "Tailored text for Backend Intern" not in exclusive["html"]
    assert "Tailored text for Frontend Intern" in exclusive["html"]
    everything = await _synth_block_preview(
        client, auth_headers, cv, {"title": "Highlights", "selected": []}
    )
    assert "Tailored text for Backend Intern" in everything["html"]
    pinned = await _synth_block_preview(
        client,
        auth_headers,
        cv,
        {"title": "Highlights", "selected": [str(pinned_variant["id"])]},
    )
    assert "Tailored text for Backend Intern" in pinned["html"]
    assert "Tailored text for Frontend Intern" not in pinned["html"]


async def test_synth_items_hidden_without_variants(client, auth_headers):
    cv = await _cv(client, auth_headers)
    preview = await _synth_block_preview(
        client, auth_headers, cv, {"title": "Highlights", "max_items": 6}
    )
    assert "Highlights</h2>" not in preview["html"]


async def test_synth_items_prefer_mode_excludes_overlay_applied(
    client, db, auth_headers
):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    await _create_variant(client, auth_headers, [item])
    cv = await _cv(client, auth_headers, synth_mode="prefer")
    await _set_blocks(
        client,
        auth_headers,
        cv,
        [
            {
                "kind": "items",
                "props": {"title": "Work", "source_key": "experience"},
            },
            {"kind": "synth_items", "props": {"title": "Highlights"}},
        ],
    )
    preview = await _preview(client, auth_headers, cv)
    assert preview["html"].count("Tailored text for Backend Intern") == 1, (
        "the variant text renders once (inside the item, never as a highlight)"
    )
    await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    version = (await db.execute(select(CvVersion))).scalars().first()
    assert version is not None
    assert version.content["snapshot"].get("synth", []) == [], (
        "the overlay-applied variant must not double-render as a highlight"
    )


async def test_synth_items_export_markdown_and_ats(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    variant = await _create_variant(client, auth_headers, [item])
    cv = await _cv(client, auth_headers)
    await _synth_block_preview(
        client,
        auth_headers,
        cv,
        {"title": "Highlights", "selected": [str(variant["id"])]},
    )
    compiled = await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    assert compiled.status_code == 201, compiled.text
    version = (await db.execute(select(CvVersion))).scalars().first()
    assert version is not None
    markdown = to_markdown(version.content)
    assert "## Highlights" in markdown
    assert "### Backend Intern" in markdown
    assert "Tailored text for Backend Intern" in markdown
    assert "Based on: Backend Intern" in markdown
    ats = to_ats_text(version.content)
    assert "Tailored text for Backend Intern" in ats


async def test_items_ordering_full_partial_and_truncation(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    older = await _make_item(db, uid, title="Older Role", start=date(2023, 1, 1))
    newer = await _make_item(db, uid, title="Newer Role", start=date(2024, 6, 1))
    cv = await _cv(client, auth_headers)
    await _set_blocks(
        client,
        auth_headers,
        cv,
        [
            {
                "kind": "items",
                "props": {
                    "title": "Work",
                    "source_key": "experience",
                    "order": [str(older.id), str(newer.id)],
                },
            }
        ],
    )
    html = (await _preview(client, auth_headers, cv))["html"]
    first, second = html.index(">Older Role<"), html.index(">Newer Role<")
    assert first < second, "user order beats the resolved newest-first default"

    partial = await _cv(client, auth_headers)
    await _set_blocks(
        client,
        auth_headers,
        partial,
        [
            {
                "kind": "items",
                "props": {
                    "title": "Work",
                    "source_key": "experience",
                    "order": [str(older.id)],
                },
            }
        ],
    )
    partial_html = (await _preview(client, auth_headers, partial))["html"]
    first, second = (
        partial_html.index(">Older Role<"),
        partial_html.index(">Newer Role<"),
    )
    assert first < second, "partial order: pinned first, remainder appended"

    truncating = await _cv(client, auth_headers)
    await _set_blocks(
        client,
        auth_headers,
        truncating,
        [
            {
                "kind": "items",
                "props": {
                    "title": "Work",
                    "source_key": "experience",
                    "max_items": 1,
                    "order": [str(older.id)],
                },
            }
        ],
    )
    truncated = (await _preview(client, auth_headers, truncating))["html"]
    assert ">Older Role<" in truncated
    assert ">Newer Role<" not in truncated, "the user's order decides survival"


async def test_estimator_honors_order_and_synth():
    from app.services.cv_blocks import ItemsBlockProps, SynthItemsProps
    from app.services.cv_renderer import DesignTokens

    design = DesignTokens()
    props = ItemsBlockProps(
        title="Work", source_key="experience", max_items=1, order=["a", "b"]
    )
    snapshot = {
        "experience": [
            {"id": "b", "title": "B", "description": "word " * 80},
            {"id": "a", "title": "A", "description": "Short"},
        ]
    }
    ordered = _block_lines("items", props, snapshot, design)
    unshuffled = _block_lines(
        "items", props.model_copy(update={"order": []}), snapshot, design
    )
    assert ordered < unshuffled, (
        "the estimator prices the user's survivor, not the tail"
    )

    synth_props = SynthItemsProps(title="Highlights", max_items=6)
    synth_snapshot = {
        "synth": [
            {
                "id": "1",
                "title": "T",
                "description": "word " * 60,
                "bullets": ["b", "c"],
            },
            {"id": "2", "title": "T2", "description": "d"},
        ]
    }
    synth = _block_lines("synth_items", synth_props, synth_snapshot, design)
    assert synth > 1
    truncated = _block_lines(
        "synth_items",
        synth_props.model_copy(update={"max_items": 1}),
        synth_snapshot,
        design,
    )
    assert truncated < synth
