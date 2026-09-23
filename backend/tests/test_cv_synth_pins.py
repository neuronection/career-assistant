"""Plan 72 follow-up: per-CV synth pinning (context.synth_pins) — a pin
swaps that variant's text in for its ref (pins-only semantics), the
highlights snapshot cross-lists UNPINNED winners only, and dead pins
render profile text without any auto-winner jump-in (pin exclusivity).
Also the surgical pin endpoint (`PUT /cv/{id}/context/pin`)."""

import uuid
from datetime import date

from app.models.cv_model import CvVersion
from app.models.experience_model import ExperienceItem
from sqlalchemy import select


async def _make_item(
    db, uid: str, title: str = "Backend Intern", start: date = date(2024, 6, 1)
) -> ExperienceItem:
    item = ExperienceItem(
        user_id=uuid.UUID(uid),
        kind="internship",
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


async def _cv(client, auth_headers) -> dict:
    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "Main", "kind": "resume"},
            headers=auth_headers,
        )
    ).json()
    return cv


async def _set_context(client, auth_headers, cv: dict, **context) -> None:
    response = await client.put(
        f"/api/v1/cv/{cv['id']}/context",
        json={"mode": "all", "synth_mode": "prefer", **context},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text


async def _variant(client, auth_headers, item, *, variant_key: str, text: str) -> dict:
    response = await client.post(
        "/api/v1/cv/synth",
        json={
            "refs": [{"source_key": "experience", "item_id": str(item.id)}],
            "payload": {"description": text},
            "variant_key": variant_key,
            "voice": {"language": "en"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_pin_beats_the_automatic_winner_in_overlay(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    await _variant(
        client, auth_headers, item, variant_key="default", text="Engine default text"
    )
    pinned = await _variant(
        client, auth_headers, item, variant_key="alt", text="Pinned tailored text"
    )
    cv = await _cv(client, auth_headers)
    await _set_context(
        client,
        auth_headers,
        cv,
        synth_pins={"experience:" + str(item.id): str(pinned["id"])},
    )
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "blocks": [
                    {
                        "kind": "items",
                        "props": {"title": "Work", "source_key": "experience"},
                    }
                ],
                "overrides": {},
            }
        },
        headers=auth_headers,
    )
    preview = await client.post(
        "/api/v1/cv/" + cv["id"] + "/preview", json={}, headers=auth_headers
    )
    assert preview.status_code == 200, preview.text
    html = preview.json()["html"]
    assert "Pinned tailored text" in html, "the pin wins over the variant_key default"
    assert "Engine default text" not in html
    await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    version = (await db.execute(select(CvVersion))).scalars().first()
    assert version is not None
    applied = version.context_resolution.get("synth_applied")
    assert applied and applied["experience:" + str(item.id)] == str(pinned["id"])


async def test_pin_gates_on_language_and_falls_back(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    await _variant(
        client, auth_headers, item, variant_key="default", text="Winner text"
    )
    foreign = await client.post(
        "/api/v1/cv/synth",
        json={
            "refs": [{"source_key": "experience", "item_id": str(item.id)}],
            "payload": {"description": "German text"},
            "variant_key": "de-variant",
            "voice": {"language": "de"},
        },
        headers=auth_headers,
    )
    assert foreign.status_code == 201, foreign.text
    cv = await _cv(client, auth_headers)
    await _set_context(
        client,
        auth_headers,
        cv,
        synth_pins={"experience:" + str(item.id): foreign.json()["id"]},
    )
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "blocks": [
                    {
                        "kind": "items",
                        "props": {"title": "Work", "source_key": "experience"},
                    }
                ],
                "overrides": {},
            }
        },
        headers=auth_headers,
    )
    preview = await client.post(
        "/api/v1/cv/" + cv["id"] + "/preview", json={}, headers=auth_headers
    )
    html = preview.json()["html"]
    assert "German text" not in html, "a foreign-language pin never applies"
    assert "Winner text" not in html, "pin exclusivity: no auto-winner jump-in"
    assert "Built QA tooling" in html, "verbatim profile text renders instead"
    await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    version = (await db.execute(select(CvVersion))).scalars().first()
    entries = version.content["snapshot"].get("synth", [])
    assert "Winner text" not in [entry["description"] for entry in entries], (
        "a pinned ref never cross-lists another variant in the "
        "highlights snapshot — the star owns the item, and a dead "
        "star falls through to profile text, never to the auto-winner"
    )


async def test_highlights_snapshot_respects_pins(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    other = await _make_item(db, uid, title="Frontend Intern", start=date(2025, 1, 1))
    await _variant(
        client, auth_headers, item, variant_key="default", text="Engine default text"
    )
    pinned = await _variant(
        client, auth_headers, item, variant_key="alt", text="Pinned highlight"
    )
    awaited = await _variant(
        client,
        auth_headers,
        other,
        variant_key="default",
        text="Unpinned alternate",
    )
    cv = await _cv(client, auth_headers)
    await _set_context(
        client,
        auth_headers,
        cv,
        synth_mode="off",
        synth_pins={"experience:" + str(item.id): str(pinned["id"])},
    )
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "blocks": [
                    {
                        "kind": "items",
                        "props": {"title": "Work", "source_key": "experience"},
                    },
                    {"kind": "synth_items", "props": {"title": "Highlights"}},
                ],
                "overrides": {},
            }
        },
        headers=auth_headers,
    )
    preview = await client.post(
        "/api/v1/cv/" + cv["id"] + "/preview", json={}, headers=auth_headers
    )
    html = preview.json()["html"]
    assert "Pinned highlight" in html, "the pinned variant renders inside its item"
    assert "Engine default text" not in html
    assert html.count("Pinned highlight") == 1, (
        "the pinned variant never double-renders in the highlights section"
    )
    assert "Unpinned alternate" in html, (
        "unpinned variants for other items still list in the highlights section"
    )
    await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    version = (await db.execute(select(CvVersion))).scalars().first()
    assert version is not None
    entries = version.content["snapshot"].get("synth", [])
    assert [entry["id"] for entry in entries] == [str(awaited["id"])]


async def test_unknown_pin_id_never_cross_lists_the_winner(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    await _variant(
        client, auth_headers, item, variant_key="default", text="Winner text"
    )
    cv = await _cv(client, auth_headers)
    await _set_context(
        client,
        auth_headers,
        cv,
        synth_mode="off",
        synth_pins={
            "experience:" + str(item.id): "ffffffff-0000-0000-0000-000000000001"
        },
    )
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "blocks": [{"kind": "synth_items", "props": {"title": "Highlights"}}],
                "overrides": {},
            }
        },
        headers=auth_headers,
    )
    preview = await client.post(
        "/api/v1/cv/" + cv["id"] + "/preview", json={}, headers=auth_headers
    )
    assert "Winner text" not in preview.json()["html"], (
        "a pin pointing at a missing variant is a DEAD pin: profile text "
        "renders, the auto-winner never jumps into the highlights block"
    )


async def test_pin_applies_even_with_prefer_off(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    pinned = await _variant(
        client, auth_headers, item, variant_key="alt", text="Starred text"
    )
    cv = await _cv(client, auth_headers)
    await _set_context(
        client,
        auth_headers,
        cv,
        synth_mode="off",
        synth_pins={"experience:" + str(item.id): str(pinned["id"])},
    )
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "blocks": [
                    {
                        "kind": "items",
                        "props": {"title": "Work", "source_key": "experience"},
                    }
                ],
                "overrides": {},
            }
        },
        headers=auth_headers,
    )
    preview = await client.post(
        "/api/v1/cv/" + cv["id"] + "/preview", json={}, headers=auth_headers
    )
    assert preview.status_code == 200, preview.text
    html = preview.json()["html"]
    assert "Starred text" in html, "a pin replaces the item text on its own"
    assert "Built QA tooling" not in html, "the original text never renders"


async def test_pin_applies_for_project_items(client, db, auth_headers):
    """Plan 83 follow-up repro: pins on PROJECT items must swap text like
    experience pins do (source_key 'projects', not 'experience')."""
    uid = _uid_of(auth_headers)
    item = ExperienceItem(
        user_id=uuid.UUID(uid),
        kind="project",
        title="Neuronection",
        start=date(2025, 1, 1),
        open_ended=True,
        description="Original project description",
        status="active",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    variant = await _variant(
        client,
        auth_headers,
        item,
        variant_key="default",
        text="Synthesized project description",
    )
    import json as _json

    print("VARIANT_REFS:", _json.dumps(variant.get("source_refs")))
    cv = await _cv(client, auth_headers)
    await _set_context(
        client,
        auth_headers,
        cv,
        synth_pins={"projects:" + str(item.id): str(variant["id"])},
    )
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "blocks": [
                    {
                        "kind": "items",
                        "props": {"title": "Projects", "source_key": "projects"},
                    }
                ],
                "overrides": {},
            }
        },
        headers=auth_headers,
    )
    preview = await client.post(
        "/api/v1/cv/" + cv["id"] + "/preview", json={}, headers=auth_headers
    )
    assert preview.status_code == 200, preview.text
    html = preview.json()["html"]
    assert "Synthesized project description" in html, (
        "the pinned project variant must render"
    )
    assert "Original project description" not in html


async def test_pin_applies_for_activated_ai_project_variant(
    client, db, auth_headers, monkeypatch
):
    """Plan 83 follow-up: the exact user flow — AI-generate a project
    variant, Activate it, star it — must swap the rendered text."""
    from app.services.cv_template_service import CvTemplateService

    uid = _uid_of(auth_headers)
    item = ExperienceItem(
        user_id=uuid.UUID(uid),
        kind="project",
        title="Neuronection",
        start=date(2025, 1, 1),
        open_ended=True,
        description="Original project description",
        status="active",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    async def fake_first_page_png(self, template):
        return b"png"

    monkeypatch.setattr(CvTemplateService, "first_page_png", fake_first_page_png)

    generate = await client.post(
        "/api/v1/cv/synth/generate",
        json={
            "refs": [{"source_key": "projects", "item_id": str(item.id)}],
            "action": "summarize",
            "language": "en",
        },
        headers=auth_headers,
    )
    assert generate.status_code == 200, generate.text
    drafts = generate.json()["items"]
    assert len(drafts) >= 1

    activated = await client.patch(
        f"/api/v1/cv/synth/{drafts[0]['id']}",
        json={"status": "active"},
        headers=auth_headers,
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"

    cv = await _cv(client, auth_headers)
    await _set_context(
        client,
        auth_headers,
        cv,
        synth_pins={"projects:" + str(item.id): str(drafts[0]["id"])},
    )
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "blocks": [
                    {
                        "kind": "items",
                        "props": {"title": "Projects", "source_key": "projects"},
                    }
                ],
                "overrides": {},
            }
        },
        headers=auth_headers,
    )
    preview = await client.post(
        "/api/v1/cv/" + cv["id"] + "/preview", json={}, headers=auth_headers
    )
    assert preview.status_code == 200, preview.text
    html = preview.json()["html"]
    assert "delivered measurable outcomes" in html, (
        "the pinned activated project variant must render"
    )


async def _pin(client, auth_headers, cv, *, source_key, item_id, synth_id=None):
    return await client.put(
        f"/api/v1/cv/{cv['id']}/context/pin",
        json={
            "source_key": source_key,
            "item_id": item_id,
            "synth_id": synth_id,
        },
        headers=auth_headers,
    )


async def test_pin_endpoint_stars_and_preserves_other_slots(client, db, auth_headers):
    """The surgical pin write merges into the stored map — pinning item B
    after item A never erases A's star (the lost-update the full-map
    PUTs used to cause)."""
    uid = _uid_of(auth_headers)
    item_a = await _make_item(db, uid, title="Backend Intern")
    item_b = await _make_item(db, uid, title="Frontend Intern", start=date(2025, 1, 1))
    var_a = await _variant(
        client, auth_headers, item_a, variant_key="default", text="A"
    )
    var_b = await _variant(
        client, auth_headers, item_b, variant_key="default", text="B"
    )
    cv = await _cv(client, auth_headers)

    first = await _pin(
        client,
        auth_headers,
        cv,
        source_key="experience",
        item_id=str(item_a.id),
        synth_id=str(var_a["id"]),
    )
    assert first.status_code == 200, first.text
    pins = first.json()["context"]["synth_pins"]
    assert pins == {f"experience:{item_a.id}": str(var_a["id"])}

    second = await _pin(
        client,
        auth_headers,
        cv,
        source_key="experience",
        item_id=str(item_b.id),
        synth_id=str(var_b["id"]),
    )
    assert second.status_code == 200, second.text
    pins = second.json()["context"]["synth_pins"]
    assert pins == {
        f"experience:{item_a.id}": str(var_a["id"]),
        f"experience:{item_b.id}": str(var_b["id"]),
    }, "the second surgical write must not erase the first star"

    unpinned = await _pin(
        client,
        auth_headers,
        cv,
        source_key="experience",
        item_id=str(item_a.id),
        synth_id=None,
    )
    assert unpinned.status_code == 200, unpinned.text
    pins = unpinned.json()["context"]["synth_pins"]
    assert pins == {f"experience:{item_b.id}": str(var_b["id"])}


async def test_pin_endpoint_promotes_a_draft(client, db, auth_headers):
    """The star IS the approval (plan 102): pinning a draft row
    activates it in the same write."""
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    generated = await client.post(
        "/api/v1/cv/synth/generate",
        json={
            "refs": [{"source_key": "experience", "item_id": str(item.id)}],
            "action": "summarize",
            "language": "en",
        },
        headers=auth_headers,
    )
    assert generated.status_code == 200, generated.text
    draft = generated.json()["items"][0]
    assert draft["status"] == "draft"

    cv = await _cv(client, auth_headers)
    response = await _pin(
        client,
        auth_headers,
        cv,
        source_key="experience",
        item_id=str(item.id),
        synth_id=str(draft["id"]),
    )
    assert response.status_code == 200, response.text
    pins = response.json()["context"]["synth_pins"]
    assert pins[f"experience:{item.id}"] == str(draft["id"])

    row = (
        await client.get(f"/api/v1/cv/synth/{draft['id']}", headers=auth_headers)
    ).json()
    assert row["status"] == "active", "pinning a draft promotes it"


async def test_pin_endpoint_rejects_archived_and_foreign_rows(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    archived = await _variant(
        client, auth_headers, item, variant_key="default", text="x"
    )
    bulk = await client.post(
        "/api/v1/cv/synth/bulk",
        json={"ids": [archived["id"]], "action": "archive"},
        headers=auth_headers,
    )
    assert bulk.status_code == 200, bulk.text
    cv = await _cv(client, auth_headers)
    archived_pin = await _pin(
        client,
        auth_headers,
        cv,
        source_key="experience",
        item_id=str(item.id),
        synth_id=str(archived["id"]),
    )
    assert archived_pin.status_code == 400, archived_pin.text

    missing = await _pin(
        client,
        auth_headers,
        cv,
        source_key="experience",
        item_id=str(item.id),
        synth_id="ffffffff-0000-0000-0000-000000000001",
    )
    assert missing.status_code == 404, missing.text


async def test_pin_endpoint_rejects_another_users_variant(client, db, auth_headers):
    """Tenant isolation: a star can only name the caller's own rows."""
    from app.models.cv_synth_model import CvSynthItem
    from app.models.user_model import User

    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    other = User(
        email="foreign-pin@example.com",
        password_hash="$2b$12$foreignpinplaceholder",
    )
    db.add(other)
    await db.flush()
    foreign = CvSynthItem(
        user_id=other.id,
        scope="item",
        variant_key="default",
        source_refs=[{"source_key": "experience", "item_id": str(item.id)}],
        source_state=[],
        source_set_hash="foreign",
        payload={"description": "not yours"},
        evidence_refs=[],
        voice={"language": "en"},
        status="active",
        source="manual",
        verified=True,
    )
    db.add(foreign)
    await db.commit()
    await db.refresh(foreign)

    cv = await _cv(client, auth_headers)
    response = await _pin(
        client,
        auth_headers,
        cv,
        source_key="experience",
        item_id=str(item.id),
        synth_id=str(foreign.id),
    )
    assert response.status_code == 404, response.text
    refreshed = await client.get(f"/api/v1/cv/{cv['id']}", headers=auth_headers)
    assert refreshed.json()["context"].get("synth_pins") == {}


async def test_single_delete_strips_pins(client, db, auth_headers):
    """DELETE /cv/synth/{id} pops every star pointing at the row — a
    dangling pin must never survive a delete (bulk already did)."""
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    variant = await _variant(
        client, auth_headers, item, variant_key="default", text="x"
    )
    cv = await _cv(client, auth_headers)
    pinned = await _pin(
        client,
        auth_headers,
        cv,
        source_key="experience",
        item_id=str(item.id),
        synth_id=str(variant["id"]),
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["context"]["synth_pins"]

    deleted = await client.delete(
        f"/api/v1/cv/synth/{variant['id']}", headers=auth_headers
    )
    assert deleted.status_code in (200, 204), deleted.text

    refreshed = await client.get(f"/api/v1/cv/{cv['id']}", headers=auth_headers)
    assert refreshed.json()["context"].get("synth_pins") == {}, (
        "the star pointed at a deleted row and must be gone"
    )


async def test_resolution_responses_carry_synth_applied(client, db, auth_headers):
    """`synth_applied` is the applied-variant truth the UI stars
    cross-check: present on both the context GET and the preview."""
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    variant = await _variant(
        client, auth_headers, item, variant_key="alt", text="Starred truth"
    )
    cv = await _cv(client, auth_headers)
    await _pin(
        client,
        auth_headers,
        cv,
        source_key="experience",
        item_id=str(item.id),
        synth_id=str(variant["id"]),
    )
    ref_key = f"experience:{item.id}"

    context = await client.get(f"/api/v1/cv/{cv['id']}/context", headers=auth_headers)
    assert context.status_code == 200, context.text
    applied = context.json()["synth_applied"]
    assert applied.get(ref_key) == str(variant["id"])

    preview = await client.post(
        f"/api/v1/cv/{cv['id']}/preview", json={}, headers=auth_headers
    )
    assert preview.status_code == 200, preview.text
    applied = preview.json()["resolution"]["synth_applied"]
    assert applied.get(ref_key) == str(variant["id"])


async def test_dead_pin_is_reported_as_not_applied(client, db, auth_headers):
    """A language-gated pin renders profile text AND stays absent from
    `synth_applied` — the UI can finally show an inactive star."""
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    foreign = await client.post(
        "/api/v1/cv/synth",
        json={
            "refs": [{"source_key": "experience", "item_id": str(item.id)}],
            "payload": {"description": "German text"},
            "variant_key": "de-variant",
            "voice": {"language": "de"},
        },
        headers=auth_headers,
    )
    assert foreign.status_code == 201, foreign.text
    cv = await _cv(client, auth_headers)
    await _pin(
        client,
        auth_headers,
        cv,
        source_key="experience",
        item_id=str(item.id),
        synth_id=foreign.json()["id"],
    )
    context = await client.get(f"/api/v1/cv/{cv['id']}/context", headers=auth_headers)
    assert context.status_code == 200, context.text
    ref_key = f"experience:{item.id}"
    assert context.json()["synth_applied"].get(ref_key) is None, (
        "a dead pin never lands in synth_applied"
    )
    assert str(item.id) in context.json()["snapshot_index"].get("experience", [])
