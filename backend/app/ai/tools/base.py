"""Tool registry v2 primitives."""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Type

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


class ToolScope(str, Enum):
    """What a tool may do to user data (MCP exposure is read-scope only)."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ToolContext:
    """Per-invocation context handed to tool handlers."""

    user_id: Optional[uuid.UUID] = None


@dataclass(frozen=True)
class AITool:
    """A registered tool: schema, handler and governance declarations.

    Handlers declare their concrete input-model type; the registry calls
    them with the validated instance, so the stored callable is typed
    loosely on the input position (the schema lives in ``input_model``).
    """

    key: str
    title: str
    description: str
    input_model: Type[BaseModel]
    handler: Callable[[AsyncSession, ToolContext, Any], Awaitable[Any]]
    scope: ToolScope = ToolScope.READ
    audiences: frozenset = field(default_factory=lambda: frozenset({"chat"}))
    cost_hint: str = "cheap"
    requires_user: bool = False

    @property
    def input_schema(self) -> dict:
        """JSON Schema for the tool's arguments (function-calling shape)."""
        return self.input_model.model_json_schema()
