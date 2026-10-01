from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page[T](BaseModel):
    """Simple pagination envelope."""

    items: list[T]
    total: int
    page: int
    page_size: int


class Message(BaseModel):
    """Simple message response."""

    message: str


class ErrorResponse(BaseModel):
    """Error body."""

    detail: str


def or_empty(value: dict | None) -> dict:
    """Coerce None dicts to empty for JSONB defaults."""
    return value or {}
