from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page[T](BaseModel):
    """Simple pagination envelope."""

    items: list[T]
    total: int
    page: int
    page_size: int


class CursorPage[T](BaseModel):
    """Keyset page: a window of items plus the opaque next-page cursor.

    `total` is the whole queue's size and is answered on the first page only
    (a count per appended page would be paid for nothing)."""

    items: list[T]
    next_cursor: str | None = None
    total: int | None = None


class Message(BaseModel):
    """Simple message response."""

    message: str


class ErrorResponse(BaseModel):
    """Error body."""

    detail: str


def or_empty(value: dict | None) -> dict:
    """Coerce None dicts to empty for JSONB defaults."""
    return value or {}
