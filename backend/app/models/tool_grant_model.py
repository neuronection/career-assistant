"""Per-user tool grants (plan 32 follow-up — the D20 runtime funnel).

The ``state-changing`` risk class rides per-grant enablement (ADR-0011
classes / charter ``riskClasses`` law): a state-changing registry tool
executes only while the user has an explicit grant row for it — the
toggle lives in the tools catalog (settings/consent surface) and the
absence of a row is the default-off posture. ``destructive`` tools are
NEVER grantable (the grant path rejects them) — they confirm every call
through the HITL funnel regardless of any row; ``read-only`` tools need
no grant. Grants are user-scoped data, never model-writable: only the
REST surface creates and removes them.
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserToolGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One enabled state-changing tool for one user (the catalog toggle)."""

    __tablename__ = "user_tool_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "tool_key", name="uq_user_tool_grants"),
        CheckConstraint("tool_key <> ''", name="tool_key_nonempty"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tool_key: Mapped[str] = mapped_column(String(200), nullable=False)
