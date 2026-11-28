"""Pin the shard assignment and the workflow's shard matrix (plan 227 T1)."""

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


def _shard_module() -> ModuleType:
    """Import ``scripts/check-test-shards.py`` (the name has a dash)."""
    spec = importlib.util.spec_from_file_location("check_test_shards", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    expected = list(range(1, module.SHARD_COUNT + 1))
    for job in ("backend", "backend-sqlite"):
        matrix = jobs[job]["strategy"]["matrix"]
        assert matrix["shard"] == expected, (job, matrix["shard"], expected)
        assert jobs[job]["strategy"]["fail-fast"] is False
    assert jobs["backend-gate"]["needs"] == "backend"
    assert jobs["backend-sqlite-gate"]["needs"] == "backend-sqlite"


def test_the_protected_backend_context_is_owned_by_one_gate_job() -> None:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    holders = [job for job, spec in jobs.items() if spec.get("name") == PROTECTED_BACKEND_CHECK]
    assert holders == ["backend-gate"], holders
    gate = jobs[holders[0]]
    assert gate["needs"] == "backend"
    assert gate.get("if") == "always()"
    assert jobs["backend"]["strategy"]["matrix"]["shard"] == list(
        range(1, _shard_module().SHARD_COUNT + 1)
    )
