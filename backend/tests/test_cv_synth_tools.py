"""— CV synth copilot tools (plan 62.4): registry reads vs writes,
ownership enforcement, per-CV applicability verdicts (pins-only), and
the generate / update write paths."""

import base64
import json
import uuid
from datetime import date

import pytest

from app.ai.tools import ToolScope, list_tools, run_tool
from app.models.experience_model import ExperienceItem


def _uid(auth_headers) -> str:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    return str(json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))["sub"])


def _refs(item: ExperienceItem) -> list[dict]:
    return [{"source_key": "experience", "item_id": str(item.id)}]


async def _item(db, uid: str) -> ExperienceItem:
    item = ExperienceItem(
        user_id=uuid.UUID(uid),
        kind="internship",
        title="Backend Intern",
        org_name="Sample Corp",
        start=date(2024, 6, 1),
        end=date(2024, 9, 1),
        description="Built QA tooling",
        status="active",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _item_and_active_variant(client, db, auth_headers):
    item = await _item(db, _uid(auth_headers))
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


async def _cv(client, auth_headers, db, *, pins: dict | None = None) -> dict:
    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "Main", "kind": "resume"},
            headers=auth_headers,
        )
    ).json()
    await client.put(
        f"/api/v1/cv/{cv['id']}/context",
        json={"mode": "all", "synth_pins": pins or {}},
        headers=auth_headers,
    )
    return cv


def _pin_for(item) -> dict:
    return {"experience:" + str(item.id): None}


async def test_no_delete_tool_and_scope_split():
    listed = {t["key"]: t for t in list_tools()}
    assert not any("delete" in key for key in listed if key.startswith("cv_synth")), (
        "deletion stays human-only in the library UI"
    )
    assert listed["cv_synth_list"]["scope"] == ToolScope.READ.value
    assert listed["cv_synth_read"]["scope"] == ToolScope.READ.value
    assert listed["cv_synth_generate"]["scope"] == ToolScope.WRITE.value
    assert listed["cv_synth_update"]["scope"] == ToolScope.WRITE.value
    assert "cv_synth_enable" not in listed, (
        "synth_mode is gone — per-item pins are the only mechanism"
    )


async def test_list_requires_user(db):
    from app.core.errors import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        await run_tool(db, "cv_synth_list", None)


async def test_list_verdicts_not_pinned(client, db, auth_headers):
    from tests.test_cv_synth_resolution import (
        _cv_with_pins,
        _item_and_active_variant,
    )

    item, variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_pins(client, auth_headers, db)
    result = await run_tool(
        db, "cv_synth_list", uuid.UUID(_uid(auth_headers)), {"cv_id": str(cv["id"])}
    )
    rows = {row["id"]: row for row in result["items"]}
    assert rows[variant["id"]]["verdict"] == "not_pinned", (
        "active variant exists but no star pins it on this CV"
    )
    del item


async def test_list_applies_when_starred(client, db, auth_headers):
    from tests.test_cv_synth_resolution import (
        _cv_with_pins,
        _item_and_active_variant,
    )

    item, variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_pins(
        client, auth_headers, db, item_id=str(item.id), synth_id=variant["id"]
    )
    result = await run_tool(
        db, "cv_synth_list", uuid.UUID(_uid(auth_headers)), {"cv_id": str(cv["id"])}
    )
    rows = {row["id"]: row for row in result["items"]}
    assert rows[variant["id"]]["verdict"] == "applies"
    del item


async def test_list_language_mismatch_verdict(client, db, auth_headers):
    from tests.test_cv_synth_resolution import (
        _cv_with_pins,
        _item_and_active_variant,
    )

    item, variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_pins(
        client, auth_headers, db, item_id=str(item.id), synth_id=variant["id"]
    )
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={"language": "fr"},
        headers=auth_headers,
    )
    result = await run_tool(
        db, "cv_synth_list", uuid.UUID(_uid(auth_headers)), {"cv_id": str(cv["id"])}
    )
    rows = {row["id"]: row for row in result["items"]}
    assert rows[variant["id"]]["verdict"] == "wrong_language"
    del item


async def test_generate_and_update_via_tools(client, db, auth_headers):
    from tests.test_cv_synth_resolution import _cv_with_pins

    item = await _item(db, _uid(auth_headers))
    cv = await _cv_with_pins(client, auth_headers, db)
    generated = await run_tool(
        db,
        "cv_synth_generate",
        uuid.UUID(_uid(auth_headers)),
        {
            "cv_id": str(cv["id"]),
            "refs": _refs(item),
            "action": "summarize",
        },
    )
    assert generated["created"], "the mock provider drafted a variant"
    live = generated["created"][0]
    assert live["status"] == "active", "plan 102: chat request = activation"
    assert "already live" not in generated["note"], (
        "plan 109/110: activation is NOT rendering — the note must not "
        "claim the CV without a pin"
    )
    assert "once pinned" in generated["note"]
    assert "variant_list" in generated["note"]

    drafted = await run_tool(
        db,
        "cv_synth_generate",
        uuid.UUID(_uid(auth_headers)),
        {
            "cv_id": str(cv["id"]),
            "refs": _refs(item),
            "action": "summarize",
        },
    )
    assert drafted["created"][0]["status"] == "active"
    assert "once pinned" in drafted["note"]

    updated = await run_tool(
        db,
        "cv_synth_update",
        uuid.UUID(_uid(auth_headers)),
        {"item_id": drafted["created"][0]["id"], "status": "active"},
    )
    assert updated["status"] == "active"


async def test_variant_tools_bind_in_main_chat_only():
    from app.ai.tools.langchain import main_chat_tool_keys

    listed = {t["key"]: t for t in list_tools()}
    assert listed["variant_list"]["scope"] == ToolScope.READ.value
    assert listed["variant_pin"]["scope"] == ToolScope.WRITE.value
    chat_keys = set(main_chat_tool_keys())
    assert {"variant_list", "variant_pin"} <= chat_keys
    # Plan-110 follow-up: variant TEXT generation is card-only in chat —
    # `cv_synth_generate` retired from the main-chat surface (Studio
    # copilot tool), so there is exactly one review surface.
    assert "cv_synth_generate" not in chat_keys
    assert sorted(listed["cv_synth_generate"]["audiences"]) == ["cv_builder"]
    assert not any(
        key.startswith("cv_synth_generate") or key.startswith("cv_synth_")
        for key in chat_keys
    ), "the cv_builder-audience variant family stays copilot-owned"


async def test_variant_list_slim_rows_and_verdict(client, db, auth_headers):
    item, variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv(client, auth_headers, db)
    plain = await run_tool(db, "variant_list", uuid.UUID(_uid(auth_headers)), {})
    row = next(r for r in plain["items"] if r["id"] == variant["id"])
    assert row["status"] == "active"
    assert row["language"] == "en"
    assert "verdict" not in row, "no CV passed — no verdicts"
    with_cv = await run_tool(
        db,
        "variant_list",
        uuid.UUID(_uid(auth_headers)),
        {"cv_id": str(cv["id"])},
    )
    row = next(r for r in with_cv["items"] if r["id"] == variant["id"])
    assert row["verdict"] == "not_pinned"
    del item


async def test_variant_pin_sets_default_and_promotes_drafts(client, db, auth_headers):
    item = await _item(db, _uid(auth_headers))
    cv = await _cv(client, auth_headers, db)

    async def _draft() -> dict:
        response = await client.post(
            "/api/v1/cv/synth/generate",
            json={"refs": _refs(item), "action": "summarize", "activate": False},
            headers=auth_headers,
        )
        return response.json()["items"][0]

    first = await _draft()
    second = await _draft()
    statuses = {
        row["id"]: row["status"]
        for row in (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    }
    assert statuses[first["id"]] == "draft", "drafts coexist in a slot"

    result = await run_tool(
        db,
        "variant_pin",
        uuid.UUID(_uid(auth_headers)),
        {"cv_id": str(cv["id"]), "variant_id": first["id"]},
    )
    assert result["pinned"] == {f"experience:{item.id}": first["id"]}
    assert "default" in result["note"]

    stored = (await client.get(f"/api/v1/cv/{cv['id']}", headers=auth_headers)).json()
    assert stored["context"]["synth_pins"] == {f"experience:{item.id}": first["id"]}, (
        "the pin rides the CV context"
    )
    assert stored["context"]["mode"] == "all", "selection fields preserved"

    statuses = {
        row["id"]: row["status"]
        for row in (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    }
    assert statuses[first["id"]] == "active", "plan 102: pin promotes drafts"
    assert statuses[second["id"]] == "draft", (
        "multi-active library: pinning one variant leaves its drawer mates alone"
    )


async def test_variant_pin_unpin_by_variant_and_by_slot(client, db, auth_headers):
    item, variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv(client, auth_headers, db)
    await run_tool(
        db,
        "variant_pin",
        uuid.UUID(_uid(auth_headers)),
        {"cv_id": str(cv["id"]), "variant_id": variant["id"]},
    )
    result = await run_tool(
        db,
        "variant_pin",
        uuid.UUID(_uid(auth_headers)),
        {"cv_id": str(cv["id"]), "variant_id": variant["id"], "unpin": True},
    )
    assert result["removed"] == [f"experience:{item.id}"]
    stored = (await client.get(f"/api/v1/cv/{cv['id']}", headers=auth_headers)).json()
    assert stored["context"]["synth_pins"] == {}

    await run_tool(
        db,
        "variant_pin",
        uuid.UUID(_uid(auth_headers)),
        {"cv_id": str(cv["id"]), "variant_id": variant["id"]},
    )
    result = await run_tool(
        db,
        "variant_pin",
        uuid.UUID(_uid(auth_headers)),
        {
            "cv_id": str(cv["id"]),
            "source_key": "experience",
            "item_id": str(item.id),
            "unpin": True,
        },
    )
    assert result["removed"] == [f"experience:{item.id}"]

    empty = await run_tool(
        db,
        "variant_pin",
        uuid.UUID(_uid(auth_headers)),
        {
            "cv_id": str(cv["id"]),
            "source_key": "experience",
            "item_id": str(item.id),
            "unpin": True,
        },
    )
    assert empty["removed"] == []
    assert "Nothing was pinned" in empty["note"]
    del item


async def test_variant_pin_guards(client, db, auth_headers):
    from app.core.errors import NotFoundError, ValidationError

    item = await _item(db, _uid(auth_headers))
    cv = await _cv(client, auth_headers, db)
    archived = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={"refs": _refs(item), "action": "summarize", "activate": False},
            headers=auth_headers,
        )
    ).json()["items"][0]
    await client.patch(
        f"/api/v1/cv/synth/{archived['id']}",
        json={"status": "archived"},
        headers=auth_headers,
    )
    with pytest.raises(ValidationError, match="Archived"):
        await run_tool(
            db,
            "variant_pin",
            uuid.UUID(_uid(auth_headers)),
            {"cv_id": str(cv["id"]), "variant_id": archived["id"]},
        )
    with pytest.raises(NotFoundError):
        await run_tool(
            db,
            "variant_pin",
            uuid.UUID(_uid(auth_headers)),
            {
                "cv_id": str(cv["id"]),
                "variant_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
            },
        )
    other_cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "Other", "kind": "resume"},
            headers=auth_headers,
        )
    ).json()
    from sqlalchemy import delete as sql_delete

    from app.models.cv_model import CvDocument

    await db.execute(
        sql_delete(CvDocument).where(CvDocument.id == uuid.UUID(other_cv["id"]))
    )
    await db.commit()
    with pytest.raises(NotFoundError):
        await run_tool(
            db,
            "variant_pin",
            uuid.UUID(_uid(auth_headers)),
            {
                "cv_id": other_cv["id"],
                "unpin": True,
                "source_key": "experience",
                "item_id": str(item.id),
            },
        )
    with pytest.raises(ValidationError):
        await run_tool(
            db,
            "variant_pin",
            uuid.UUID(_uid(auth_headers)),
            {"cv_id": str(cv["id"]), "unpin": True},
        )
    del item


async def test_bulk_archive_unarchive_delete(client, db, auth_headers):
    """One call moves many rows; stars are stripped; unknown ids fail."""
    from sqlalchemy import select

    from app.models.cv_synth_model import CvSynthItem

    item = await _item(db, _uid(auth_headers))
    cv = await _cv(client, auth_headers, db)

    ids = []
    for _ in range(3):
        row = await run_tool(
            db,
            "cv_synth_generate",
            uuid.UUID(_uid(auth_headers)),
            {"cv_id": str(cv["id"]), "refs": _refs(item), "action": "summarize"},
        )
        ids.append((row["created"][0]["id"]))

    response = await client.post(
        "/api/v1/cv/synth/bulk",
        json={"ids": ids, "action": "archive"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    rows = {
        row["id"]: row["status"]
        for row in (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    }
    assert all(rows[i] == "archived" for i in ids)

    stored = (
        (await db.execute(select(CvSynthItem).where(CvSynthItem.id.in_(ids))))
        .scalars()
        .all()
    )
    assert all(row.status == "archived" for row in stored), "bulk persisted archive"

    restore = await client.post(
        "/api/v1/cv/synth/bulk",
        json={"ids": ids, "action": "unarchive"},
        headers=auth_headers,
    )
    assert restore.status_code == 200
    rows = {
        row["id"]: row["status"]
        for row in (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    }
    # Restored as drafts (no cascade supersede on bulk restore).
    assert all(rows[i] == "draft" for i in ids)

    gone = await client.post(
        "/api/v1/cv/synth/bulk",
        json={"ids": ids, "action": "delete"},
        headers=auth_headers,
    )
    assert gone.status_code == 200
    assert set(gone.json()["deleted"]) == set(ids)
    remaining = (
        (
            await db.execute(
                select(CvSynthItem).where(
                    CvSynthItem.user_id == uuid.UUID(_uid(auth_headers))
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []

    unknown = await client.post(
        "/api/v1/cv/synth/bulk",
        json={"ids": ids, "action": "delete"},
        headers=auth_headers,
    )
    assert unknown.status_code in (400, 422)
    assert "Unknown variant" in unknown.json()["detail"]


async def test_bulk_archive_strips_star(client, db, auth_headers):
    item, row = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv(
        client,
        auth_headers,
        db,
        pins={f"experience:{item.id}": row["id"]},
    )
    response = await client.post(
        "/api/v1/cv/synth/bulk",
        json={"ids": [row["id"]], "action": "archive"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    stored = (await client.get(f"/api/v1/cv/{cv['id']}", headers=auth_headers)).json()
    pins = stored.get("context", {}).get("synth_pins") or {}
    assert not any(str(value) == row["id"] for value in pins.values())
