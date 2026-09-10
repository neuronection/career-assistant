import json
import logging
from datetime import date, datetime
from typing import AsyncGenerator
from uuid import UUID

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


class CustomJSONEncoder(json.JSONEncoder):
    """JSON encoder that understands UUIDs and datetimes."""

    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


def json_serializer(obj) -> str:
    """Serialize JSONB values with UUID/datetime support."""
    return json.dumps(obj, cls=CustomJSONEncoder)


_engine_kwargs: dict = {
    "pool_size": 10,
    "max_overflow": 10,
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "echo": False,
    "json_serializer": json_serializer,
}
if settings.DATABASE_URL.startswith("sqlite"):
    # SQLite has no pool sizing; the timeout rides out writer contention
    # between request handlers and background-job workers.
    _engine_kwargs = {
        "pool_pre_ping": True,
        "connect_args": {"timeout": 30},
        "echo": False,
        "json_serializer": json_serializer,
    }

engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)


def sqlite_pragmas(dbapi_connection, _record=None):
    """FK cascades + durability pragmas (SQLite ignores them by default).

    Shared with the test engine: switching a fresh file into WAL needs
    exclusive access, so every engine touching the database must run
    this on connect or the later switch races an open peer connection.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


if settings.DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    event.listens_for(engine.sync_engine, "connect")(sqlite_pragmas)


AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
