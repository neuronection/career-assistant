""": tool registry v2 — schemas, governance, execution, plugins."""

import pytest
from pydantic import BaseModel

from app.ai.tools import (
    AITool,
    get_tool,
    list_tools,
    register_tool,
    reset_registry,
    run_tool,
)
from app.core.errors import DomainError, PermissionDeniedError


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    reset_registry()


class _EchoInput(BaseModel):
    text: str


async def _echo(db, ctx, args: _EchoInput):
    return {"echo": args.text, "user_id": ctx.user_id}


def test_builtin_registry_declarations():
    listed = {t["key"]: t for t in list_tools()}
    assert set(listed) == {
        "search_jobs",
        "search_postings",
        "get_posting",
        "similar_postings",
        "my_notifications",
        "run_autopilot",
        "my_autopilot",
        "compare_jobs",
        # — CV builder copilot family
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
    }
    assert all(t["builtin"] for t in listed.values())
    non_cv = {k: t for k, t in listed.items() if not k.startswith("cv_")}
    assert all(
        t["scope"] == "read" for k, t in non_cv.items() if k != "my_notifications"
    )
    assert non_cv["my_notifications"]["scope"] == "write"
    assert listed["cv_read_state"]["scope"] == "read"
    assert listed["cv_review_visual"]["scope"] == "read"
    assert all(
        listed[key]["scope"] == "write"
        for key in listed
        if key.startswith("cv_") and key not in ("cv_read_state", "cv_review_visual")
    )
    assert listed["search_postings"]["requires_user"] is True
    assert listed["run_autopilot"]["requires_user"] is True
    assert listed["my_autopilot"]["requires_user"] is True
    for key, entry in listed.items():
        schema = entry["input_schema"]
        assert schema.get("type") == "object", key
        assert schema.get("properties"), key


def test_get_tool_rejects_unknown():
    with pytest.raises(DomainError, match="Unknown tool"):
        get_tool("nope")


async def test_run_tool_validates_and_passes_user(db):
    result = await run_tool(db, "search_jobs", None, {"query": "nurse"})
    assert isinstance(result, list)
    with pytest.raises(DomainError, match="Invalid input for tool search_jobs"):
        await run_tool(db, "search_jobs", None, {"limit": 3})


async def test_run_tool_enforces_requires_user(db):
    with pytest.raises(PermissionDeniedError, match="requires a signed-in user"):
        await run_tool(db, "search_postings", None, {"query": "python"})
    # Read-only tool without the flag works unscoped:
    assert await run_tool(db, "get_posting", None, {"ref": "ABCD2345"}) is not None


async def test_registered_plugin_executes(db):
    tool = AITool(
        key="echo",
        title="Echo",
        description="test tool",
        input_model=_EchoInput,
        handler=_echo,
        requires_user=True,
    )
    register_tool(tool)
    assert (await run_tool(db, "echo", "user-1", {"text": "hi"}))["echo"] == "hi"


async def test_get_posting_error_shape(db):
    result = await run_tool(db, "get_posting", None, {"ref": "ZZZZZZZZ"})
    assert "error" in result


async def test_compare_jobs_tool_grounds_on_catalog(
    db, auth_headers, profile_ready, seeded_catalog
):
    from sqlalchemy import select

    from app.models.user_model import User

    user = (
        (await db.execute(select(User).where(User.email == "student@example.com")))
        .scalars()
        .first()
    )
    result = await run_tool(
        db,
        "compare_jobs",
        user.id,
        {"refs": ["software-developer", "nurse"]},
    )
    entries = result["comparison"]
    assert [e["code"] for e in entries] == ["software-developer", "nurse"]
    for entry in entries:
        assert 0 <= entry["fit_score"] <= 10
        assert "skills" in entry["dimensions"]
        assert entry["education_level"]
        assert entry["demand_outlook"]
    assert "not found" not in result.get("error", "")


async def test_compare_jobs_tool_validates_and_reports_unknown(db):
    with pytest.raises(PermissionDeniedError, match="requires a signed-in user"):
        await run_tool(db, "compare_jobs", None, {"refs": ["a", "b"]})
    with pytest.raises(DomainError, match="Invalid input for tool compare_jobs"):
        await run_tool(db, "compare_jobs", "user-1", {"refs": ["only-one"]})
    result = await run_tool(
        db, "compare_jobs", "user-1", {"refs": ["ghost-job", "also-ghost"]}
    )
    assert "error" in result


async def test_notification_write_flow_through_registry(db, kinds):
    """The write-scope tool really mutes through the registry path."""
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.models.engagement_model import NotificationKind, NotificationKindPref
    from app.models.user_model import User

    kind = (await db.execute(select(NotificationKind))).scalars().first()
    user = User(email="tool-mute@example.com", password_hash=hash_password("pw123456"))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    result = await run_tool(
        db,
        "my_notifications",
        user.id,
        {"message": f"mute {kind.key.replace('_', ' ')} please"},
    )
    assert "muted" in result
    pref = (
        (
            await db.execute(
                select(NotificationKindPref).where(
                    NotificationKindPref.user_id == user.id,
                    NotificationKindPref.kind_id == kind.id,
                )
            )
        )
        .scalars()
        .first()
    )
    assert pref is not None and pref.enabled is False


def test_plugin_allowlist_gates_entry_points(monkeypatch):
    """Entry-point tools register only when allowlisted (connector pattern)."""
    from importlib import metadata as importlib_metadata

    class _FakeEP:
        name = "echo"

        def load(self):
            # entry points resolve to a callable; the registry calls it once
            return lambda: AITool(
                key="echo",
                title="Echo",
                description="plugin",
                input_model=_EchoInput,
                handler=_echo,
            )

    monkeypatch.setattr(
        importlib_metadata,
        "entry_points",
        lambda group: [_FakeEP()] if group == "career_assistant.tools" else [],
    )
    reset_registry()
    assert all(t["key"] != "echo" for t in list_tools())

    from app.core.config import settings

    monkeypatch.setattr(settings, "TOOL_PLUGINS_ALLOWLIST", ["echo"])
    reset_registry()
    assert any(t["key"] == "echo" for t in list_tools())
