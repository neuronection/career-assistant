"""Tool registry v2 — one definition, every surface.

Tools are first-class registered objects: pydantic input schema (rendered
to JSON Schema for function calling), async handler, declared scope
(``read`` | ``write``), audience (chat / autopilot / interview / mcp),
cost hint, and per-user requirements. Built-ins auto-register; plugins
arrive via the ``career_assistant.tools`` entry-point group and are
admin-opt-in through ``TOOL_PLUGINS_ALLOWLIST`` (same pattern as
connectors). The chatbot consumes the registry today; autopilot and the
MCP layer (41b) consume the same definitions.
"""

from enum import Enum

from app.ai.tools.base import AITool, ToolContext, ToolScope
from app.ai.tools.registry import (
    get_tool,
    list_tools,
    register_tool,
    reset_registry,
    run_tool,
)

__all__ = [
    "AITool",
    "ToolContext",
    "ToolScope",
    "get_tool",
    "list_tools",
    "register_tool",
    "reset_registry",
    "run_tool",
    "ToolAudience",
]


class ToolAudience(str, Enum):
    """Surfaces that may invoke a tool."""

    CHAT = "chat"
    AUTOPILOT = "autopilot"
    INTERVIEW = "interview"
    CV_BUILDER = "cv_builder"
    MCP = "mcp"
