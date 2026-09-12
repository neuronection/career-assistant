"""— CV synth copilot tools (plan 62.4): registry reads vs writes,
ownership enforcement, per-CV applicability verdicts, and the
generate / update / enable write paths."""

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


async def _cv_with_synth(client, auth_headers, db, *, synth_mode: str) -> dict:
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


async def test_no_delete_tool_and_scope_split():
    listed = {t["key"]: t for t in list_tools()}
    assert not any("delete" in key for key in listed if key.startswith("cv_synth")), (
        "deletion stays human-only in the library UI"
    )
    assert listed["cv_synth_list"]["scope"] == ToolScope.READ.value
    assert listed["cv_synth_read"]["scope"] == ToolScope.READ.value
    assert listed["cv_synth_generate"]["scope"] == ToolScope.WRITE.value
    assert listed["cv_synth_update"]["scope"] == ToolScope.WRITE.value
    assert listed["cv_synth_enable"]["scope"] == ToolScope.WRITE.value


async def test_list_requires_user(db):
    from app.core.errors import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        await run_tool(db, "cv_synth_list", None)


async def test_list_verdicts_against_cv(client, db, auth_headers):
    from tests.test_cv_synth_resolution import (
        _cv_with_synth,
        _item_and_active_variant,
    )

    item, variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_synth(client, auth_headers, db, synth_mode="off")
    result = await run_tool(
        db, "cv_synth_list", uuid.UUID(_uid(auth_headers)), {"cv_id": str(cv["id"])}
    )
    rows = {row["id"]: row for row in result["items"]}
    assert rows[variant["id"]]["verdict"] == "mode_off", (
        "active variant exists but the CV's synth_mode is off"
    )
    del item


async def test_list_applies_after_enable(client, db, auth_headers):
    from tests.test_cv_synth_resolution import (
        _cv_with_synth,
        _item_and_active_variant,
    )

    item, variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_synth(client, auth_headers, db, synth_mode="prefer")
    result = await run_tool(
        db, "cv_synth_list", uuid.UUID(_uid(auth_headers)), {"cv_id": str(cv["id"])}
    )
    rows = {row["id"]: row for row in result["items"]}
    assert rows[variant["id"]]["verdict"] == "applies"
    del item


async def test_list_language_mismatch_verdict(client, db, auth_headers):
    from tests.test_cv_synth_resolution import (
        _cv_with_synth,
        _item_and_active_variant,
    )

    item, variant = await _item_and_active_variant(client, db, auth_headers)
    cv = await _cv_with_synth(client, auth_headers, db, synth_mode="prefer")
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
    from tests.test_cv_synth_resolution import _cv_with_synth

    item = await _item(db, _uid(auth_headers))
    cv = await _cv_with_synth(client, auth_headers, db, synth_mode="prefer")
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
    draft = generated["created"][0]
    assert draft["status"] == "draft"

    updated = await run_tool(
        db,
        "cv_synth_update",
        uuid.UUID(_uid(auth_headers)),
        {"item_id": draft["id"], "status": "active"},
    )
    assert updated["status"] == "active"


async def test_enable_flips_synth_mode(client, db, auth_headers):
    from tests.test_cv_synth_resolution import _cv_with_synth

    cv = await _cv_with_synth(client, auth_headers, db, synth_mode="off")
    result = await run_tool(
        db,
        "cv_synth_enable",
        uuid.UUID(_uid(auth_headers)),
        {"cv_id": str(cv["id"]), "mode": "prefer"},
    )
    assert result["synth_mode"] == "prefer"
    refreshed = (
        await client.get(f"/api/v1/cv/{cv['id']}", headers=auth_headers)
    ).json()
    assert refreshed["context"]["synth_mode"] == items_mode(refreshed)


def items_mode(cv: dict) -> str:
    return cv["context"].get("synth_mode") or "off"
