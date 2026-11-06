"""Opaque keyset cursors for admin queue listings (plan 206).

A cursor carries the order keys of the last row a client received. Services
compare the queue's `(timestamp, id)` order against it; the wire never sees
the keys, so a projection can change without breaking links. The decoder is
strict: a malformed or hand-edited token is a 400, never a silently empty
page.
"""

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.errors import ValidationError

_MAX_TOKEN = 400


def _pack(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"dt": value.isoformat()}
    if isinstance(value, UUID):
        return {"uuid": str(value)}
    if isinstance(value, (str, int, float)):
        return value
    raise TypeError(f"unsupported cursor value: {type(value).__name__}")


def _unpack(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"dt"}:
            return datetime.fromisoformat(str(value["dt"]))
        if set(value) == {"uuid"}:
            return UUID(str(value["uuid"]))
        raise ValueError("unknown cursor value shape")
    if isinstance(value, (str, int, float)):
        return value
    raise ValueError("unknown cursor value shape")


def encode_cursor(values: tuple[Any, ...]) -> str:
    """Encode the last row's order keys as an opaque URL-safe token."""
    payload = json.dumps([_pack(value) for value in values], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(token: str, *, types: tuple[type, ...]) -> tuple[Any, ...]:
    """Decode a cursor token written by :func:`encode_cursor`.

    `types` pins the queue's order-key shape: a token with the wrong arity or
    a hand-edited value type is a 400, never a query error.
    """
    if len(token) > _MAX_TOKEN:
        raise ValidationError("Invalid cursor")
    try:
        raw = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError("Invalid cursor") from exc
    if not isinstance(raw, list) or len(raw) != len(types):
        raise ValidationError("Invalid cursor")
    try:
        values = tuple(_unpack(value) for value in raw)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Invalid cursor") from exc
    values = tuple(
        value.replace(tzinfo=UTC) if isinstance(value, datetime) and value.tzinfo is None else value
        for value in values
    )
    for value, expected in zip(values, types, strict=True):
        if not isinstance(value, expected):
            raise ValidationError("Invalid cursor")
    return values
