import uuid
from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import JSON, DateTime, MetaData, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

# Structured JSON payloads (jobs.attributes, profile sections, AI outputs…).
# JSONB on PostgreSQL, JSON on SQLite (desktop profile) — one Python type.
StructuredJSON = JSONB().with_variant(JSON(), "sqlite")


class GuidType(TypeDecorator):
    """UUID that tolerates string values on bind.

    PostgreSQL's native UUID casts strings implicitly; on SQLite the
    ``Uuid`` bind processor requires ``uuid.UUID`` instances, so a str id
    from a JSON payload or path param would raise ``'str' object has no
    attribute 'hex'`` (desktop profile). DDL is identical to ``Uuid`` on
    every dialect.
    """

    impl = Uuid
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value

    def coerce_compared_value(self, op, value):
        return self


class TZDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every dialect.

    PostgreSQL timestamptz round-trips aware datetimes, SQLite DATETIME
    returns naive ones (desktop profile). Values are normalized to UTC on
    write and re-attached on read so `datetime` comparisons never mix
    offset-naive and offset-aware objects.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


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
    type_annotation_map: ClassVar[dict[type, type]] = {uuid.UUID: GuidType}


class TimestampMixin:
    """created_at/updated_at columns maintained on write.

    Python-side defaults give sub-second precision on every dialect (SQLite's
    CURRENT_TIMESTAMP is second-granular); server defaults cover raw SQL
    inserts.
    """

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """UUID primary key, generated client-side so it works on every dialect."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
