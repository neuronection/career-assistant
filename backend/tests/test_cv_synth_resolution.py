"""— CV synth resolution + lint (plan 62.3): the per-CV synth overlay,
override/synth precedence, compile trace, and the lint signals."""

import uuid
from datetime import date

from app.models.experience_model import ExperienceAchievement, ExperienceItem


async def _make_item(
    db, uid: str, description: str = "Built QA tooling"
) -> ExperienceItem:
    item = ExperienceItem(
        user_id=uuid.UUID(uid),
        kind="internship",
        title="Backend Intern",
        org_name="Sample Corp",
        start=date(2024, 6, 1),
        end=date(2024, 9, 1),
        description=description,
        status="active",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


def _refs(item: ExperienceItem) -> list[dict]:
    return [{"source_key": "experience", "item_id": str(item.id)}]


async def _item_and_active_variant(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    row = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={"refs": _refs(item), "action": "summarize"},
            headers=auth_headers,
        )
    ).json()["items"][0]
    await client.patch(
        f"/api/v1/cv/synth/{row['id']}",
        json={"status": "active"},
        headers=auth_headers,
    )
    return item, row


def _uid_of(headers) -> str:
    import base64
    import json

    token = headers["Authorization"].split(" ", 1)[1]
    return str(json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))["sub"])


async def _cv_with_pins(
    client, auth_headers, db, *, item_id: str = "", synth_id: str = ""
) -> dict:
    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "Main", "kind": "resume"},
            headers=auth_headers,
        )
    ).json()
    pins = {"experience:" + item_id: synth_id} if synth_id else {}
    await client.put(
        f"/api/v1/cv/{cv['id']}/context",
        json={"mode": "all", "synth_pins": pins},
        headers=auth_headers,
    )
    return cv


async def _resolution(client, auth_headers, cv: dict) -> dict:
    return (
        await client.get(f"/api/v1/cv/{cv['id']}/context", headers=auth_headers)
    ).json()


async def test_no_pins_render_verbatim(client, db, auth_headers):
    item, _variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_pins(client, auth_headers, db, item_id=str(item.id))
    resolution = await _resolution(client, auth_headers, cv)
    description = resolution["snapshot"]["experience"][0]["description"]
    assert description == "Built QA tooling", "verbatim profile text at off"


async def test_starred_variant_swaps_in(client, db, auth_headers):
    item, variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_pins(
        client, auth_headers, db, item_id=str(item.id), synth_id=variant["id"]
    )
    resolution = await _resolution(client, auth_headers, cv)
    description = resolution["snapshot"]["experience"][0]["description"]
    assert description == variant["payload"]["description"], (
        "the synthesized variant replaced the source description"
    )
    assert description != "Built QA tooling"


async def test_pin_swap_bullets_replace(client, db, auth_headers):
    """Two-layer model: a variant that sets achievements OWNS the list —
    the profile's bullets render only when no variant sets them."""
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    db.add(ExperienceAchievement(experience_id=item.id, text="Own grounded bullet"))
    await db.commit()
    row = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={"refs": _refs(item), "action": "detail"},
            headers=auth_headers,
        )
    ).json()["items"][0]
    variant_id = row["id"]
    await client.patch(
        f"/api/v1/cv/synth/{variant_id}",
        json={
            "status": "active",
            "payload": {
                "description": row["payload"]["description"],
                "achievements": [{"text": "Variant bullet one"}],
            },
        },
        headers=auth_headers,
    )
    cv = await _cv_with_pins(
        client, auth_headers, db, item_id=str(item.id), synth_id=variant_id
    )
    resolution = await _resolution(client, auth_headers, cv)
    entries = resolution["snapshot"]["experience"][0]["achievements"]
    assert [entry["text"] for entry in entries] == ["Variant bullet one"], (
        "a variant that sets achievements replaces the profile list"
    )
    assert all(
        isinstance(entry, dict) and set(entry) == {"text"} for entry in entries
    ), "canonical bullet shape everywhere"


async def _make_bullets_variant(client, auth_headers, item, texts):
    return (
        await client.post(
            "/api/v1/cv/synth",
            json={
                "refs": _refs(item),
                "scope": "bullets",
                "payload": {"achievements": [{"text": text} for text in texts]},
            },
            headers=auth_headers,
        )
    ).json()


async def _cv_with_pin_map(client, auth_headers, pins: dict) -> dict:
    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "Main", "kind": "resume"},
            headers=auth_headers,
        )
    ).json()
    await client.put(
        f"/api/v1/cv/{cv['id']}/context",
        json={"mode": "all", "synth_pins": pins},
        headers=auth_headers,
    )
    return cv


async def test_bullets_variant_pin_composes_with_text_variant(client, db, auth_headers):
    """Plan-110 single-slot model: one star per item; a row applies what
    its payload carries. Composition of text + bullets on one starred
    row is the replace-free affordance (qpdate the pinned row's
    achievements separately) — the scaled-down two-slot pin test suite."""
    item, text_variant = await _item_and_active_variant(client, db, auth_headers)
    db.add(ExperienceAchievement(experience_id=item.id, text="Profile bullet"))
    await db.commit()

    with_guidance = await _cv_with_pin_map(
        client, auth_headers, {"experience:" + str(item.id): text_variant["id"]}
    )
    rows = (await _resolution(client, auth_headers, with_guidance))["snapshot"][
        "experience"
    ]
    assert rows[0]["description"] == text_variant["payload"]["description"], (
        "the pinned text variant owns the description"
    )
    assert [entry["text"] for entry in rows[0]["achievements"]] == ["Profile bullet"], (
        "absent achievements keep the profile bullets (presence rule)"
    )

    compose = await _cv_synth_update(
        client,
        auth_headers,
        text_variant["id"],
        {
            "payload": {
                **text_variant["payload"],
                "achievements": [
                    {"text": "Cut latency 40%"},
                    {"text": "Shipped v2"},
                ],
            }
        },
    )
    assert compose["status"] == "active"
    rows = (await _resolution(client, auth_headers, with_guidance))["snapshot"][
        "experience"
    ]
    assert rows[0]["description"] == text_variant["payload"]["description"], (
        "one row, one star: the same single slot"
    )
    assert [entry["text"] for entry in rows[0]["achievements"]] == [
        "Cut latency 40%",
        "Shipped v2",
    ], "the composed row swaps both layers"


async def _cv_synth_update(client, auth_headers, item_id, patch):
    response = await client.patch(
        f"/api/v1/cv/synth/{item_id}",
        json=patch,
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_bullets_variants_coexist_with_text_slot(client, db, auth_headers):
    """Multi-active library: activating a bullets candidate never
    retires the item's other enabled variants — the per-CV star (pin)
    decides what renders."""
    item, text_variant = await _item_and_active_variant(client, db, auth_headers)
    first = await _make_bullets_variant(client, auth_headers, item, ["First set"])
    second = await _make_bullets_variant(client, auth_headers, item, ["Second set"])

    text_row = (
        await client.get(f"/api/v1/cv/synth/{text_variant['id']}", headers=auth_headers)
    ).json()
    first_row = (
        await client.get(f"/api/v1/cv/synth/{first['id']}", headers=auth_headers)
    ).json()
    assert text_row["status"] == "active"
    assert first_row["status"] == "active"
    assert second["status"] == "active"


async def test_bullets_variant_needs_a_bullet(client, db, auth_headers):
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    response = await client.post(
        "/api/v1/cv/synth",
        json={"refs": _refs(item), "scope": "bullets", "payload": {}},
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_pin_beats_override_overrides_return_on_unpin(client, db, auth_headers):
    """Layer order is `pin > override > source`: re-starring a variant
    re-asserts its own fields over an older captured override (the
    pinned row owns what it carries); unpinning restores the override
    text so a manual patch is never lost."""
    item, _variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_pins(
        client, auth_headers, db, item_id=str(item.id), synth_id=_variant["id"]
    )
    ref = _refs(item)[0]
    ref_key = ref["source_key"] + ":" + ref["item_id"]
    edit = await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "blocks": [],
                "overrides": {ref_key: {"description": "Manual final text"}},
            }
        },
        headers=auth_headers,
    )
    assert edit.status_code == 200, edit.text
    preview = await client.post(
        "/api/v1/cv/" + cv["id"] + "/preview", json={}, headers=auth_headers
    )
    assert preview.status_code == 200, preview.text
    assert _variant["payload"]["description"] in preview.json()["html"], (
        "the pinned variant's text renders over the captured override"
    )
    # Unpin (remove the synth star) — the override text returns.
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={"context": {"synth_pins": {}}},
        headers=auth_headers,
    )
    unpinned = await client.post(
        "/api/v1/cv/" + cv["id"] + "/preview", json={}, headers=auth_headers
    )
    assert "Manual final text" in unpinned.json()["html"], (
        "unpinning restores the manual patch"
    )


async def test_compile_records_synth_trace(client, db, auth_headers):
    item, variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_pins(
        client, auth_headers, db, item_id=str(item.id), synth_id=variant["id"]
    )
    compiled = await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    assert compiled.status_code == 201, compiled.text
    trace = await db.execute(
        __import__("sqlalchemy", fromlist=["select"]).select(
            __import__("app.models.cv_model", fromlist=["CvVersion"]).CvVersion
        )
    )
    version = trace.scalars().first()
    applied = version.context_resolution.get("synth_applied") or {}
    assert applied, "compile records which synth id applied per ref"
    assert set(applied) and applied


async def test_lint_flags_synth_available(client, db, auth_headers):
    await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_pins(client, auth_headers, db)
    lint = (
        await client.get(f"/api/v1/cv/{cv['id']}/lint", headers=auth_headers)
    ).json()
    checks = {c["id"]: c for c in lint["checks"]}
    assert "synth_available" in checks
    assert checks["synth_available"]["level"] == "info"


async def test_lint_reports_synth_share_when_starred(client, db, auth_headers):
    item, variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_pins(
        client, auth_headers, db, item_id=str(item.id), synth_id=variant["id"]
    )
    lint = (
        await client.get(
            f"/api/v1/cv/{cv['id']}/lint",
            headers=auth_headers,
        )
    ).json()
    checks = {c["id"]: c for c in lint["checks"]}
    assert "synth_share" in checks
    assert checks["synth_share"]["applied"] >= 1


async def test_lint_flags_override_conflict(client, db, auth_headers):
    item, _variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_pins(
        client, auth_headers, db, item_id=str(item.id), synth_id=_variant["id"]
    )
    ref = _refs(item)[0]
    ref_key = ref["source_key"] + ":" + ref["item_id"]
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "blocks": [],
                "overrides": {ref_key: {"description": "Manual final text"}},
            }
        },
        headers=auth_headers,
    )
    lint = (
        await client.get(
            f"/api/v1/cv/{cv['id']}/lint",
            headers=auth_headers,
        )
    ).json()
    checks = {c["id"]: c for c in lint["checks"]}
    assert "synth_conflict" in checks, "override beats synth; lint tells the story"


async def test_lint_warns_when_pin_points_at_draft(client, db, auth_headers):
    """Plan 83 follow-up: a starred variant that can't render (still a
    draft) must surface a warn — silence reads as 'variants are broken'."""
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    row = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={"refs": _refs(item), "action": "summarize"},
            headers=auth_headers,
        )
    ).json()["items"][0]
    cv = await _cv_with_pins(
        client, auth_headers, db, item_id=str(item.id), synth_id=row["id"]
    )
    lint = (
        await client.get(f"/api/v1/cv/{cv['id']}/lint", headers=auth_headers)
    ).json()
    checks = {c["id"]: c for c in lint["checks"]}
    assert "synth_pin_inactive" in checks
    assert checks["synth_pin_inactive"]["level"] == "warn"
    assert "draft" in checks["synth_pin_inactive"]["message"]
    assert checks["synth_pin_inactive"]["ref"] == f"experience:{item.id}"


async def test_lint_silent_while_pin_variant_stays_active(client, db, auth_headers):
    """Multi-active library: activating sibling variants never retires a
    pinned active row — the pin stays lint-clean."""
    uid = _uid_of(auth_headers)
    item = await _make_item(db, uid)
    first = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={"refs": _refs(item), "action": "summarize"},
            headers=auth_headers,
        )
    ).json()["items"][0]
    await client.patch(
        f"/api/v1/cv/synth/{first['id']}",
        json={"status": "active"},
        headers=auth_headers,
    )
    second = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={"refs": _refs(item), "action": "detail"},
            headers=auth_headers,
        )
    ).json()["items"][0]
    cv = await _cv_with_pins(
        client, auth_headers, db, item_id=str(item.id), synth_id=first["id"]
    )
    await client.patch(
        f"/api/v1/cv/synth/{second['id']}",
        json={"status": "active"},
        headers=auth_headers,
    )
    lint = (
        await client.get(f"/api/v1/cv/{cv['id']}/lint", headers=auth_headers)
    ).json()
    checks = {c["id"]: c for c in lint["checks"]}
    assert "synth_pin_inactive" not in checks


async def test_omit_bullets_flag_clears_the_list_explicitly(client, db, auth_headers):
    """Plan-110 explicit omission: `omit_bullets: true` on a pinned row
    clears the item's bullets (description-variant-only entry prints),
    while an ordinary text-only variant (default serialization carries
    `achievements: []`) MUST keep rendering the profile bullets — empty
    list is never a signal."""
    item, text_variant = await _item_and_active_variant(client, db, auth_headers)
    db.add(ExperienceAchievement(experience_id=item.id, text="Profile bullet 1"))
    await db.commit()

    cv = await _cv_with_pin_map(
        client, auth_headers, {"experience:" + str(item.id): text_variant["id"]}
    )
    rows = (await _resolution(client, auth_headers, cv))["snapshot"]["experience"]
    assert [entry["text"] for entry in rows[0]["achievements"]] == [
        "Profile bullet 1"
    ], (
        "a text-only pinned row keeps the profile bullets (empty list is the row's "
        "default serialization, never an omission deal)"
    )

    omitted = await _cv_synth_update(
        client,
        auth_headers,
        text_variant["id"],
        {
            "payload": {
                "description": text_variant["payload"]["description"],
                "omit_bullets": True,
            }
        },
    )
    assert omitted["status"] == "active"
    cv_omitting = await _cv_with_pin_map(
        client, auth_headers, {"experience:" + str(item.id): text_variant["id"]}
    )
    rows = (await _resolution(client, auth_headers, cv_omitting))["snapshot"][
        "experience"
    ]
    assert rows[0]["achievements"] == [], (
        "the omit_bullets deal clears the pinned item's bullet list"
    )
    assert rows[0]["description"] == text_variant["payload"]["description"], (
        "the description variant renders as the only text"
    )
