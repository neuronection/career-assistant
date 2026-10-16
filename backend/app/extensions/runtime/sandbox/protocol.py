"""The capability-RPC host seam — framing + the structural message gate
(plan 32 Phase 5 / capability-rpc.md).

The authoritative structural law is the vendored schema
(``contracts/capability-rpc.schema.json``): every line the host accepts
from or sends to a sandbox validates against it through the vendored
validator (:mod:`app.extensions.contract`) — the same fixtures that gate
every other host (the rpc section of ``extension-contract.fixtures.json``
runs through exactly this gate). Framing adds the charter's line cap
(``limits.rpcLineMaxBytes``) and the closed vocabularies (methods, error
enum, retryable sub-enum) as typed Python errors.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.extensions import contract
from app.extensions.polite_http import DEFAULT_RETRYABLE, ERROR_CODES, ERROR_DETAIL_MAX_CHARS

__all__ = [
    "CAP_METHODS",
    "EVENT_METHODS",
    "FRAMING_MAX_LINE_BYTES",
    "HOST_METHODS",
    "PROTOCOL",
    "RPC_LINE_MAX_BYTES",
    "FramingError",
    "encode_line",
    "error_envelope",
    "validate_document",
    "validate_message",
]

PROTOCOL = "capability-rpc/1"
VERSION = 1

CAP_METHODS = frozenset(
    {"cap.net.fetch", "cap.state.get", "cap.state.set", "cap.items.emit", "cap.secrets.need"}
)
HOST_METHODS = frozenset({"ext.invoke", "ext.dispose"})
EVENT_METHODS = frozenset({"evt.progress", "evt.log"})

RPC_LINE_MAX_BYTES = 1_048_576
# The newline plus a small safety margin around the charter line cap.
FRAMING_MAX_LINE_BYTES = RPC_LINE_MAX_BYTES + 2

_SCHEMA_CACHE: dict[str, Any] | None = None


def rpc_schema() -> dict[str, Any]:
    """The vendored message schema (repo-root contracts/, frozen-bundle
    path when packaged) — loaded once, fail-closed."""
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        from app.extensions.lifecycle import _contracts_dir

        path = Path(_contracts_dir()) / "capability-rpc.schema.json"
        try:
            _SCHEMA_CACHE = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"capability-rpc schema unavailable at {path}: {exc} — "
                "the sandbox seam fails closed (vendored contract set incomplete)"
            ) from exc
    return _SCHEMA_CACHE


class FramingError(Exception):
    """One protocol-violating line — the call it belongs to fails with
    ``protocol``; the peer is recycled after repeated violations."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail[:ERROR_DETAIL_MAX_CHARS]


def validate_message(line: bytes | str) -> dict[str, Any]:
    """Decode + structurally validate one framed line against the vendored
    schema. Raises :class:`FramingError` on any violation."""
    if isinstance(line, bytes):
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FramingError("invalid UTF-8 in message line") from exc
    else:
        text = line
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FramingError("line is not valid JSON") from exc
    if not isinstance(doc, dict):
        raise FramingError("message is not a JSON object")
    validate_document(doc)
    return doc


def validate_document(doc: Any) -> None:
    """Structural gate for one parsed message against the vendored
    schema. Raises :class:`FramingError` on any violation."""
    if not isinstance(doc, dict):
        raise FramingError("message is not a JSON object")
    err = contract.validate(rpc_schema(), doc, rpc_schema())
    if err is not None:
        raise FramingError(f"message fails the capability-rpc schema: {err}")


def encode_line(message: dict[str, Any]) -> bytes:
    """One framed outbound line; oversized lines are a host-side framing
    bug — refused here, never sent."""
    line = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(line) > RPC_LINE_MAX_BYTES:
        raise FramingError("outbound message exceeds rpcLineMaxBytes")
    return line + b"\n"


def error_envelope(
    code: str,
    detail: str,
    *,
    retryable: str | None = None,
    retry_after_ms: int | None = None,
) -> dict[str, Any]:
    """The charter error envelope (protocol §8) — one vocabulary across
    the seam, the result envelopes and every product surface."""
    if code not in ERROR_CODES:
        raise ValueError(f"unknown charter error code: {code!r}")
    envelope: dict[str, Any] = {
        "code": code,
        "detail": detail[:ERROR_DETAIL_MAX_CHARS],
        "retryable": retryable or DEFAULT_RETRYABLE[code],
    }
    if retry_after_ms is not None:
        envelope["retryAfterMs"] = max(0, int(retry_after_ms))
    return envelope
