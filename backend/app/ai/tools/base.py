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
    audiences: frozenset = field(default_factory=lambda: frozenset({"chat"}))
    cost_hint: str = "cheap"
    requires_user: bool = False
    kind: str = "tool"
    hitl: bool = False

    @property
    def input_schema(self) -> dict:
        """JSON Schema for the tool's arguments (function-calling shape)."""
        return self.input_model.model_json_schema()
