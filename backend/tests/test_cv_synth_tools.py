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
    assert "live" in generated["note"]

    drafted = await run_tool(
        db,
        "cv_synth_generate",
        uuid.UUID(_uid(auth_headers)),
        {
            "cv_id": str(cv["id"]),
            "refs": _refs(item),
            "action": "summarize",
            "activate": False,
        },
    )
    assert drafted["created"][0]["status"] == "draft"
    assert "library" in drafted["note"]

    updated = await run_tool(
        db,
        "cv_synth_update",
        uuid.UUID(_uid(auth_headers)),
        {"item_id": drafted["created"][0]["id"], "status": "active"},
    )
    assert updated["status"] == "active"
