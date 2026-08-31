import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, JSON, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Structured JSON payloads (jobs.attributes, profile sections, AI outputs…).
# JSONB on PostgreSQL, JSON on SQLite (desktop profile) — one Python type.
StructuredJSON = JSONB().with_variant(JSON(), "sqlite")

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with a shared naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """created_at/updated_at columns maintained on write.

    Python-side defaults give sub-second precision on every dialect (SQLite's
    CURRENT_TIMESTAMP is second-granular); server defaults cover raw SQL
    inserts.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """UUID primary key, generated client-side so it works on every dialect."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
