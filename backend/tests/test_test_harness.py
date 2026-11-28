"""The xdist worker harness owns its state (plan 226).

``tests/xdist_routing.py`` points every routed worker at its own database
*and* its own data/upload trees before the app settings exist, and
``tests/conftest.py`` asserts the settings landed there. These cases pin the
routing branches, the exemptions and the worker-scoped cleanup.
"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.conftest as harness
import tests.xdist_routing as routing


def test_sqlite_worker_gets_its_own_database_and_state_trees(tmp_path, monkeypatch) -> None:
    worker_root = tmp_path / "gw0"
    url = routing._worker_sqlite_url(
        "sqlite+aiosqlite:///./neuronection_career_test.db", worker_root
    )
    assert url == f"sqlite+aiosqlite:///{worker_root}/neuronection_career_test.db"

    monkeypatch.setenv("CAREER_DATA_DIR", "shared-before")
    monkeypatch.setenv("CAREER_UPLOAD_DIR", "shared-before")
    routing._route_worker_state(worker_root)

    assert os.environ["CAREER_DATA_DIR"] == str(worker_root / "data")
    assert os.environ["CAREER_UPLOAD_DIR"] == str(worker_root / "uploads")
    assert (worker_root / "data").is_dir()
    assert (worker_root / "uploads").is_dir()


def test_sqlite_memory_database_is_not_routed(tmp_path) -> None:
    assert routing._worker_sqlite_url("sqlite+aiosqlite:///:memory:", tmp_path) is None
    assert routing._worker_sqlite_url("sqlite+aiosqlite:///", tmp_path) is None


def test_postgres_worker_gets_its_own_database() -> None:
    base = (
        "postgresql+asyncpg://neuronection_career_owner:career_dev_pw"
        "@127.0.0.1:5684/neuronection_career_test?sslmode=disable"
    )
    assert routing._worker_postgres_url(base, "gw3") == (
        "postgresql+asyncpg://neuronection_career_owner:career_dev_pw"
        "@127.0.0.1:5684/neuronection_career_test_gw3?sslmode=disable"
    )
    assert routing._worker_postgres_url("postgresql+asyncpg://host/", "gw3") is None


def test_no_worker_is_a_no_op(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("CAREER_DATA_DIR", raising=False)
    monkeypatch.delenv("CAREER_UPLOAD_DIR", raising=False)
    monkeypatch.setattr(routing, "_worker_root", None)

    routing.route_worker_database()

    assert routing.routed_worker_root() is None
    assert "CAREER_DATA_DIR" not in os.environ
    assert "CAREER_UPLOAD_DIR" not in os.environ


def test_missing_database_url_is_a_no_op(monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    monkeypatch.delenv("CAREER_DATABASE_URL", raising=False)
    monkeypatch.delenv("CAREER_DATA_DIR", raising=False)
    monkeypatch.setattr(routing, "_worker_root", None)

    routing.route_worker_database()

    assert routing.routed_worker_root() is None
    assert "CAREER_DATA_DIR" not in os.environ


def test_in_memory_database_is_exempt(monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    monkeypatch.setenv("CAREER_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.delenv("CAREER_DATA_DIR", raising=False)
    monkeypatch.setattr(routing, "_worker_root", None)

    routing.route_worker_database()

    assert routing.routed_worker_root() is None
    assert "CAREER_DATA_DIR" not in os.environ


def test_routing_after_the_app_config_raises(monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    monkeypatch.setenv("CAREER_DATABASE_URL", "sqlite+aiosqlite:///./neuronection_career_test.db")

    with pytest.raises(RuntimeError, match=r"after app\.core\.config was imported"):
        routing.route_worker_database()


def test_worker_cleanup_never_touches_a_sibling_worker(tmp_path, monkeypatch) -> None:
    stale = tmp_path / "gw0" / "data" / "previews" / "stale.bin"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")

    sibling = tmp_path / "gw1"
    (sibling / "data").mkdir(parents=True)
    (sibling / "uploads").mkdir(parents=True)
    live_db = sibling / "neuronection_career_test.db"
    live_db.write_text("live", encoding="utf-8")

    monkeypatch.setenv("CAREER_DATA_DIR", "shared-before")
    monkeypatch.setenv("CAREER_UPLOAD_DIR", "shared-before")
    routing._route_worker_state(tmp_path / "gw0")

    assert not stale.exists()
    assert live_db.read_text(encoding="utf-8") == "live"
    assert (sibling / "data").is_dir()
    assert (sibling / "uploads").is_dir()


def test_routed_settings_must_stay_inside_the_worker_root(tmp_path, monkeypatch) -> None:
    worker_root = tmp_path / "gw0"
    monkeypatch.setattr(harness, "routed_worker_root", lambda: worker_root)
    monkeypatch.setattr(
        harness,
        "settings",
        SimpleNamespace(data_dir=worker_root / "data", upload_root=worker_root / "uploads"),
    )
    harness._assert_worker_state_isolation()

    monkeypatch.setattr(
        harness,
        "settings",
        SimpleNamespace(data_dir=tmp_path / "shared_data", upload_root=worker_root / "uploads"),
    )
    with pytest.raises(RuntimeError, match="escaped its worker directory"):
        harness._assert_worker_state_isolation()


def test_unrouted_session_skips_the_isolation_assertion(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(harness, "routed_worker_root", lambda: None)
    monkeypatch.setattr(
        harness,
        "settings",
        SimpleNamespace(data_dir=tmp_path / "shared_data", upload_root=tmp_path / "shared_uploads"),
    )

    harness._assert_worker_state_isolation()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 0),
        (0, 0),
        (1, 1),
        (2, 2),
        ("auto", os.cpu_count() or 1),
        ("logical", os.cpu_count() or 1),
        ("4", 4),
    ],
)
def test_worker_count_normalisation(raw, expected, monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
    config = SimpleNamespace(getoption=lambda _name, default=None: raw)
    assert harness._resolved_worker_count(config) == expected


def test_worker_count_reads_the_xdist_worker_environment(monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "4")
    config = SimpleNamespace(getoption=lambda _name, default=None: None)
    assert harness._resolved_worker_count(config) == 4


def test_worker_count_zero_is_not_parallel(monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "4")
    config = SimpleNamespace(getoption=lambda _name, default=None: 0)
    assert harness._resolved_worker_count(config) == 0


def _guard_config(raw_workers):
    return SimpleNamespace(getoption=lambda _name, default=None: raw_workers)


def test_serial_guard_trips_in_a_parallel_sqlite_session(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
    monkeypatch.setattr(harness, "IS_SQLITE", True)
    for workers in (2, 4, "auto"):
        violation = harness._serial_guard_violation(_guard_config(workers), ["tests/test_x.py::t"])
        assert '-m "not serial"' in violation
        assert "serial test" not in violation


def test_serial_guard_ignores_the_postgres_profile(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
    monkeypatch.setattr(harness, "IS_SQLITE", False)
    assert harness._serial_guard_violation(_guard_config(4), ["tests/test_x.py::t"]) == ""


def test_serial_guard_ignores_a_single_or_absent_worker(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
    monkeypatch.setattr(harness, "IS_SQLITE", True)
    for workers in (None, 0, 1):
        assert harness._serial_guard_violation(_guard_config(workers), ["tests/test_x.py::t"]) == ""


def test_serial_guard_ignores_unmarked_sessions(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
    monkeypatch.setattr(harness, "IS_SQLITE", True)
    assert harness._serial_guard_violation(_guard_config(4), []) == ""


def test_routed_worker_points_at_its_own_database_and_trees() -> None:
    worker_root = routing.routed_worker_root()
    if worker_root is None:
        assert "_xdist" not in harness.TEST_DB_URL
        return
    root = worker_root.resolve()
    if harness.IS_SQLITE:
        assert f"tests/_xdist/{worker_root.name}/" in harness.TEST_DB_URL
    else:
        assert harness.TEST_DB_URL.endswith(f"_test_{worker_root.name}")
    assert Path(str(harness.settings.data_dir)).resolve().is_relative_to(root)
    assert Path(harness.settings.upload_root).resolve().is_relative_to(root)
