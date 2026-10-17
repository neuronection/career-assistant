"""Tool registry: data, not code.

Built-ins auto-register at import; plugins arrive via the
``career_assistant.tools`` entry-point group and are **admin-opt-in**
through the ``TOOL_PLUGINS_ALLOWLIST`` setting (they run in-process,
exactly like connector plugins).
"""

from __future__ import annotations

import logging
from importlib import metadata
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools.base import AITool, ToolContext, ToolRiskClass, ToolScope
from app.core.errors import DomainError, PermissionDeniedError, ValidationError

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "career_assistant.tools"


def _validate_tool(tool: AITool) -> None:
    """The registration-time D20 gate: the risk class is closed-vocabulary
    data that must cohere with the tool's scope (ADR-0011 classes /
    charter ``riskClasses``). Capability entries stay non-executable in
    every funnel — ``run_tool`` rejects them (ADR-0015 item 5)."""
    if not isinstance(tool.risk_class, ToolRiskClass) and tool.risk_class is not None:
        raise ValidationError(f"Tool {tool.key} carries an unknown risk class")
    if tool.kind == "tool":
        risk = tool.effective_risk_class
        if tool.risk_class is ToolRiskClass.READ_ONLY and tool.scope is not ToolScope.READ:
            raise ValidationError(f"Tool {tool.key}: a read-only class requires read scope")
        if (
            tool.risk_class in (ToolRiskClass.STATE_CHANGING, ToolRiskClass.DESTRUCTIVE)
            and tool.scope is not ToolScope.WRITE
        ):
            raise ValidationError(f"Tool {tool.key}: a {risk.value} class requires write scope")


def _builtins() -> list[AITool]:
    from app.ai.tools.builtin import BUILTIN_TOOLS
    from app.ai.tools.capabilities import BUILTIN_CAPABILITIES
    from app.ai.tools.cv_builder import CV_BUILDER_TOOLS
    from app.ai.tools.cv_synth import CV_SYNTH_TOOLS
    from app.ai.tools.web import WEB_TOOLS

    return [
        *BUILTIN_TOOLS,
        *CV_BUILDER_TOOLS,
        *CV_SYNTH_TOOLS,
        *WEB_TOOLS,
        *BUILTIN_CAPABILITIES,
    ]


_registry: dict[str, AITool] = {}
_plugins_loaded = False


def _ensure_builtins() -> None:
    if not _registry:
        for tool in _builtins():
            _validate_tool(tool)
            _registry[tool.key] = tool


def _extension_chat_tools() -> list[AITool]:
    """Extension-contributed chat tools (D20): a bundled connector whose
    manifest declares ``chat-tools`` contributes its tools with the
    MANIFEST's risk class — the manifest is the law; a code-side
    declaration that disagrees with it (or with the declared list) is a
    registration-time throw, never a silent drift."""
    from app.extensions.registry import iter_connectors
    from app.extensions.sdk import ChatToolContribution

    tools: list[AITool] = []
    for connector in iter_connectors():
        manifest = connector.manifest()
        if "chat-tools" not in (manifest.get("capabilities") or []):
            continue
        declared = {entry["id"]: entry for entry in manifest.get("tools") or []}
        contributions = connector.chat_tools()
        if not contributions:
            raise ValidationError(
                f"Connector {manifest.get('id')} declares chat-tools without implementations"
            )
        for contribution in contributions:
            if not isinstance(contribution, ChatToolContribution):
                raise ValidationError(
                    f"Connector {manifest.get('id')}: chat tool contributions must be "
                    "ChatToolContribution"
                )
            entry = declared.get(contribution.id)
            if entry is None:
                raise ValidationError(
                    f"Connector {manifest.get('id')}: chat tool "
                    f"{contribution.id!r} is not declared in the manifest"
                )
            if entry.get("riskClass") != contribution.risk_class:
                raise ValidationError(
                    f"Connector {manifest.get('id')}: chat tool {contribution.id!r} "
                    f"declares {entry.get('riskClass')!r} in the manifest but "
                    f"{contribution.risk_class!r} in code — the manifest is the law"
                )
            declared.pop(contribution.id)
            tools.append(contribution.as_tool(f"{manifest['id']}:{contribution.id}"))
        if declared:
            raise ValidationError(
                f"Connector {manifest.get('id')}: manifest declares chat tools "
                f"with no implementation: {sorted(declared)}"
            )
    return tools


def plugin_allowed(key: str) -> bool:
    from app.core.config import settings

    allowlist = getattr(settings, "tool_plugins_allowlist", None) or []
    return key in allowlist


def _load_plugins() -> None:
    """Entry-point discovery — plugin keys are opt-in via the allowlist.

    Extension-contributed chat tools (D20) ride the same once-per-load
    lifecycle: the connector manifests are the law, re-derived whenever
    the registry rebuilds."""
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    _ensure_builtins()
    for tool in _extension_chat_tools():
        _validate_tool(tool)
        _registry.setdefault(tool.key, tool)
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        return
    for ep in eps:
        try:
            tool = ep.load()()
        except Exception as exc:
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
        _validate_tool(tool)
        _registry.setdefault(tool.key, tool)


def reset_registry() -> None:
    """Test hook: drop plugin entries (built-ins stay)."""
    global _plugins_loaded
    builtins = {t.key for t in _builtins()} | {t.key for t in _extension_chat_tools()}
    for key in list(_registry):
        if key not in builtins:
            del _registry[key]
    _plugins_loaded = False


def register_tool(tool: AITool) -> None:
    """Registration used by tests and by allowlisted plugins at runtime.

    The D20 gate runs for EVERY registration (see :func:`_validate_tool`)."""
    _validate_tool(tool)
    _registry[tool.key] = tool


def get_tool(key: str) -> AITool:
    _load_plugins()
    tool = _registry.get(key)
    if tool is None and "__" in key:
        # Bind-safe alias (OpenAI function names take no colons): the
        # charter-namespaced extension key `<extensionId>:<id>` binds as
        # `<extensionId>__<id>` — kebab-case ids make the round-trip
        # bijective (extension ids and tool ids cannot contain `_`).
        tool = _registry.get(key.replace("__", ":", 1))
    if tool is None:
        raise DomainError(f"Unknown tool: {key}")
    return tool


logger = logging.getLogger(__name__)


def _coerce_tool_args(input_model: type[BaseModel], args: dict, key: str) -> Any:
    """Validate tool args, clamping over-long model-provided strings once.

    LLM tool calls routinely stuff prose (the user's whole message) into
    string args; a `string_too_long` error then turned into `flow_failed`
    with the turn rejected. Services already degrade prose queries via
    per-word fallbacks, so truncating to the field's max_length is safe;
    anything else (or still-invalid args) stays a hard DomainError.
    """
    from pydantic import ValidationError

    try:
        return input_model.model_validate(args)
    except ValidationError:
        clamped = False
        cleaned = dict(args)
        field_max: dict[str, int] = {}
        for name, field in input_model.model_fields.items():
            for length in field.metadata or []:
                if getattr(length, "max_length", None):
                    field_max[name] = length.max_length
        for name, value in cleaned.items():
            max_len = field_max.get(name)
            if isinstance(value, str) and max_len and len(value) > max_len:
                cleaned[name] = value[:max_len]
                clamped = True
            elif isinstance(value, list) and name in field_max and len(value) > field_max[name]:
                cleaned[name] = value[: field_max[name]]
                clamped = True
        if not clamped:
            raise DomainError(f"Invalid input for tool {key}") from None
        try:
            return input_model.model_validate(cleaned)
        except ValidationError as retry:
            logger.warning("tool args still invalid after clamp: %s (%s)", key, retry)
            raise DomainError(f"Invalid input for tool {key}: {retry}") from retry


def list_tools() -> list[dict]:
    """Registry contents for the settings UI / MCP surface (41b).

    Includes non-callable ``kind="capability"`` entries (ADR-0015);
    executors and exposure surfaces must filter to ``kind == "tool"``.
    Every row carries its resolved ADR-0011 risk class (D20) — the chat
    tool metadata the catalog/consent surface renders."""
    _load_plugins()
    builtins = {t.key for t in _builtins()}
    return [
        {
            "key": t.key,
            "title": t.title,
            "description": t.description,
            "scope": t.scope.value,
            "risk_class": t.effective_risk_class.value,
            "audiences": sorted(t.audiences),
            "cost_hint": t.cost_hint,
            "requires_user": t.requires_user,
            "input_schema": t.input_schema,
            "builtin": t.key in builtins,
            "kind": t.kind,
            "hitl": t.hitl,
        }
        for t in _registry.values()
    ]


async def run_tool(
    db: AsyncSession,
    key: str,
    user_id,
    args: dict | None = None,
    *,
    chat_session_id=None,
) -> Any:
    """Validate args and execute a registry tool (the one executor).

    This is the D20 invocation-time funnel: ``read-only`` runs as before;
    ``state-changing`` requires the user's catalog grant;
    ``destructive`` tools CANNOT execute here — the call becomes an
    ADR-0015 Class-B confirmation card (kind ``tool_execution``) and
    runs only through that card's idempotent resolve (never by calling
    this function again, whatever the model does with the result)."""
    tool = get_tool(key)
    if tool.kind != "tool":
        raise DomainError(f"Not a callable tool: {key}")
    parsed = _coerce_tool_args(tool.input_model, args or {}, key)
    if tool.requires_user and user_id is None:
        raise PermissionDeniedError(f"Tool {key} requires a signed-in user")
    risk = tool.effective_risk_class
    if risk is ToolRiskClass.STATE_CHANGING:
        from app.ai.tools.grants import has_grant

        if user_id is None or not await has_grant(db, user_id, tool.key):
            raise DomainError(
                f"Tool {tool.key} is state-changing and not enabled by this user — "
                "it stays inert until enabled in the tools catalog"
            )
    if risk is ToolRiskClass.DESTRUCTIVE:
        from app.ai.tools.confirm import emit_tool_confirmation

        if user_id is None:
            raise PermissionDeniedError(
                f"Tool {tool.key} is destructive and requires a signed-in user to confirm"
            )
        return await emit_tool_confirmation(
            db,
            tool=tool,
            user_id=user_id,
            args=parsed,
            chat_session_id=chat_session_id,
        )
    handler = tool.handler
    assert handler is not None, "callable tools always carry a handler"
    return await handler(db, ToolContext(user_id=user_id), parsed)
