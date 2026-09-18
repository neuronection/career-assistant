"""Checkpointer lifecycle: the app lifespan owns first-run
setup. LangGraph's initial migration issues CREATE INDEX CONCURRENTLY,
which waits on every pre-existing transaction snapshot — run lazily
mid-flight (inside a handler whose session holds a snapshot) it
self-deadlocks the worker, so the warm-up must happen at
startup, before any worker or request. Boot survives a failed warm-up
(graph flows degrade, everything else keeps working)."""

import pytest


@pytest.fixture
def warm_spy(monkeypatch):
    import app.ai.checkpointer as checkpointer_module

    calls: list[str] = []

    async def fake_get_checkpointer():
        calls.append("warm")

    monkeypatch.setattr(checkpointer_module, "get_checkpointer", fake_get_checkpointer)
    return calls


def _lifespan_app():
    from app.main import create_app

    return create_app()


async def test_lifespan_warms_checkpointer_before_serving(warm_spy):
    app = _lifespan_app()
    async with app.router.lifespan_context(app):
        pass
    assert warm_spy == ["warm"], "checkpointer must be set up once at startup"


async def test_lifespan_survives_checkpointer_failure(monkeypatch, warm_spy):
    import app.ai.checkpointer as checkpointer_module

    async def broken_checkpointer():
        warm_spy.append("attempted")
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(checkpointer_module, "get_checkpointer", broken_checkpointer)
    app = _lifespan_app()
    async with app.router.lifespan_context(app):
        pass
    assert warm_spy == ["attempted"], "warm-up failure must not block boot"


async def test_postgres_checkpointer_uses_a_connection_pool(db, auth_headers):
    """Cancellation-safety for the SSE turn lifecycle (the
    "another command is already in progress" e2e flake): the Postgres
    saver draws pooled connections instead of one process-lifetime
    AsyncConnection that a cancelled checkpoint op can poison."""
    import asyncio
    import contextlib

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    from app.ai.checkpointer import aclose_checkpointer, get_checkpointer
    from app.core.config import settings

    if settings.DATABASE_URL.startswith("sqlite"):
        pytest.skip("pool shape is Postgres-only")
    await aclose_checkpointer()
    try:
        saver = await get_checkpointer()
        assert isinstance(saver, AsyncPostgresSaver)
        assert isinstance(saver.conn, AsyncConnectionPool)
        config = {"configurable": {"thread_id": "pool-round-trip"}}

        # Round trip: an empty thread queries, cancels mid-command, and
        # the very next op must succeed (the pool checks out a fresh,
        # validated connection instead of the poisoned socket).
        assert await saver.aget_tuple(config) is None
        async_gen = saver.alist(config, limit=1).__aiter__()
        task = asyncio.create_task(async_gen.__anext__())
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        with contextlib.suppress(StopAsyncIteration):
            await async_gen.aclose()
        rows = [entry async for entry in saver.alist(config, limit=10)]
        assert rows == []
    finally:
        await aclose_checkpointer()
