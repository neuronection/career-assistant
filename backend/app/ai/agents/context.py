"""Shared helpers for building AI prompts with deterministic mock support."""

import json
from typing import Any


def context_json(data: Any) -> str:
    """Serialize prompt context and append a machine-readable marker.

    The ``CONTEXT_JSON:`` marker lets the mock provider build deterministic
    outputs from the same data real providers see.
    """
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"{payload}\n\nCONTEXT_JSON: {payload}"


def parse_context(user_prompt: str) -> dict:
    """Extract the CONTEXT_JSON payload from a prompt (mock path only)."""
    marker = "CONTEXT_JSON: "
    idx = user_prompt.rfind(marker)
    if idx == -1:
        return {}
    try:
        return json.loads(user_prompt[idx + len(marker) :])
    except json.JSONDecodeError:
        return {}
