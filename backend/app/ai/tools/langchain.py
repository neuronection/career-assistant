"""LangChain tool specs from the registry (ADR-0016, plan 98 Phase 1).

The registry stays the single source of tool truth; this module is the
thin adapter that maps ``AITool`` rows to OpenAI function-format specs
for ``bind_tools``. The main-chat bind set is the chat-audience,
callable tools excluding the surface-owned families (``cv_*`` copilot,
``web_*`` contextual fetch) — capabilities (``kind="capability"``) are
never bindable.
"""

from __future__ import annotations

from typing import Optional

from app.ai.tools.registry import list_tools

#: Tool families owned by other chat surfaces — never bound in main chat.
MAIN_CHAT_EXCLUDED_PREFIXES = ("cv_", "web_")


def main_chat_tool_keys() -> list[str]:
    """Registry keys bindable in the main chat turn."""
    return [
        entry["key"]
        for entry in list_tools()
        if entry.get("kind") == "tool"
        and "chat" in entry.get("audiences", [])
        and not entry["key"].startswith(MAIN_CHAT_EXCLUDED_PREFIXES)
    ]


def tool_spec(key: str) -> Optional[dict]:
    """One registry tool as an OpenAI function-format spec, or None."""
    for entry in list_tools():
        if entry["key"] != key or entry.get("kind") != "tool":
            continue
        return {
            "type": "function",
            "function": {
                "name": entry["key"],
                "description": entry["description"],
                "parameters": entry["input_schema"],
            },
        }
    return None


def chat_tool_specs(keys: Optional[list[str]] = None) -> list[dict]:
    """Bind specs for the given keys (default: the main-chat set)."""
    wanted = keys if keys is not None else main_chat_tool_keys()
    return [spec for key in wanted if (spec := tool_spec(key)) is not None]
