"""The skip wall is itself under test (plan 124 residual 3).

`tests/conftest.py::pytest_sessionfinish` compares the observed skips with
`tests/skip_allowlist.json`. These cases pin the allowlist schema and both
failure modes, so the wall cannot quietly become a no-op.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import tests.conftest as skip_wall


def _allowlist() -> dict:
    path = Path(__file__).with_name("skip_allowlist.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _fake_session(*, full_suite: bool, reporter_lines: list[str], markexpr: str = ""):
    class _Reporter:
        def write_line(self, text: str, **_kwargs) -> None:
            reporter_lines.append(text)

    class _PluginManager:
        def getplugin(self, _name: str) -> _Reporter:
            return _Reporter()

    config = SimpleNamespace(
        option=SimpleNamespace(markexpr=markexpr, keyword=""),
        args=["tests"] if full_suite else ["tests/test_jobs.py"],
        pluginmanager=_PluginManager(),
    )
    return SimpleNamespace(config=config, exitstatus=0)


def test_allowlist_entries_are_reviewed_and_unique() -> None:
    data = _allowlist()
    assert set(data) - {"$comment"} == {"postgres", "sqlite"}
    for dialect in ("postgres", "sqlite"):
        ids = [entry["id"] for entry in data[dialect]]
        assert len(ids) == len(set(ids)), f"{dialect}: duplicate skip entries"
        for entry in data[dialect]:
            assert entry["id"].startswith("tests/"), entry["id"]
            assert entry["reason_contains"].strip(), entry
            assert entry["why"].strip(), entry
            assert entry["when"] in {"always", "conditional"}, entry


def test_full_suite_detection(monkeypatch) -> None:
    full = _fake_session(full_suite=True, reporter_lines=[])
    subset = _fake_session(full_suite=False, reporter_lines=[])
    marked = _fake_session(full_suite=True, reporter_lines=[], markexpr="contract")
    assert skip_wall._targets_full_suite(full.config) is True
    assert skip_wall._targets_full_suite(subset.config) is False
    assert skip_wall._targets_full_suite(marked.config) is False


def test_unlisted_skip_fails_the_run(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_skip_allowlist",
        lambda: [{"id": "tests/test_x.py::kept", "reason_contains": "dialect", "when": "always"}],
    )
    monkeypatch.setattr(skip_wall, "_observed_skips", {"tests/test_y.py::new": "surprise"})
    lines: list[str] = []
    session = _fake_session(full_suite=False, reporter_lines=lines)
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 1
    assert any("unlisted skip: tests/test_y.py::new" in line for line in lines)


def test_allowlisted_skip_that_never_fires_fails_a_full_run(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_skip_allowlist",
        lambda: [{"id": "tests/test_x.py::gone", "reason_contains": "dialect", "when": "always"}],
    )
    monkeypatch.setattr(skip_wall, "_observed_skips", {})
    lines: list[str] = []
    session = _fake_session(full_suite=True, reporter_lines=lines)
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 1
    assert any("allowlisted skip did not fire: tests/test_x.py::gone" in line for line in lines)


def test_matching_skip_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_skip_allowlist",
        lambda: [{"id": "tests/test_x.py::kept", "reason_contains": "no engine", "when": "always"}],
    )
    monkeypatch.setattr(
        skip_wall, "_observed_skips", {"tests/test_x.py::kept": "no engine on this host"}
    )
    lines: list[str] = []
    session = _fake_session(full_suite=True, reporter_lines=lines)
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0
    assert lines == []
