"""LangChain tool specs from the registry (ADR-0016, plan 98 Phase 1).

The registry stays the single source of tool truth; this module is the
thin adapter that maps ``AITool`` rows to OpenAI function-format specs
for ``bind_tools``. The main-chat bind set is the chat-audience,
callable tools excluding the surface-owned families (``cv_*`` copilot,
``web_*`` contextual fetch) — capabilities (``kind="capability"``) are
never bindable. Within the excluded families, a narrow allowlist of
READ-look / styling ops still binds: attached-CV inspection and restyle
(read state, visual review, theme/design/template) — the same audited
op path the builder copilot uses, without handing the chat the section
content editors.
"""

from __future__ import annotations

from typing import Optional

from app.ai.tools.registry import list_tools

#: Tool families owned by other chat surfaces — never bound in main chat.
MAIN_CHAT_EXCLUDED_PREFIXES = ("web_",)

#: cv_* tools the main chat may bind: inspect a CV's state, review how
#: it looks, restyle it (theme/curated tokens/template switch), and
#: control its context selection (the allowlist — the non-destructive
#: improvement path). Variant TEXT generation is NOT bound: cv_* chat
#: asks go through the HITL `cv_synth` card (one review surface); the
#: `cv_synth_generate` tool stays Studio-copilot-only.
MAIN_CHAT_CV_TOOLS = frozenset(
    {
        "cv_read_state",
        "cv_review_visual",
        "cv_set_template",
        "cv_apply_theme",
        "cv_update_design",
        "cv_set_context",
    }
)


def _main_chat_bindable(key: str) -> bool:
    """web_* is never bound; cv_* only through the explicit allowlist."""
    if any(key.startswith(prefix) for prefix in MAIN_CHAT_EXCLUDED_PREFIXES):
        return False
    if key.startswith("cv_"):
        return key in MAIN_CHAT_CV_TOOLS
    return True


def main_chat_tool_keys() -> list[str]:
    """Registry keys bindable in the main chat turn."""
    return [
        entry["key"]
        for entry in list_tools()
        if entry.get("kind") == "tool"
        and "chat" in entry.get("audiences", [])
        and _main_chat_bindable(entry["key"])
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
