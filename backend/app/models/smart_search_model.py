"""Smart search cache (plan 179): one row per NORMALIZED free-text
query, shared across users — the text→filter mapping has no personal
inputs, so a repeat query (from anyone) costs zero AI. Rows are cache
data: TTL-pruned daily by the smart-digest job (7 days), rebuildable by
definition, never a record.
"""

from datetime import UTC, datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StructuredJSON, TZDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SmartQueryCache(Base):
    """The cross-user NL-query → spec cache (plan 179).

    Primary key is the sha256 of the normalized query (casefold +
    whitespace collapse), so cross-user keys are stable; ``spec`` is the
    closed ``SmartSearchSpec`` projection the resolver runs on read.
    """

    __tablename__ = "smart_query_cache"

    query_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    spec: Mapped[dict] = mapped_column(StructuredJSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=_utcnow)
