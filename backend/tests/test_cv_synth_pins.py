"""Plan 72 follow-up: per-CV synth pinning (context.synth_pins) — a pin
beats the automatic match winner for its ref, in both the prefer overlay
and the highlights snapshot; foreign-language or dead pins fall back."""

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
    assert "Winner text" in html, "a foreign-language pin is ignored; default applies"
    assert "German text" not in html

    # Highlights snapshot lists the winner (post-overlay exclusion keeps
    # it out of `synth` keys in prefer mode — here prefer + pin → applied
    # winner → excluded).
    await client.post(f"/api/v1/cv/{cv['id']}/compile", headers=auth_headers)
    version = (await db.execute(select(CvVersion))).scalars().first()
    assert version.content["snapshot"].get("synth", []) == []


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


async def test_unknown_pin_id_falls_back_to_winner(client, db, auth_headers):
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
    assert "Winner text" in preview.json()["html"], (
        "a pin pointing at a missing variant degrades to the matched winner"
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
