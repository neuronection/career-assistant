"""— CV synth resolution + lint (plan 62.3): the per-CV synth overlay,
override/synth precedence, compile trace, and the lint signals."""

import uuid
from datetime import date

from app.models.experience_model import ExperienceItem


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


async def test_override_beats_synth(client, db, auth_headers):
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
    assert "Manual final text" in preview.json()["html"], (
        "override beats synth at render time"
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


async def test_lint_warns_when_pin_variant_is_archived_by_activation(
    client, db, auth_headers
):
    """Activating a second variant archives the slot's previous owner —
    a pin still pointing at the archived row must warn, not fail silently."""
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
    # Activating the second retires the first (slot supersede) — the pin
    # now points at an archived row.
    await client.patch(
        f"/api/v1/cv/synth/{second['id']}",
        json={"status": "active"},
        headers=auth_headers,
    )
    lint = (
        await client.get(f"/api/v1/cv/{cv['id']}/lint", headers=auth_headers)
    ).json()
    checks = {c["id"]: c for c in lint["checks"]}
    assert "synth_pin_inactive" in checks
    assert "archived" in checks["synth_pin_inactive"]["message"]
