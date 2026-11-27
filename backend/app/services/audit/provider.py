"""Provider audit events (plan 218).

Seed-provider syncs, pending versions and quarantines are admin-visible
actions, so they ride the same bounded ``audit_events`` trail as retrieval
operations. The vocabulary is closed; resources are ids and digests only —
never pack content, URLs with credentials or policy documents.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity_model import AuditEvent

PROVIDER_AUDIT_GROUP = "provider"
PROVIDER_AUDIT_EVENTS = (
    "provider.sync.ok",
    "provider.sync.noop",
    "provider.sync.failed",
    "provider.sync.partial",
    "provider.version.pending",
    "provider.version.rejected",
    "provider.version.approved",
    "provider.version.revoked",
    "provider.apply.ok",
    "provider.apply.conflicted",
    "provider.apply.failed",
    "provider.item.retired",
    "provider.item.published",
    "provider.source.created",
    "provider.source.updated",
    "provider.source.retired",
    "provider.endpoint.probe",
)
RESOURCE_LIMIT = 500


def resource(*parts: str | None, **fields: Any) -> str:
    values = [str(part) for part in parts if part]
    for key, value in fields.items():
        if value is not None:
            values.append(f"{key}={value}")
    return ";".join(values)[:RESOURCE_LIMIT]


def audit_event(
    *,
    actor: str | uuid.UUID,
    action: str,
    resource_ref: str,
    outcome: str = "ok",
    tenant_id: uuid.UUID | None = None,
) -> AuditEvent:
    if action not in PROVIDER_AUDIT_EVENTS:
        raise ValueError(f"unknown provider audit event {action!r}")
    return AuditEvent(
        actor=str(actor),
        action=action,
        resource=resource_ref[:RESOURCE_LIMIT],
        outcome=str(outcome),
        tenant_id=tenant_id,
    )


async def emit(
    db: AsyncSession,
    *,
    actor: str | uuid.UUID,
    action: str,
    resource_ref: str,
    outcome: str = "ok",
    tenant_id: uuid.UUID | None = None,
) -> AuditEvent:
    event = audit_event(
        actor=actor,
        action=action,
        resource_ref=resource_ref,
        outcome=outcome,
        tenant_id=tenant_id,
    )
    db.add(event)
    return event


__all__ = ["PROVIDER_AUDIT_EVENTS", "PROVIDER_AUDIT_GROUP", "audit_event", "emit", "resource"]
