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
