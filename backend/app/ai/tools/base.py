"""Tool registry v2 primitives."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


class ToolScope(StrEnum):
    """What a tool may do to user data (MCP exposure is read-scope only)."""

    READ = "read"
    WRITE = "write"


class ToolRiskClass(StrEnum):
    """The ADR-0011 risk classes (charter ``riskClasses`` vocabulary,
    D20): every chat tool carries exactly one. ``read-only`` auto-runs;
    ``state-changing`` rides per-grant enablement (the tools catalog
    toggle, :mod:`app.ai.tools.grants`); ``destructive`` confirms every
    call through the HITL funnel (:mod:`app.ai.tools.confirm`) and is
    never grant-bypassable. The closed vocabulary is pinned against the
    vendored charter by the extensions contract wall."""

    READ_ONLY = "read-only"
    STATE_CHANGING = "state-changing"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolContext:
    """Per-invocation context handed to tool handlers."""

    user_id: uuid.UUID | None = None


@dataclass(frozen=True)
class AITool:
    """A registered tool: schema, handler and governance declarations.

    Handlers declare their concrete input-model type; the registry calls
    them with the validated instance, so the stored callable is typed
    loosely on the input position (the schema lives in ``input_model``).

    ``kind="capability"`` entries are non-callable catalog rows (ADR-0015):
    they document HITL proposal capabilities in the tools surface but can
    never execute — ``run_tool`` rejects them and MCP/admin tool surfaces
    expose callable tools only.
    """

    key: str
    title: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[AsyncSession, ToolContext, Any], Awaitable[Any]] | None
    scope: ToolScope = ToolScope.READ
    # The declared ADR-0011 class (D20). ``None`` derives from scope at
    # registration (read ⇒ read-only, write ⇒ state-changing) so legacy
    # declarations keep their honest class without churning every row;
    # an EXPLICIT class must cohere with scope, and only an explicit
    # declaration can ever be ``destructive``.
    risk_class: ToolRiskClass | None = None
    audiences: frozenset = field(default_factory=lambda: frozenset({"chat"}))
    cost_hint: str = "cheap"
    requires_user: bool = False
    kind: str = "tool"
    hitl: bool = False

    @property
    def input_schema(self) -> dict:
        """JSON Schema for the tool's arguments (function-calling shape)."""
        return self.input_model.model_json_schema()

    @property
    def effective_risk_class(self) -> ToolRiskClass:
        """The registered class: explicit, or the scope-derived default."""
        if self.risk_class is not None:
            return self.risk_class
        if self.scope is ToolScope.READ:
            return ToolRiskClass.READ_ONLY
        return ToolRiskClass.STATE_CHANGING
