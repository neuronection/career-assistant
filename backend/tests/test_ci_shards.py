"""Pin the shard assignment and the workflow's shard/check job split (plan 227 T1)."""

from __future__ import annotations

import functools
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import yaml

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SCRIPT = ROOT / "scripts" / "check-test-shards.py"
DURATIONS = BACKEND / "tests" / "ci_durations.json"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PROTECTED_BACKEND_CHECK = "Backend (ruff + pytest)"
SQLITE_GATE = "backend-sqlite-gate"
SQLITE_CHECKS = "backend-sqlite-checks"
SQLITE_CHECKS_NAME = "Backend on SQLite (desktop profile) — checks"
POSTGRES_GATE = "backend-gate"
POSTGRES_CHECKS = "backend-checks"
POSTGRES_CHECKS_NAME = "Backend checks (static + contract)"
# Plan 227 T1 follow-up: these read the tree, not the shard artifacts, so they
# run in their own job alongside the matrix instead of behind it in the gate.
TREE_ONLY_SQLITE_STEPS = (
    "Partition integrity (no test lost, none doubled)",
    "Spawner teardown gate (unraisable leaks fatal)",
    "Contract drift gate (identity-auth §18)",
)
POSTGRES_STATIC_STEPS = (
    "Tracing suite with the otel extra installed (plan 168)",
    "Contract drift gate (identity-auth §18)",
    "OpenAPI contract diff",
    "Type check (mypy)",
    "Type ratchet (app/services wall)",
    "Dependency audit (pip-audit, blocking with reviewed allowlist)",
)
SQLITE_REQUIRED_UPSTREAM_GUARD = "Require the shards and the tree-only checks"
POSTGRES_REQUIRED_UPSTREAM_GUARD = "Require the shards and the static checks"


def _shard_module() -> ModuleType:
    """Import ``scripts/check-test-shards.py`` (the name has a dash)."""
    spec = importlib.util.spec_from_file_location("check_test_shards", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jobs() -> dict[str, dict]:
    """The workflow's job mapping."""
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _needs(spec: dict) -> set[str]:
    """A job's ``needs`` as a set, accepting the scalar and list YAML forms."""
    needs = spec.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


@functools.lru_cache(maxsize=1)
def _collected_files() -> tuple[str, ...]:
    """The file list pytest collects from ``tests`` right now."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_XDIST_")}
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-o", "addopts="],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    nodeids = {line.split("::", 1)[0] for line in completed.stdout.splitlines() if "::" in line}
    return tuple(sorted(nodeids))


def test_duration_table_names_only_collected_test_files() -> None:
    durations = _shard_module().load_durations(DURATIONS)
    assert durations, "the duration table is empty"
    for path in durations:
        file = BACKEND / path
        assert path.startswith("tests/test_"), path
        assert file.name.startswith("test_") and file.suffix == ".py", path
        assert file.is_file(), f"{path} is not a real test file"


def test_assignment_covers_the_collected_tree_for_two_and_four_shards() -> None:
    module = _shard_module()
    durations = module.load_durations(DURATIONS)
    files = list(_collected_files())
    assert files
    for shard_count in (2, 4):
        buckets = module.assign_shards(files, durations, shard_count)
        problems = module.validate_assignment(buckets, files)
        assert not problems, (shard_count, problems)
        assert all(buckets), f"shard {shard_count} left a shard empty"


def test_a_duplicated_file_fails_the_assignment() -> None:
    module = _shard_module()
    buckets = [["tests/test_a.py", "tests/test_b.py"], ["tests/test_b.py", "tests/test_c.py"]]
    files = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]
    problems = module.validate_assignment(buckets, files)
    assert any("duplicate" in problem for problem in problems), problems


def test_an_empty_shard_fails_the_assignment() -> None:
    module = _shard_module()
    problems = module.validate_assignment([["tests/test_a.py"], []], ["tests/test_a.py"])
    assert any("empty" in problem for problem in problems), problems


def test_the_workflow_matches_the_committed_shard_count() -> None:
    module = _shard_module()
    jobs = _jobs()
    expected = list(range(1, module.SHARD_COUNT + 1))
    for job in ("backend", "backend-sqlite"):
        matrix = jobs[job]["strategy"]["matrix"]
        assert matrix["shard"] == expected, (job, matrix["shard"], expected)
        assert jobs[job]["strategy"]["fail-fast"] is False
    assert _needs(jobs[POSTGRES_GATE]) == {"backend", POSTGRES_CHECKS}
    assert _needs(jobs[SQLITE_GATE]) == {"backend-sqlite", SQLITE_CHECKS}


def test_the_postgres_static_checks_overlap_the_shards() -> None:
    jobs = _jobs()
    checks = jobs[POSTGRES_CHECKS]
    assert checks["name"] == POSTGRES_CHECKS_NAME
    # No `needs`: the static gates must overlap the shard matrix, not queue
    # after it.
    assert "needs" not in checks, checks.get("needs")
    # Same lane service/env as the shards, so the moved commands keep working.
    assert checks["env"] == jobs["backend"]["env"]
    assert checks["services"] == jobs["backend"]["services"]
    step_names = [step.get("name") for step in checks["steps"]]
    for name in POSTGRES_STATIC_STEPS:
        assert name in step_names, name
    # The independence is the point: no shard artifact is downloaded here.
    assert not any("download-artifact" in str(step.get("uses", "")) for step in checks["steps"])

    gate = jobs[POSTGRES_GATE]
    assert _needs(gate) == {"backend", POSTGRES_CHECKS}
    gate_steps = [step.get("name") for step in gate["steps"]]
    for name in POSTGRES_STATIC_STEPS:
        assert name not in gate_steps, name
    # The protected context fails closed when a dependency failed; without this
    # step `if: always()` would report green while mypy/contract were red.
    assert POSTGRES_REQUIRED_UPSTREAM_GUARD in gate_steps


def test_the_gate_jobs_run_only_the_coverage_tail_and_the_sqlite_serial_lane() -> None:
    jobs = _jobs()
    serial_lane = "Run tests — serial lane (whole tree, single process)"
    postgres_runs = [str(step.get("run", "")) for step in jobs[POSTGRES_GATE]["steps"]]
    assert not any("pytest" in run for run in postgres_runs)

    sqlite_pytest_steps = [
        step.get("name")
        for step in jobs[SQLITE_GATE]["steps"]
        if "pytest" in str(step.get("run", ""))
    ]
    assert sqlite_pytest_steps == [serial_lane], sqlite_pytest_steps
    sqlite_gate_steps = [step.get("name") for step in jobs[SQLITE_GATE]["steps"]]
    assert SQLITE_REQUIRED_UPSTREAM_GUARD in sqlite_gate_steps


def test_the_sqlite_checks_job_overlaps_the_shards() -> None:
    jobs = _jobs()
    checks = jobs[SQLITE_CHECKS]
    assert checks["name"] == SQLITE_CHECKS_NAME
    # No `needs`: the tree-only checks must overlap the shard matrix, not queue
    # after it (that serial tail is the cost this job exists to remove).
    assert "needs" not in checks, checks.get("needs")
    assert checks["env"] == jobs[SQLITE_GATE]["env"]
    step_names = [step.get("name") for step in checks["steps"]]
    for name in TREE_ONLY_SQLITE_STEPS:
        assert name in step_names, name
    # The independence is the point: no shard artifact is downloaded here.
    assert not any("download-artifact" in str(step.get("uses", "")) for step in checks["steps"])

    gate = jobs[SQLITE_GATE]
    assert _needs(gate) == {"backend-sqlite", SQLITE_CHECKS}
    gate_steps = [step.get("name") for step in gate["steps"]]
    for name in TREE_ONLY_SQLITE_STEPS:
        assert name not in gate_steps, name
    # The gate keeps the whole-tree serial lane and the one coverage floor.
    assert "Run tests — serial lane (whole tree, single process)" in gate_steps
    assert "Coverage floor (whole suite, both shards)" in gate_steps


def test_the_sqlite_tree_only_gates_run_in_exactly_one_job() -> None:
    jobs = _jobs()
    sqlite_jobs = {
        job: spec
        for job, spec in jobs.items()
        if str(spec.get("name", "")).startswith("Backend on SQLite")
    }
    for name in TREE_ONLY_SQLITE_STEPS:
        holders = [
            job
            for job, spec in sqlite_jobs.items()
            if any(step.get("name") == name for step in spec["steps"])
        ]
        assert holders == [SQLITE_CHECKS], (name, holders)


def test_the_protected_backend_context_is_owned_by_one_gate_job() -> None:
    jobs = _jobs()
    holders = [job for job, spec in jobs.items() if spec.get("name") == PROTECTED_BACKEND_CHECK]
    assert holders == [POSTGRES_GATE], holders
    gate = jobs[holders[0]]
    # The required check subsumes the static checks: a red mypy/contract job
    # must fail the protected context, not run beside it.
    assert _needs(gate) == {"backend", POSTGRES_CHECKS}
    assert gate.get("if") == "always()"
    assert jobs["backend"]["strategy"]["matrix"]["shard"] == list(
        range(1, _shard_module().SHARD_COUNT + 1)
    )
