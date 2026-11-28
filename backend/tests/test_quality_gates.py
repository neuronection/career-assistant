"""The skip wall is itself under test (plan 124 residual 3).

`tests/conftest.py::pytest_sessionfinish` compares the observed skips with
`tests/skip_allowlist.json`. These cases pin the allowlist schema and both
failure modes, so the wall cannot quietly become a no-op.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.conftest as skip_wall


@pytest.fixture(autouse=True)
def _isolated_skip_journal(monkeypatch, tmp_path):
    """The merged-observation journal is per-worktree state — never touch the real one."""
    monkeypatch.setattr(skip_wall, "_SKIP_OBSERVATIONS_PATH", tmp_path / "skip_observations.json")


def _allowlist() -> dict:
    path = Path(__file__).with_name("skip_allowlist.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _fake_session(
    *,
    full_suite: bool,
    reporter_lines: list[str],
    markexpr: str = "",
    no_skip_wall: bool = False,
):
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
        getoption=lambda name, default=None: no_skip_wall if name == "--no-skip-wall" else default,
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


def test_dynamic_skip_reports_are_recorded(monkeypatch) -> None:
    """`pytest.skip()` in a fixture or test body is a `report.skipped`
    with no marker metadata — the wall must record it the same way it
    records a marked skip, or capability gaps slip past silently."""
    monkeypatch.setattr(skip_wall, "_observed_skips", {})

    def _report(nodeid: str, *, skipped: bool, when: str, reason: str | None):
        longrepr = ("tests/test_x.py", 12, f"Skipped: {reason}") if reason else None
        return SimpleNamespace(nodeid=nodeid, skipped=skipped, when=when, longrepr=longrepr)

    skip_wall.pytest_runtest_logreport(
        _report("tests/test_x.py::dynamic", skipped=True, when="call", reason="no PDF engine")
    )
    skip_wall.pytest_runtest_logreport(
        _report("tests/test_x.py::marked", skipped=True, when="setup", reason="dialect only")
    )
    skip_wall.pytest_runtest_logreport(
        _report("tests/test_x.py::passed", skipped=False, when="call", reason=None)
    )
    assert skip_wall._observed_skips == {
        "tests/test_x.py::dynamic": "no PDF engine",
        "tests/test_x.py::marked": "dialect only",
    }


def test_dynamic_skip_without_marker_still_fails_an_unlisted_run(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "_skip_allowlist", lambda: [])
    monkeypatch.setattr(skip_wall, "_observed_skips", {})
    skip_wall.pytest_runtest_logreport(
        SimpleNamespace(
            nodeid="tests/test_x.py::dynamic",
            skipped=True,
            when="call",
            longrepr=("tests/test_x.py", 12, "Skipped: no PDF engine on this host"),
        )
    )
    lines: list[str] = []
    session = _fake_session(full_suite=False, reporter_lines=lines)
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 1
    assert any("unlisted skip: tests/test_x.py::dynamic" in line for line in lines)


def _write_journal(lanes: dict[str, dict[str, str]]) -> None:
    path = skip_wall._SKIP_OBSERVATIONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lanes), encoding="utf-8")


def test_final_lane_without_the_parallel_lane_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "_skip_allowlist", lambda: [])
    monkeypatch.setattr(skip_wall, "_observed_skips", {})
    lines: list[str] = []
    session = _fake_session(full_suite=True, reporter_lines=lines, markexpr="serial")
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 1
    assert any("final lane without the parallel lane's observations" in line for line in lines)


def test_final_lane_judges_the_merged_lanes(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_skip_allowlist",
        lambda: [{"id": "tests/test_x.py::a", "reason_contains": "dialect", "when": "always"}],
    )
    monkeypatch.setattr(skip_wall, "_observed_skips", {})
    _write_journal({"not serial": {"tests/test_x.py::a": "dialect only"}})
    lines: list[str] = []
    session = _fake_session(full_suite=True, reporter_lines=lines, markexpr="serial")
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0, lines


def test_final_lane_catches_an_allowlisted_skip_that_never_fired(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_skip_allowlist",
        lambda: [{"id": "tests/test_x.py::gone", "reason_contains": "dialect", "when": "always"}],
    )
    monkeypatch.setattr(skip_wall, "_observed_skips", {})
    _write_journal({"not serial": {}})
    lines: list[str] = []
    session = _fake_session(full_suite=True, reporter_lines=lines, markexpr="serial")
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 1
    assert any("allowlisted skip did not fire: tests/test_x.py::gone" in line for line in lines)


def test_parallel_lane_never_evaluates_completeness(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_skip_allowlist",
        lambda: [{"id": "tests/test_x.py::gone", "reason_contains": "dialect", "when": "always"}],
    )
    monkeypatch.setattr(skip_wall, "_observed_skips", {})
    lines: list[str] = []
    session = _fake_session(full_suite=True, reporter_lines=lines, markexpr="not serial")
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0
    assert lines == []


def test_partial_selector_keeps_todays_behaviour(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "_skip_allowlist", lambda: [])
    monkeypatch.setattr(skip_wall, "_observed_skips", {})
    _write_journal({"not serial": {"tests/test_x.py::a": "dialect only"}})
    lines: list[str] = []
    session = _fake_session(full_suite=True, reporter_lines=lines, markexpr="contract")
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0


def test_full_run_judges_this_runs_observations(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_skip_allowlist",
        lambda: [{"id": "tests/test_x.py::a", "reason_contains": "dialect", "when": "always"}],
    )
    monkeypatch.setattr(skip_wall, "_observed_skips", {"tests/test_x.py::a": "dialect only"})
    _write_journal({"not serial": {"tests/test_x.py::stale": "an earlier lane"}})
    lines: list[str] = []
    session = _fake_session(full_suite=True, reporter_lines=lines)
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0, lines


def test_full_run_ignores_an_earlier_runs_observations(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_skip_allowlist",
        lambda: [{"id": "tests/test_x.py::a", "reason_contains": "dialect", "when": "always"}],
    )
    monkeypatch.setattr(skip_wall, "_observed_skips", {})
    _write_journal(
        {
            "": {"tests/test_x.py::a": "dialect only"},
            "not serial": {"tests/test_x.py::a": "dialect only"},
        }
    )
    lines: list[str] = []
    session = _fake_session(full_suite=True, reporter_lines=lines)
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 1
    assert any("allowlisted skip did not fire: tests/test_x.py::a" in line for line in lines)


def test_journal_replaces_the_lane_key(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "_skip_allowlist", lambda: [])
    monkeypatch.setattr(skip_wall, "_observed_skips", {"tests/test_x.py::new": "now"})
    _write_journal({"not serial": {"tests/test_x.py::old": "an earlier run"}})
    session = _fake_session(full_suite=False, reporter_lines=[], markexpr="not serial")
    skip_wall.pytest_sessionfinish(session, 0)
    journal = json.loads(skip_wall._SKIP_OBSERVATIONS_PATH.read_text(encoding="utf-8"))
    assert journal["not serial"] == {"tests/test_x.py::new": "now"}


def test_collect_only_does_not_judge_completeness(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_skip_allowlist",
        lambda: [{"id": "tests/test_x.py::gone", "reason_contains": "dialect", "when": "always"}],
    )
    monkeypatch.setattr(skip_wall, "_observed_skips", {})
    lines: list[str] = []
    session = _fake_session(full_suite=True, reporter_lines=lines)
    session.config.option.collectonly = True
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0, lines


def test_no_skip_wall_disables_completeness_only(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "_skip_allowlist", lambda: [])
    monkeypatch.setattr(skip_wall, "_observed_skips", {})
    lines: list[str] = []
    session = _fake_session(
        full_suite=True, reporter_lines=lines, markexpr="serial", no_skip_wall=True
    )
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0, lines

    monkeypatch.setattr(skip_wall, "_observed_skips", {"tests/test_y.py::new": "surprise"})
    lines = []
    session = _fake_session(
        full_suite=True, reporter_lines=lines, markexpr="serial", no_skip_wall=True
    )
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 1
    assert any("unlisted skip: tests/test_y.py::new" in line for line in lines)


def test_observed_skips_are_merged_under_the_exact_markexpr(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "_skip_allowlist", lambda: [])
    monkeypatch.setattr(skip_wall, "_observed_skips", {"tests/test_x.py::a": "dialect only"})
    _write_journal({"": {"tests/test_x.py::old": "old reason"}})
    session = _fake_session(full_suite=False, reporter_lines=[], markexpr="not serial")
    skip_wall.pytest_sessionfinish(session, 0)
    journal = json.loads(skip_wall._SKIP_OBSERVATIONS_PATH.read_text(encoding="utf-8"))
    assert journal["not serial"] == {"tests/test_x.py::a": "dialect only"}
    assert journal[""] == {"tests/test_x.py::old": "old reason"}


_SERIAL_ENTRY = {
    "id": "tests/test_storage_health.py::test_slow_probe_times_out_as_degraded",
    "criterion": "H3",
    "resource": "backend/tests/test_storage_health.py:174",
    "why": "asserts an elapsed bound against a 0.05 s probe timeout",
}


def test_shipped_serial_registry_is_valid() -> None:
    data = json.loads(skip_wall._SERIAL_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert data["$comment"].strip()
    assert isinstance(data["entries"], list)
    assert skip_wall._serial_registry_problems([], full_run=False) == []


def test_serial_entry_shape_is_enforced(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_serial_allowlist",
        lambda: [
            {**_SERIAL_ENTRY, "criterion": "H9"},
            {**_SERIAL_ENTRY, "why": "  "},
            {**_SERIAL_ENTRY, "resource": "backend/tests/does_not_exist.py:3"},
            {**_SERIAL_ENTRY, "resource": "backend/tests/test_storage_health.py:999999"},
            {**_SERIAL_ENTRY, "resource": "not-a-line"},
            {**_SERIAL_ENTRY, "id": ""},
        ],
    )
    problems = skip_wall._serial_registry_problems([], full_run=False)
    assert any("criterion must be H2 or H3" in problem for problem in problems)
    assert any("why must be non-empty" in problem for problem in problems)
    assert any("resource file does not exist" in problem for problem in problems)
    assert any("resource line is past the end" in problem for problem in problems)
    assert any("resource must be a path:line reference" in problem for problem in problems)
    assert any("entry without an id" in problem for problem in problems)


def test_serial_registry_rejects_duplicate_ids(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "_serial_allowlist", lambda: [_SERIAL_ENTRY, _SERIAL_ENTRY])
    problems = skip_wall._serial_registry_problems([], full_run=False)
    assert any("duplicate serial registry id" in problem for problem in problems)


def test_marked_but_unregistered_fails(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "_serial_allowlist", lambda: [])
    problems = skip_wall._serial_registry_problems(["tests/test_x.py::t"], full_run=False)
    assert any(
        "serial test not in the registry: tests/test_x.py::t" in problem for problem in problems
    )


def test_registry_entry_matching_nothing_fails_on_a_full_run_only(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "_serial_allowlist", lambda: [_SERIAL_ENTRY])
    assert skip_wall._serial_registry_problems([], full_run=False) == []
    problems = skip_wall._serial_registry_problems([], full_run=True)
    assert any("matches nothing on a full run" in problem for problem in problems)


def test_registry_prefix_entry_covers_a_whole_file(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_serial_allowlist",
        lambda: [{**_SERIAL_ENTRY, "id": "tests/test_storage_health.py"}],
    )
    marked = ["tests/test_storage_health.py::test_a", "tests/test_storage_health.py::test_b"]
    assert skip_wall._serial_registry_problems(marked, full_run=True) == []


def test_collection_refuses_an_unregistered_serial_marker(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "_serial_allowlist", lambda: [])
    item = SimpleNamespace(nodeid="tests/test_x.py::t", get_closest_marker=lambda _name: object())
    config = SimpleNamespace(option=SimpleNamespace(markexpr="", keyword=""), args=["tests"])
    with pytest.raises(pytest.UsageError, match="not in the registry"):
        skip_wall.pytest_collection_modifyitems(config, [item])


def _serial_item(nodeid: str = "tests/test_extension_sandbox.py::test_x") -> SimpleNamespace:
    return SimpleNamespace(
        nodeid=nodeid,
        get_closest_marker=lambda name: object() if name == skip_wall.SERIAL_MARKER else None,
    )


def _collection_config(raw_workers):
    return SimpleNamespace(
        option=SimpleNamespace(markexpr="", keyword=""),
        args=["tests/test_extension_sandbox.py"],
        getoption=lambda _name, default=None: raw_workers,
    )


def test_collection_guard_refuses_a_parallel_sqlite_collection(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "IS_SQLITE", True)
    for raw_workers in (2, "auto"):
        with pytest.raises(pytest.UsageError, match='-m "not serial"'):
            skip_wall.pytest_collection_modifyitems(
                _collection_config(raw_workers), [_serial_item()]
            )


def test_collection_guard_allows_a_single_worker(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "IS_SQLITE", True)
    skip_wall.pytest_collection_modifyitems(_collection_config(1), [_serial_item()])


def test_setup_guard_refuses_a_worker_side_serial_item(monkeypatch) -> None:
    monkeypatch.setattr(skip_wall, "IS_SQLITE", True)
    item = SimpleNamespace(
        nodeid="tests/test_extension_sandbox.py::test_x",
        config=SimpleNamespace(getoption=lambda _name, default=None: 2),
        get_closest_marker=lambda name: object() if name == skip_wall.SERIAL_MARKER else None,
    )
    with pytest.raises(pytest.fail.Exception, match='-m "not serial"'):
        skip_wall.pytest_runtest_setup(item)


def test_serial_lane_on_a_narrowed_path_has_no_completeness(monkeypatch) -> None:
    monkeypatch.setattr(
        skip_wall,
        "_skip_allowlist",
        lambda: [{"id": "tests/test_x.py::gone", "reason_contains": "dialect", "when": "always"}],
    )
    monkeypatch.setattr(skip_wall, "_observed_skips", {})
    lines: list[str] = []
    session = _fake_session(full_suite=False, reporter_lines=lines, markexpr="serial")
    skip_wall.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0, lines
