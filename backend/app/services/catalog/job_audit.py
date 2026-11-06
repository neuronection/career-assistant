"""Closed job-audit vocabulary + writer (plan 202 AD9).

The admin audit surface reads ``admin.%`` actions; the vector emitter
rejects non-``vector.*`` actions, so catalog merge events are constructed
directly over the identity ``AuditEvent`` model.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity_model import AuditEvent

JOB_AUDIT_ACTIONS = {"admin.job_type.merge"}


def record_job_audit(
    db: AsyncSession,
    *,
    actor: str,
    action: str,
    resource: str,
    outcome: str = "ok",
) -> AuditEvent:
    """Append one job audit row in the caller's transaction."""
    if action not in JOB_AUDIT_ACTIONS:
        raise ValueError(f"unregistered job audit action: {action}")
    event = AuditEvent(actor=actor, action=action, resource=resource, outcome=outcome)
    db.add(event)
    return event


__all__ = ["JOB_AUDIT_ACTIONS", "record_job_audit"]
