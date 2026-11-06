"""The app-side ``audit_events`` emitter for retrieval operations (plan 51 Q1b).

Until this slice the only writer was the identity kit's sink; ``admin.%``
had a read filter with no writers. Retrieval actions are the first
product-side audit producers. The vocabulary is the vendored family
contract's ``vector.*`` group — no free-form action strings.

**Failure policy.** The emitter never commits on its own, so an action that
owns its transaction writes the audit row and the mutation in one commit: an
audit insert failure aborts the action instead of leaving an unaudited
mutation. The four lifecycle actions (build/activate/retire/drop) mutate
through :class:`~app.services.vector_space_lifecycle.VectorSpaceLifecycleService`,
which commits on its own sync session. Their audit row is written with the
action-run result immediately after that commit; if that write fails, the
request fails loudly (HTTP 500), the failure is logged, and the run stays
running until the stale reaper settles it. The already-committed mutation is
never hidden behind a swallowed exception.

Resources are short, structured references (``space:<id>``,
``run:<id>``, ``space:<id>;action=vacuum``); no document, query or prompt
text ever reaches an audit row.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity_model import AuditEvent
from app.storage.retrieval_ops import VECTOR_AUDIT_EVENTS, VECTOR_AUDIT_GROUP

RESOURCE_LIMIT = 500


def resource(*parts: str | None, **fields: Any) -> str:
    """Build a bounded structured resource reference (ids and keys only)."""
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
    """Build (but do not commit) one ``vector.*`` audit row."""
    if action not in VECTOR_AUDIT_EVENTS:
        raise ValueError(f"unknown retrieval audit event {action!r}")
    if not action.startswith(f"{VECTOR_AUDIT_GROUP}."):
        raise ValueError(f"retrieval audit event must be in the {VECTOR_AUDIT_GROUP} group")
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
    """Add the audit row to the caller's transaction (no commit)."""
    event = audit_event(
        actor=actor,
        action=action,
        resource_ref=resource_ref,
        outcome=outcome,
        tenant_id=tenant_id,
    )
    db.add(event)
    return event


__all__ = ["RESOURCE_LIMIT", "audit_event", "emit", "resource"]
