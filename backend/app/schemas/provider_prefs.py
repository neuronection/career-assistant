"""Provider subscription and source-preference shapes (plan 218 §3.12)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SubscriptionMode = Literal["all", "selected"]


class ProviderSubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    mode: SubscriptionMode = "all"
    collections: list[str] = Field(default_factory=list, max_length=50)
    filters: dict[str, Any] = Field(default_factory=dict)


class ProviderSubscriptionOut(BaseModel):
    id: str
    provider_id: str
    enabled: bool
    mode: SubscriptionMode
    collections: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)


class SourcePrefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hidden: bool = True
    priority: int = Field(default=100, ge=0, le=999)
    filters: dict[str, Any] = Field(default_factory=dict)


class SourcePrefOut(BaseModel):
    id: str
    source_id: str
    hidden: bool
    priority: int
    filters: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ProviderSubscriptionIn",
    "ProviderSubscriptionOut",
    "SourcePrefIn",
    "SourcePrefOut",
]
