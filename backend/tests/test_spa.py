"""SPA serving behavior: dist mount, index fallback, API 404 semantics."""

from pathlib import Path
import sys

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
import app.main as main_module
from app.main import _find_spa_dist, create_app


@pytest.fixture
def spa_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body><div id=root></div></body></html>"
    )
    (dist / "assets" / "app.js").write_text("console.log('app');")
    return dist


@pytest.fixture
def no_local_dist(monkeypatch):
    """Neutralize repo/frozen dist detection so tests are deterministic."""
    monkeypatch.setattr(settings, "SPA_DIST", "")
    monkeypatch.setattr(sys, "_MEIPASS", None, raising=False)
    yield


def _make_app(monkeypatch, dist: Path | None):
    monkeypatch.setattr(main_module, "_find_spa_dist", lambda: dist)
    return create_app()


async def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def test_find_spa_dist_honors_explicit_setting(spa_dist, monkeypatch):
    monkeypatch.setattr(settings, "SPA_DIST", str(spa_dist))
    assert _find_spa_dist() == spa_dist


def test_find_spa_dist_ignores_dir_without_index(tmp_path: Path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(settings, "SPA_DIST", str(empty))
    found = _find_spa_dist()
    assert found is None or found != empty


async def test_spa_dist_serves_index(spa_dist, monkeypatch):
    app = _make_app(monkeypatch, spa_dist)
    async with await _client(app) as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<div id=root>" in response.text


async def test_unknown_spa_route_falls_back_to_index(spa_dist, monkeypatch):
    app = _make_app(monkeypatch, spa_dist)
    async with await _client(app) as client:
        response = await client.get("/settings/ai")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


async def test_missing_asset_returns_real_404(spa_dist, monkeypatch):
    app = _make_app(monkeypatch, spa_dist)
    async with await _client(app) as client:
        response = await client.get("/assets/missing-chunk.js")
        assert response.status_code == 404


async def test_existing_static_asset_is_served(spa_dist, monkeypatch):
    app = _make_app(monkeypatch, spa_dist)
    async with await _client(app) as client:
        response = await client.get("/assets/app.js")
        assert response.status_code == 200
        assert "console.log" in response.text


async def test_unmatched_api_path_returns_json_404_not_html(spa_dist, monkeypatch):
    app = _make_app(monkeypatch, spa_dist)
    async with await _client(app) as client:
        response = await client.get("/api/v1/does-not-exist")
        assert response.status_code == 404
        assert "application/json" in response.headers["content-type"]
        assert response.json() == {"detail": "Not Found"}


async def test_health_still_works_alongside_spa(spa_dist, monkeypatch):
    app = _make_app(monkeypatch, spa_dist)
    async with await _client(app) as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


async def test_without_dist_api_only_mode(no_local_dist, monkeypatch):
    app = _make_app(monkeypatch, None)
    async with await _client(app) as client:
        response = await client.get("/")
        assert response.status_code == 404
        assert "application/json" in response.headers["content-type"]
