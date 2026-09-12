"""Tool registry: data, not code.

Built-ins auto-register at import; plugins arrive via the
``career_assistant.tools`` entry-point group and are **admin-opt-in**
through the ``TOOL_PLUGINS_ALLOWLIST`` setting (they run in-process,
exactly like connector plugins).
"""

from __future__ import annotations

import logging
from importlib import metadata
from typing import Any, Optional

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools.base import AITool, ToolContext
from app.core.errors import DomainError, PermissionDeniedError

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "career_assistant.tools"


def _builtins() -> list[AITool]:
    from app.ai.tools.builtin import BUILTIN_TOOLS
    from app.ai.tools.cv_builder import CV_BUILDER_TOOLS
    from app.ai.tools.cv_synth import CV_SYNTH_TOOLS

    return [*BUILTIN_TOOLS, *CV_BUILDER_TOOLS, *CV_SYNTH_TOOLS]


_registry: dict[str, AITool] = {}
_plugins_loaded = False


def _ensure_builtins() -> None:
    if not _registry:
        for tool in _builtins():
            _registry[tool.key] = tool


def plugin_allowed(key: str) -> bool:
    from app.core.config import settings

    allowlist = getattr(settings, "TOOL_PLUGINS_ALLOWLIST", None) or []
    return key in allowlist


def _load_plugins() -> None:
    """Entry-point discovery — plugin keys are opt-in via the allowlist."""
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    _ensure_builtins()
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        return
    for ep in eps:
        try:
            tool = ep.load()()
        except Exception as exc:  # noqa: BLE001 — one bad plugin never breaks boot
            logger.warning("Tool plugin %s failed to load: %s", ep.name, exc)
            continue
        if not isinstance(tool, AITool):
            logger.warning("Tool plugin %s is not an AITool", ep.name)
            continue
        if not plugin_allowed(tool.key):
            logger.info(
                "Tool plugin %s discovered but not allowlisted — skipping",
                tool.key,
            )
            continue
        _registry.setdefault(tool.key, tool)


def reset_registry() -> None:
    """Test hook: drop plugin entries (built-ins stay)."""
    global _plugins_loaded
    builtins = {t.key for t in _builtins()}
    for key in list(_registry):
        if key not in builtins:
            del _registry[key]
    _plugins_loaded = False


def register_tool(tool: AITool) -> None:
    """Registration used by tests and by allowlisted plugins at runtime."""
    _registry[tool.key] = tool


def get_tool(key: str) -> AITool:
    _load_plugins()
    tool = _registry.get(key)
    if tool is None:
        raise DomainError(f"Unknown tool: {key}")
    return tool


def list_tools() -> list[dict]:
    """Registry contents for the settings UI / MCP surface (41b)."""
    _load_plugins()
    builtins = {t.key for t in _builtins()}
    return [
        {
            "key": t.key,
            "title": t.title,
            "description": t.description,
            "scope": t.scope.value,
            "audiences": sorted(t.audiences),
            "cost_hint": t.cost_hint,
            "requires_user": t.requires_user,
            "input_schema": t.input_schema,
            "builtin": t.key in builtins,
        }
        for t in _registry.values()
    ]


async def run_tool(
    db: AsyncSession,
    key: str,
    user_id,
    args: Optional[dict] = None,
) -> Any:
    """Validate args and execute a registry tool (the one executor)."""
    tool = get_tool(key)
    try:
        parsed = tool.input_model.model_validate(args or {})
    except ValidationError as exc:
        raise DomainError(f"Invalid input for tool {key}: {exc}") from exc
    if tool.requires_user and user_id is None:
        raise PermissionDeniedError(f"Tool {key} requires a signed-in user")
    return await tool.handler(db, ToolContext(user_id=user_id), parsed)
