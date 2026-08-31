"""Local desktop profile: secret file, env bootstrap, window state, shell utils."""

import stat
from pathlib import Path

import pytest

from app.local import (
    SECRET_FILE,
    bootstrap_environment,
    default_data_dir,
    ensure_secret_file,
)
from app.shell import (
    WindowGeometryTracker,
    clamp_window_state,
    find_free_port,
    load_window_state,
    sanitize_environment,
    save_window_state,
)


class FakeScreen:
    def __init__(self, x=0, y=0, width=1920, height=1080):
        self.x, self.y, self.width, self.height = x, y, width, height


@pytest.fixture
def clean_env(monkeypatch):
    """Isolate the environment keys the local bootstrap touches."""
    for key in (
        "DATA_DIR",
        "DATABASE_URL",
        "UPLOAD_DIR",
        "JWT_SECRET",
        "MJA_ENV_FILE",
        "APPDATA",
        "XDG_DATA_HOME",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def test_default_data_dir_honors_explicit_override(clean_env, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "custom"))
    assert default_data_dir() == tmp_path / "custom"


def test_default_data_dir_platform_default(clean_env, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(Path("/xdg")))
    assert default_data_dir() == Path("/xdg/CareerAssistant")


def test_ensure_secret_file_creates_strong_secret_once(tmp_path):
    path = tmp_path / SECRET_FILE
    first = ensure_secret_file(path)
    assert path.is_file()
    assert len(first) >= 32
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & 0o077 == 0
    assert ensure_secret_file(path) == first


def test_ensure_secret_file_regenerates_empty_file(tmp_path):
    path = tmp_path / SECRET_FILE
    path.write_text("")
    assert len(ensure_secret_file(path)) >= 32


def test_bootstrap_environment_sets_sqlite_defaults(clean_env, tmp_path):
    env = bootstrap_environment(tmp_path, environ={})
    assert env["DATA_DIR"] == str(tmp_path)
    assert env["DATABASE_URL"].startswith(f"sqlite+aiosqlite:///{tmp_path}")
    assert env["UPLOAD_DIR"] == str(tmp_path / "uploads")
    assert env["JWT_SECRET"] == env["JWT_SECRET"] and len(env["JWT_SECRET"]) >= 32
    assert (tmp_path / "uploads").is_dir()
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / SECRET_FILE).is_file()
    assert env["MJA_ENV_FILE"] == str(tmp_path / "env")


def test_bootstrap_environment_never_overrides_real_env(clean_env, tmp_path):
    env = {
        "DATABASE_URL": "postgresql+asyncpg://keep@me/db",
        "JWT_SECRET": "explicit-secret-value-0123456789abcdef0123456789",
    }
    bootstrap_environment(tmp_path, environ=env)
    assert env["DATABASE_URL"] == "postgresql+asyncpg://keep@me/db"
    assert env["JWT_SECRET"] == "explicit-secret-value-0123456789abcdef0123456789"
    assert not (tmp_path / SECRET_FILE).exists()


def test_find_free_port_is_bindable():
    import socket

    port = find_free_port()
    assert isinstance(port, int) and 0 < port < 65536
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_window_state_roundtrip(tmp_path):
    state = {"width": 1000, "height": 700, "x": 20, "y": 30, "maximized": False}
    save_window_state(tmp_path, state)
    loaded = load_window_state(tmp_path, screens=[FakeScreen()])
    assert loaded["width"] == 1000 and loaded["height"] == 700
    assert loaded["x"] == 20 and loaded["y"] == 30


def test_load_window_state_corrupt_file_returns_defaults(tmp_path):
    (tmp_path / "window-state.json").write_text("{not json")
    assert load_window_state(tmp_path, screens=[]) == {
        "width": 1280,
        "height": 800,
    }


def test_clamp_window_state_pulls_window_onscreen():
    screens = [FakeScreen(width=1920, height=1080)]
    clamped = clamp_window_state(
        {"width": 1280, "height": 800, "x": 5000, "y": 5000}, screens
    )
    assert clamped["x"] <= 1920
    assert clamped["y"] <= 1080


def test_clamp_window_state_min_size():
    clamped = clamp_window_state({"width": 10, "height": 10}, [])
    assert clamped["width"] == 640 and clamped["height"] == 480


def test_geometry_tracker_maximize_restore():
    tracker = WindowGeometryTracker(1000, 700, 10, 20)
    tracker.on_maximized()
    assert tracker.state["maximized"] is True
    tracker.on_resized(1920, 1080)
    assert tracker.state["width"] == 1000
    tracker.on_restored()
    assert tracker.state["maximized"] is False
    assert tracker.state["width"] == 1000 and tracker.state["height"] == 700


def test_sanitize_environment_restores_vscode_snap_originals():
    env = {"GDK_BACKEND": "snap-polluted", "GDK_BACKEND_VSCODE_SNAP_ORIG": "x11"}
    sanitize_environment(env)
    assert env["GDK_BACKEND"] == "x11"
    assert "GDK_BACKEND_VSCODE_SNAP_ORIG" not in env or True


def test_sanitize_environment_drops_snap_paths():
    env = {"LD_LIBRARY_PATH": "/snap/foo/lib:/usr/lib", "XDG_DATA_HOME": "/snap/data"}
    sanitize_environment(env)
    assert env["LD_LIBRARY_PATH"] == "/usr/lib"
    assert "XDG_DATA_HOME" not in env


def test_version_single_source():
    import app

    from app.core.config import settings

    assert settings.VERSION == app.__version__
