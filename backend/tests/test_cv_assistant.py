"""— CV builder copilot: ops, turn loop, SSE surface, registry."""

import json
import uuid
from datetime import date

from sqlalchemy import select

from app.ai.agents.cv_builder_chat import apply_operation, build_builder_context
from app.ai.tools import list_tools, run_tool
from app.models.user_model import User
from app.schemas.cv_assistant import (
    AddBlockOp,
    ApplyThemeOp,
    RemoveBlockOp,
    SetContextOp,
    SetOverrideOp,
    UpdateBlockPropsOp,
    UpdateDesignOp,
)
from app.seeds.cv_templates import seed_cv_template_bank
from app.services.cv_builder_service import CvBuilderService
from app.services.cv_pdf_service import PDFEngineUnavailable
from app.services.cv_service import CvService


async def _raise_engine_unavailable(*_args, **_kwargs):
    raise PDFEngineUnavailable("Server PDF engine not installed")


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name = ""
        data = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        events.append((name, json.loads(data) if data else {}))
    return events


async def _user_id(db) -> uuid.UUID:
    row = await db.execute(select(User).where(User.email == "student@example.com"))
    return row.scalars().first().id


async def _owned_cv(db, client, auth_headers, **overrides) -> tuple[object, dict]:
    payload = {"title": "Copilot CV", **overrides}
    created = await client.post("/api/v1/cv", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    cv = await CvService(db).get_owned(
        uuid.UUID(created.json()["id"]), await _user_id(db)
    )
    return cv, created.json()


async def _seed_bank(db) -> None:
    await seed_cv_template_bank(db)


# ------------------------------------------------------------- registry


def test_cv_builder_tools_registered():
    listed = {tool["key"]: tool for tool in list_tools()}
    for key in (
        "cv_read_state",
        "cv_review_visual",
        "cv_set_template",
        "cv_apply_theme",
        "cv_update_design",
        "cv_set_context",
        "cv_set_doc_options",
        "cv_add_block",
        "cv_remove_block",
        "cv_move_block",
        "cv_update_block_props",
        "cv_set_override",
    ):
        assert key in listed, key
        # The styling allowlist serves the general chat too: inspection
        # + restyle ops bind there; content/section editors stay owned
        # by the builder copilot only.
        chat_allowed = {
            "cv_read_state",
            "cv_review_visual",
            "cv_set_template",
            "cv_apply_theme",
            "cv_update_design",
            "cv_set_context",
        }
        expected = ["chat", "cv_builder"] if key in chat_allowed else ["cv_builder"]
        assert listed[key]["audiences"] == expected
        assert listed[key]["builtin"] is True
        assert listed[key]["requires_user"] is True
    assert listed["cv_set_template"]["scope"] == "write"
    assert listed["cv_read_state"]["scope"] == "read"


async def test_write_tool_requires_user(db):
    from app.core.errors import PermissionDeniedError

    try:
        await run_tool(
            db, "cv_set_template", None, {"cv_id": "x" * 8, "template_id": "y" * 8}
        )
    except PermissionDeniedError:
        return
    raise AssertionError("expected PermissionDeniedError")


# ----------------------------------------------------------- operations


async def test_apply_theme_duplicates_bank_template(client, db, auth_headers):
    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    from app.services.cv_builder_service import CvBuilderService

    original = await CvBuilderService(db).template_row(cv)

    result = await apply_operation(
        db, cv, ApplyThemeOp(op="apply_theme", theme_key="teal_modern")
    )
    assert result.ok, result.detail
    assert cv.template_id is not None and cv.template_id != original.id

    from app.services.cv_template_service import CvTemplateService

    row = await CvTemplateService(db).get_readable(cv.template_id, cv.user_id)
    assert row.author_user_id == cv.user_id
    assert row.content["design"]["accent_color"] == "#0f766e"
    bank = await CvTemplateService(db).get_readable(original.id, cv.user_id)
    assert bank.content["design"]["accent_color"] != "#0f766e"


async def test_second_customize_session_on_same_bank_template_appends(
    client, db, auth_headers
):
    """A later run styling the SAME bank template again duplicates it
    under the same private slug — the version must chain (v2), never
    collide with the first copy's v1 (uq_cv_templates_version)."""
    from app.services.cv_template_service import CvTemplateService

    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    from app.services.cv_builder_service import CvBuilderService

    bank = await CvBuilderService(db).template_row(cv)

    first = await apply_operation(
        db, cv, ApplyThemeOp(op="apply_theme", theme_key="teal_modern")
    )
    assert first.ok, first.detail
    first_version = (
        await CvTemplateService(db).get_readable(cv.template_id, cv.user_id)
    ).version
    first_key = (
        await CvTemplateService(db).get_readable(cv.template_id, cv.user_id)
    ).key
    # A fresh generate run would land back on the untouched bank row.
    cv.template_id = bank.id
    await db.commit()
    second = await apply_operation(
        db, cv, UpdateDesignOp(op="update_design", design={"base_size_pt": 9})
    )
    assert second.ok, second.detail
    row = await CvTemplateService(db).get_readable(cv.template_id, cv.user_id)
    assert row.author_user_id == cv.user_id
    assert row.key == first_key, "the same private chain continues"
    assert row.version == first_version + 1, "chain version must move forward"
    assert row.content["design"]["base_size_pt"] == 9


async def test_update_design_rejects_unknown_tokens(client, db, auth_headers):
    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    result = await apply_operation(
        db, cv, UpdateDesignOp(op="update_design", design={"not_a_token": 3})
    )
    assert not result.ok
    assert "Unknown design token" in result.detail


async def test_update_design_on_owned_template_publishes_version(
    client, db, auth_headers
):
    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    themed = await apply_operation(
        db, cv, ApplyThemeOp(op="apply_theme", theme_key="classic_navy")
    )
    assert themed.ok
    owned_id = cv.template_id

    from app.services.cv_template_service import CvTemplateService

    before = await CvTemplateService(db).get_readable(owned_id, cv.user_id)
    result = await apply_operation(
        db, cv, UpdateDesignOp(op="update_design", design={"base_size_pt": 9})
    )
    assert result.ok, result.detail
    after = await CvTemplateService(db).get_readable(cv.template_id, cv.user_id)
    assert after.key == before.key
    assert after.version == before.version + 1
    assert after.content["design"]["base_size_pt"] == 9


async def test_set_context_never_empties_the_cv(client, db, auth_headers):
    """Empty-outcome guard: an AI op selecting nothing (custom with an
    empty include, none without one, exclude covering all items) is
    refused — a CV with zero context renders nothing."""
    from app.schemas.cv_assistant import SetContextOp

    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    for op in (
        SetContextOp(op="set_context", mode="custom", include=[], exclude=[]),
        SetContextOp(op="set_context", mode="none", include=[], exclude=[]),
    ):
        result = await apply_operation(db, cv, op)
        assert not result.ok, result.detail
        assert "deselect everything" in result.detail

    # mode all without excludes is the reset-to-everything baseline.
    result = await apply_operation(
        db, cv, SetContextOp(op="set_context", mode="all", include=[], exclude=[])
    )
    assert result.ok, result.detail


async def test_read_state_flags_stale_selection_refs(client, db, auth_headers):
    """Custom selections saved against profile rows that later
    regenerated (new item ids) silently render nothing — the digest
    must name the stale refs so the copilot can repair them."""
    from app.ai.agents.cv_builder_chat import build_builder_context
    from app.schemas.cv import CvContextRef, CvContextSelection
    from app.services.cv_context_service import resolve_sources

    cv, _json = await _owned_cv(db, client, auth_headers)
    resolved = await resolve_sources(db, cv.user_id)
    source_key, items = next(iter(resolved.items()))
    fresh_id = items[0].item_id
    ghost_id = "0" * 8
    context = CvContextSelection.model_validate(cv.context or {})
    context.mode = "custom"
    context.include = [CvContextRef(source_key=source_key, item_id=fresh_id)]
    context.exclude = [CvContextRef(source_key=source_key, item_id=ghost_id)]
    cv.context = context.model_dump(mode="json")
    await db.commit()

    digest = await build_builder_context(db, cv)
    selection = digest["selection"]
    assert selection["mode"] == "custom"
    assert f"{source_key}:{ghost_id}" in selection["stale"]
    assert f"{source_key}:{fresh_id}" in selection["include"]


async def _pinned_project_variant(
    client, db, auth_headers, uid
) -> tuple[object, object]:
    """A project item whose pinned variant replaces description AND
    bullets on a CV (mode custom keeps only that item)."""
    from app.models.experience_model import ExperienceItem

    item = ExperienceItem(
        user_id=uid,
        kind="project",
        title="Desktop Assistant",
        org_name="Neuronection",
        start=date(2024, 1, 1),
        description="Long original project description from the profile",
        status="active",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    row = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={
                "refs": [{"source_key": "projects", "item_id": str(item.id)}],
                "action": "summarize",
            },
            headers=auth_headers,
        )
    ).json()["items"][0]
    variant_id = row["id"]
    patched = await client.patch(
        f"/api/v1/cv/synth/{variant_id}",
        json={
            "status": "active",
            "payload": {
                "description": "Concise variant description",
                "achievements": [{"text": "Variant bullet"}],
            },
        },
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    saved = await client.put(
        f"/api/v1/cv/{cv.id}/context",
        json={
            "mode": "custom",
            "include": [{"source_key": "projects", "item_id": str(item.id)}],
            "synth_pins": {f"projects:{item.id}": variant_id},
        },
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    fresh = await CvService(db).get_owned(cv.id, cv.user_id)
    await db.refresh(fresh)
    return fresh, item


async def test_read_state_sources_carry_effective_variant_layers(
    client, db, auth_headers
):
    """cv_read_state reports what the CV PRINTS: a pinned variant's text
    replaces the profile's in `sources` (never both layers' texts side
    by side), `variant` flags the swap, and off-CV pool rows stay
    label+detail only."""
    fresh, item = await _pinned_project_variant(
        client, db, auth_headers, await _user_id(db)
    )
    digest = await build_builder_context(db, fresh)
    entry = next(
        row
        for row in digest["sources"]["projects"]["items"]
        if row["item_id"] == str(item.id)
    )
    assert entry["selected"] is True
    assert entry["variant"] is True
    assert entry["description"] == "Concise variant description"
    assert entry["bullets"] == ["Variant bullet"]
    assert "Long original project description" not in json.dumps(digest["sources"])


async def test_read_state_off_cv_pool_rows_stay_light(client, db, auth_headers):
    uid = await _user_id(db)
    from app.models.experience_model import ExperienceItem

    outsider = ExperienceItem(
        user_id=uid,
        kind="project",
        title="Off CV Project",
        org_name="Lab",
        start=date(2024, 3, 1),
        description="Not included anywhere",
        status="active",
    )
    db.add(outsider)
    await db.commit()
    await db.refresh(outsider)
    waitstaff = ExperienceItem(
        user_id=uid,
        kind="job",
        title="Bar Staff",
        org_name="Coffee Bar",
        start=date(2023, 5, 1),
        description="Off-CV job",
        status="active",
    )
    db.add(waitstaff)
    await db.commit()
    await db.refresh(waitstaff)
    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    await client.put(
        f"/api/v1/cv/{cv.id}/context",
        json={
            "mode": "custom",
            "include": [
                {"source_key": "summary", "item_id": "summary"},
                {"source_key": "projects", "item_id": str(outsider.id)},
            ],
        },
        headers=auth_headers,
    )
    fresh = await CvService(db).get_owned(cv.id, cv.user_id)
    await db.refresh(fresh)
    digest = await build_builder_context(db, fresh)
    experience = digest["sources"]["experience"]["items"]
    assert experience and all(row["selected"] is False for row in experience)
    assert all("description" not in row and "bullets" not in row for row in experience)


async def test_read_state_rendered_sections_report_layers(client, db, auth_headers):
    """`rendered` is the deterministic what-prints truth per entry:
    each printed item's headline with its own description/bullet layers,
    and per-section counts — one bulleted item never reads as
    "the section prints bullets"."""
    uid = await _user_id(db)
    from app.models.experience_model import ExperienceAchievement, ExperienceItem

    plain = ExperienceItem(
        user_id=uid,
        kind="project",
        title="Host Web Services",
        org_name="Lab",
        start=date(2024, 2, 1),
        description="A dense project description",
        status="active",
    )
    db.add(plain)
    await db.commit()
    await db.refresh(plain)
    bulleted = ExperienceItem(
        user_id=uid,
        kind="project",
        title="Desktop Assistant",
        org_name="Neuronection",
        start=date(2024, 1, 1),
        description="A concise project description",
        status="active",
    )
    db.add(bulleted)
    await db.commit()
    await db.refresh(bulleted)
    db.add(ExperienceAchievement(experience_id=bulleted.id, text="Profile bullet"))
    await db.commit()

    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    added = await apply_operation(
        db,
        cv,
        AddBlockOp(
            op="add_block",
            kind="items",
            props={"title": "Projects", "source_key": "projects"},
        ),
    )
    assert added.ok, added.detail
    block_index = len(cv.working_content["blocks"]) - 1
    silenced = await apply_operation(
        db,
        cv,
        UpdateBlockPropsOp(
            op="update_block_props",
            block_index=block_index,
            props={"show_achievements": False},
        ),
    )
    assert silenced.ok, silenced.detail
    fresh = await CvService(db).get_owned(cv.id, cv.user_id)
    await db.refresh(fresh)

    digest = await build_builder_context(db, fresh)
    projects = next(
        section for section in digest["rendered"] if section["section"] == "Projects"
    )
    assert projects["items"] == 2
    assert projects["with_description"] == 2
    assert projects["with_bullets"] == 0, "the prop gate silences every bullet"
    host = next(
        entry for entry in projects["entries"] if "Host Web Services" in entry["title"]
    )
    assert host["title"] == "Host Web Services — Lab"
    assert host["description"] is True and host["bullets"] is False

    unwrapped = await apply_operation(
        db,
        fresh,
        UpdateBlockPropsOp(
            op="update_block_props",
            block_index=block_index,
            props={"show_achievements": True},
        ),
    )
    assert unwrapped.ok, unwrapped.detail
    fresh = await CvService(db).get_owned(cv.id, cv.user_id)
    await db.refresh(fresh)
    projects = next(
        section
        for section in (await build_builder_context(db, fresh))["rendered"]
        if section["section"] == "Projects"
    )
    assert (
        next(
            entry
            for entry in projects["entries"]
            if "Host Web Services" in entry["title"]
        )["bullets"]
        is False
    )
    desktop = next(
        entry for entry in projects["entries"] if "Desktop Assistant" in entry["title"]
    )
    assert desktop["bullets"] is True and desktop["bullet_count"] == 1
    assert projects["with_bullets"] == 1, "exactly one entry prints bullets"


async def test_critique_pages_prompt_carries_rendered_truth(monkeypatch):
    """The visual critique prompt embeds the rendered ground truth and
    its system line binds content claims to it."""
    import app.ai.agents.cv_template_designer as designer

    captured: dict = {}

    async def _fake_invoke(_db, _task, _schema, system, user, **_kwargs):
        captured["system"] = system
        captured["user"] = user
        return designer.CvVisualCritique()

    monkeypatch.setattr(designer, "ainvoke_structured", _fake_invoke)
    await designer.critique_pages(
        None,
        None,
        template_summary="t",
        lint={},
        max_pages=1,
        page_count=1,
        rendered=[
            {
                "section": "Projects",
                "items": 2,
                "entries": [
                    {
                        "title": "Host Web Services — Lab",
                        "description": True,
                        "bullets": False,
                        "bullet_count": 0,
                    },
                    {
                        "title": "Desktop Assistant — Neuronection",
                        "description": True,
                        "bullets": True,
                        "bullet_count": 1,
                    },
                ],
                "with_description": 2,
                "with_bullets": 1,
            }
        ],
    )
    from app.ai.agents.context import parse_context

    ctx = parse_context(captured["user"])
    assert ctx["rendered"][0]["with_bullets"] == 1
    assert ctx["rendered"][0]["entries"][1]["bullets"] is True
    assert ctx["rendered"][0]["section"] == "Projects"
    assert "with_bullets" in captured["system"]


async def test_template_switch_grounded_on_layout_facts(client, db, auth_headers):
    """Template switches are verified, not narrated from a name:
    `templates` carry factual layout/ATS facts, the op detail states the
    applied template's layout, and a styling op's result carries `after`
    (applied template + rendered layers) so a chat claim like "this
    two-column template creates room beside the narrative" can only
    follow the actual design."""
    await _seed_bank(db)
    cv, created = await _owned_cv(db, client, auth_headers)
    user_id = await _user_id(db)
    state = await run_tool(db, "cv_read_state", user_id, {"cv_id": created["id"]})
    assert state["template"]["layout"] in ("single", "sidebar")
    assert all("layout" in row and "ats_safe" in row for row in state["templates"]), (
        "every candidate template carries its factual layout"
    )
    candidate = next(row for row in state["templates"] if not row["ats_safe"])
    out = await run_tool(
        db,
        "cv_set_template",
        user_id,
        {"cv_id": created["id"], "template_id": candidate["id"]},
    )
    assert out["ok"] is True
    assert "layout" in out["detail"], out["detail"]
    assert out["after"]["template"] == candidate["title"]
    assert out["after"]["layout"] == candidate["layout"]
    assert out["after"]["estimated_pages"] >= 1
    assert isinstance(out["after"]["rendered"], list)


async def test_set_context_validates_items(client, db, auth_headers):
    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    result = await apply_operation(
        db,
        cv,
        SetContextOp(
            op="set_context",
            mode="custom",
            include=[{"source_key": "experience", "item_id": "nope"}],
            exclude=[],
        ),
    )
    assert not result.ok
    assert "Unknown context item" in result.detail


async def test_fresh_cv_default_template_is_collation_proof(client, db, auth_headers):
    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    row = await CvBuilderService(db).template_row(cv)
    assert row is not None and row.key == "ats-classic"


async def test_block_ops_apply_and_validate(client, db, auth_headers):
    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)

    added = await apply_operation(
        db,
        cv,
        AddBlockOp(
            op="add_block",
            kind="custom_text",
            props={"title": "Highlights", "text": "Hello"},
        ),
    )
    assert added.ok, added.detail
    blocks = cv.working_content["blocks"]
    assert blocks[-1]["kind"] == "custom_text"

    bad = await apply_operation(
        db, cv, RemoveBlockOp(op="remove_block", block_index=24)
    )
    assert not bad.ok

    skills_index = next(
        index for index, block in enumerate(blocks) if block["kind"] == "skills"
    )
    patched = await apply_operation(
        db,
        cv,
        UpdateBlockPropsOp(
            op="update_block_props",
            block_index=skills_index,
            props={"show_levels": True},
        ),
    )
    assert patched.ok, patched.detail
    assert cv.working_content["blocks"][skills_index]["props"]["show_levels"] is True

    sidebar_add = await apply_operation(
        db,
        cv,
        AddBlockOp(
            op="add_block",
            kind="languages",
            props={"title": "Languages"},
            area="sidebar",
        ),
    )
    assert sidebar_add.ok, sidebar_add.detail
    last = cv.working_content["blocks"][-1]
    assert last["kind"] == "languages" and last["area"] == "sidebar"


async def test_set_override_requires_selected_item(
    client, db, auth_headers, profile_ready
):
    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    missing = await apply_operation(
        db,
        cv,
        SetOverrideOp(
            op="set_override",
            source_key="experience",
            item_id="missing",
            field="description",
            value="x",
        ),
    )
    assert not missing.ok


async def test_builder_context_digest_shape(client, db, auth_headers, profile_ready):
    await _seed_bank(db)
    cv, _json = await _owned_cv(db, client, auth_headers)
    digest = await build_builder_context(db, cv)
    assert digest["document"]["title"] == "Copilot CV"
    assert digest["template"]["id"] is not None
    assert len(digest["templates"]) >= 1
    assert all("index" in block for block in digest["blocks"])
    assert "interests" in digest["sources"]
    assert "metrics" in digest and "lint" in digest
    assert {theme["key"] for theme in digest["themes"]} >= {"teal_modern"}


# ----------------------------------------------------------------- turn


async def _open_builder_session(client, auth_headers, cv_id: str) -> str:
    session = await client.post(
        "/api/v1/chat/sessions",
        json={
            "title": "CV assistant",
            "context": {"surface": "cv_builder", "cv_id": cv_id},
        },
        headers=auth_headers,
    )
    assert session.status_code == 201, session.text
    return session.json()["id"]


async def test_assistant_turn_stream_applies_ops(
    client, db, auth_headers, profile_ready, monkeypatch
):
    monkeypatch.setattr(
        "app.ai.agents.cv_builder_chat.measure_pages",
        _raise_engine_unavailable,
    )
    await _seed_bank(db)
    cv, cv_json = await _owned_cv(db, client, auth_headers)
    original_template_id = cv.template_id
    session_id = await _open_builder_session(client, auth_headers, cv_json["id"])

    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "switch to another template"},
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    names = [name for name, _payload in events]
    assert names[0] == "flow_started"
    assert events[0][1]["flow"] == "cv_builder"
    assert "delta" in names
    assert "builder_state" in names
    assert "meta" in names
    assert names[-1] == "flow_finished"
    assert "error" not in names

    tool_calls = [payload for name, payload in events if name == "tool_call"]
    assert any(call["name"] == "cv_set_template" for call in tool_calls)
    assert all(call["status"] == "done" for call in tool_calls)
    read_state = next(call for call in tool_calls if call["name"] == "cv_read_state")
    assert read_state["title"] == "Reading the builder state"
    assert isinstance(read_state["duration_ms"], int)
    assert "blocks" in read_state["result"]
    assert all("duration_ms" in call for call in tool_calls)
    assert all("durationMs" not in call for call in tool_calls)

    state = next(payload for name, payload in events if name == "builder_state")
    assert state["document"]["id"] == cv_json["id"]
    assert state["document"]["template_id"] not in (None, str(original_template_id))
    assert state["html"]
    assert state["resolution"]["snapshot_index"]
    assert any(op["ok"] for op in state["operations"])
    assert state["version"] is not None

    refreshed = await client.get(f"/api/v1/cv/{cv_json['id']}", headers=auth_headers)
    assert refreshed.json()["template_id"] == state["document"]["template_id"]

    versions = (
        await client.get(f"/api/v1/cv/{cv_json['id']}/versions", headers=auth_headers)
    ).json()
    assert any(v["created_by"] == "ai_apply" for v in versions)

    history = await client.get(
        f"/api/v1/chat/sessions/{session_id}/messages", headers=auth_headers
    )
    rows = history.json()
    assert [row["role"] for row in rows] == ["user", "assistant"]
    meta = rows[1]["metadata_json"]
    assert meta["surface"] == "cv_builder"
    assert meta["operations"]
    assert meta["version"] is not None
    tool_names = [tool["name"] for tool in meta["tools"]]
    assert "cv_read_state" in tool_names
    assert "cv_set_template" in tool_names
    assert all(isinstance(tool["start_ms"], int) for tool in meta["tools"])
    assert all(isinstance(tool["duration_ms"], int) for tool in meta["tools"])
    assert all(len(tool["args_summary"]) <= 160 for tool in meta["tools"])
    assert all(len(tool["result_summary"]) <= 160 for tool in meta["tools"])
    assert [node["id"] for node in meta["nodes"]] == ["ground", "plan", "apply"]
    assert all(node["status"] == "done" for node in meta["nodes"])
    assert all(
        isinstance(node["start_ms"], int) and isinstance(node["duration_ms"], int)
        for node in meta["nodes"]
    )
    assert meta["nodes"][0]["start_ms"] == 0


async def test_builder_turn_failure_persists_partial_trace(
    client, db, auth_headers, profile_ready, monkeypatch
):
    """A turn that dies mid-`plan` still persists what ran: the
    exception path closes the open node windows and saves the trace
    gathered so far."""
    from app.ai.gateway import StructuredStream
    from app.core.errors import DomainError

    await _seed_bank(db)
    _cv, cv_json = await _owned_cv(db, client, auth_headers)
    session_id = await _open_builder_session(client, auth_headers, cv_json["id"])

    async def _explode(self, *args, **kwargs):
        raise DomainError("plan exploded")
        yield  # pragma: no cover

    monkeypatch.setattr(StructuredStream, "chunks", _explode)
    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "rewrite the summary section"},
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    names = [name for name, _payload in events]
    assert "flow_failed" in names
    assert "builder_state" not in names
    assert "done" not in names

    rows = (
        await client.get(
            f"/api/v1/chat/sessions/{session_id}/messages", headers=auth_headers
        )
    ).json()
    assert rows[-1]["role"] == "assistant"
    meta = rows[-1]["metadata_json"]
    assert meta["stream_interrupted"] is True
    assert meta["surface"] == "cv_builder"
    assert [node["id"] for node in meta["nodes"]] == ["ground", "plan"]
    assert meta["nodes"][0]["status"] == "done"
    assert meta["nodes"][1]["status"] == "failed"
    assert [tool["name"] for tool in meta["tools"]] == ["cv_read_state"]


async def test_regular_session_untouched_by_builder_flow(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    """A session without the cv_builder context runs the normal chatbot."""
    session = await client.post(
        "/api/v1/chat/sessions", json={"title": "chat"}, headers=auth_headers
    )
    response = await client.post(
        f"/api/v1/chat/sessions/{session.json()['id']}/messages",
        json={"content": "data science careers"},
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    flow_started = next(payload for name, payload in events if name == "flow_started")
    assert flow_started["flow"] == "chat"
    assert all(name != "builder_state" for name, _ in events)


async def test_builder_session_edit_keeps_copilot(
    client, db, auth_headers, profile_ready, monkeypatch
):
    """Edit-and-resend rides the same turn flow — copilot ops included."""
    monkeypatch.setattr(
        "app.ai.agents.cv_builder_chat.measure_pages",
        _raise_engine_unavailable,
    )
    await _seed_bank(db)
    _cv, cv_json = await _owned_cv(db, client, auth_headers)
    session_id = await _open_builder_session(client, auth_headers, cv_json["id"])
    await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "switch template"},
        params={"stream": "true"},
        headers=auth_headers,
    )
    rows = (
        await client.get(
            f"/api/v1/chat/sessions/{session_id}/messages", headers=auth_headers
        )
    ).json()

    edited = await client.post(
        f"/api/v1/chat/messages/{rows[0]['id']}/edit",
        json={"content": "apply a theme instead"},
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    events = _parse_sse(edited.text)
    assert events[0][1]["flow"] == "cv_builder"
    tool_calls = [payload for name, payload in events if name == "tool_call"]
    assert any(call["name"] == "cv_apply_theme" for call in tool_calls)


async def test_builder_session_validates_cv_ownership(
    client, db, auth_headers, profile_ready
):
    await _seed_bank(db)
    _cv, cv_json = await _owned_cv(db, client, auth_headers)
    other_headers = await _second_user(client)
    session = await client.post(
        "/api/v1/chat/sessions",
        json={
            "title": "sneaky",
            "context": {"surface": "cv_builder", "cv_id": cv_json["id"]},
        },
        headers=other_headers,
    )
    response = await client.post(
        f"/api/v1/chat/sessions/{session.json()['id']}/messages",
        json={"content": "switch template"},
        params={"stream": "true"},
        headers=other_headers,
    )
    assert response.status_code == 404


async def test_visual_review_degrades_without_chromium(
    client, db, auth_headers, profile_ready, monkeypatch
):
    await _seed_bank(db)
    _cv, cv_json = await _owned_cv(db, client, auth_headers)
    monkeypatch.setattr(
        "app.ai.agents.cv_builder_chat.measure_pages",
        _raise_engine_unavailable,
    )
    session_id = await _open_builder_session(client, auth_headers, cv_json["id"])
    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "review the layout and fix the overflow"},
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[-1] == "flow_finished"
    review = next(
        payload
        for name, payload in events
        if name == "tool_call" and payload["name"] == "cv_review_visual"
    )
    assert "Chromium" in review["result"]
    state = next(payload for name, payload in events if name == "builder_state")
    assert state["critique"] is None


async def _second_user(client) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{uuid.uuid4().hex[:10]}@example.com",
            "password": "Str0ngPass!23",
            "full_name": "Second User",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ------------------------------------------------------- ops endpoint (71.1)


async def test_ops_endpoint_applies_design_and_resyncs_template(
    client, db, auth_headers
):
    """UI restyling rides the same audited apply_operation path; the
    response template_id reflects the private-copy re-pointing."""
    await _seed_bank(db)
    cv, created = await _owned_cv(db, client, auth_headers)
    before = (
        await client.get(f"/api/v1/cv/{cv.id}/design", headers=auth_headers)
    ).json()
    assert before["design"]["accent_color"]
    assert before["template"]["owned"] is False

    response = await client.post(
        f"/api/v1/cv/{created['id']}/ops",
        json={
            "ops": [
                {
                    "op": "update_design",
                    "design": {"accent_color": "#b91c1c", "line_height": 1.5},
                }
            ]
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["results"][0]["ok"] is True
    state = body["state"]
    assert state["document"]["template_id"], "a private copy was created"
    assert state["document"]["template_id"] != before["template"]["id"]
    assert state["critique"] is None

    design = (
        await client.get(f"/api/v1/cv/{cv.id}/design", headers=auth_headers)
    ).json()
    assert design["design"]["accent_color"] == "#b91c1c"
    assert design["design"]["line_height"] == 1.5
    assert design["template"]["owned"] is True


async def test_ops_endpoint_rejects_unknown_cv_and_bad_ops(client, db, auth_headers):
    response = await client.post(
        f"/api/v1/cv/{uuid.uuid4()}/ops",
        json={"ops": [{"op": "set_doc_options", "page_size": "a4"}]},
        headers=auth_headers,
    )
    assert response.status_code == 404

    cv, created = await _owned_cv(db, client, auth_headers)
    response = await client.post(
        f"/api/v1/cv/{created['id']}/ops",
        json={"ops": [{"op": "update_design", "design": {"accent_color": "red"}}]},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text

    response = await client.post(
        f"/api/v1/cv/{created['id']}/ops",
        json={"ops": [{"op": "set_doc_options", "page_size": "a4"}]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["ok"] is True


async def test_ops_endpoint_is_owner_scoped(client, db, auth_headers):
    cv, created = await _owned_cv(db, client, auth_headers)
    other = await _second_user(client)
    response = await client.post(
        f"/api/v1/cv/{created['id']}/ops",
        json={"ops": [{"op": "set_doc_options", "page_size": "letter"}]},
        headers=other,
    )
    assert response.status_code == 404, response.text


def test_design_patch_coerces_the_models_number_voice():
    """The reviewer's densify op with `base_size_pt: 8.5` validates —
    fraction floats round to the int token; int floats widen to float
    — instead of being rejected every polish round."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.cv_template import DesignTokens

    from app.ai.agents.cv_builder_chat import _design_candidate

    base = DesignTokens().model_dump(mode="json")
    candidate = _design_candidate(
        base, {"base_size_pt": 8.5, "spacing_scale": 0.9, "item_gap_mm": 1}
    )
    tokens = DesignTokens.model_validate(candidate)
    assert tokens.base_size_pt == 8, (
        "8.5 rounds down — banker's rounding, still compact"
    )
    assert tokens.spacing_scale == 0.9 and tokens.item_gap_mm == 1
    with pytest.raises(ValidationError):
        _design_candidate(base, {"base_size_pt": "big"})
