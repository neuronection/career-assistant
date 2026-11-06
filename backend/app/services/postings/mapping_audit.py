"""Closed mapping-audit vocabulary + writer (plan 205 AD6).

The admin audit surface reads ``admin.%`` actions; the vector emitter
rejects non-``vector.*`` actions, so the console's bulk actions are
constructed directly over the identity ``AuditEvent`` model — one row per
action (actor + counts), never one per posting.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity_model import AuditEvent

MAPPING_AUDIT_ACTIONS = {
    "admin.mapping.extract",
    "admin.mapping.redecide",
    "admin.mapping.ignore",
    "admin.mapping.unignore",
    "admin.mapping.unmap",
    "admin.mapping.review",
    "admin.mapping.map",
    "admin.mapping.policy",
    "admin.mapping.alerts",
}


def record_mapping_audit(
    db: AsyncSession,
    *,
    actor: str,
    action: str,
    resource: str,
    outcome: str = "ok",
    fields: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append one mapping audit row in the caller's transaction."""
    if action not in MAPPING_AUDIT_ACTIONS:
        raise ValueError(f"unregistered mapping audit action: {action}")
    resource_text = resource if not fields else f"{resource};{fields}"
    event = AuditEvent(actor=actor, action=action, resource=resource_text, outcome=outcome)
    db.add(event)
    return event


__all__ = ["MAPPING_AUDIT_ACTIONS", "record_mapping_audit"]
