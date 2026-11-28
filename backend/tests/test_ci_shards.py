"""Pin the shard assignment and the workflow's shard/check job split (plan 227 T1)."""

from __future__ import annotations

import functools
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import yaml

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SCRIPT = ROOT / "scripts" / "check-test-shards.py"
SKIP_WALL_SCRIPT = ROOT / "scripts" / "check-skip-wall.py"
DURATIONS = BACKEND / "tests" / "ci_durations.json"
ALLOWLIST = BACKEND / "tests" / "skip_allowlist.json"
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
POSTGRES_OBSERVATIONS_SKIP_WALL = "Check the Postgres skip wall (merged shards)"
MERGE_OBSERVATIONS = "Merge shard skip observations"
VERIFY_JUNIT_UNION = "Verify the shard JUnit union"


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


def _step(job: str, name: str) -> dict:
    """One named step of a workflow job."""
    return next(step for step in _jobs()[job]["steps"] if step.get("name") == name)


def _run_script(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one repository script with the current interpreter."""
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _always_entries() -> list[dict[str, str]]:
    """The Postgres allowlist's ``when: always`` entries."""
    data = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    return [entry for entry in data["postgres"] if entry.get("when", "always") == "always"]


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

    def executed_pytest_steps(job: str) -> list[str]:
        return [
            step.get("name")
            for step in jobs[job]["steps"]
            if "pytest" in str(step.get("run", ""))
            and "--collect-only" not in str(step.get("run", ""))
        ]

    assert executed_pytest_steps(POSTGRES_GATE) == []
    assert executed_pytest_steps(SQLITE_GATE) == [serial_lane]
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


def test_the_gate_dependency_guards_run_before_checkout_outside_backend() -> None:
    jobs = _jobs()
    gates = {
        POSTGRES_GATE: POSTGRES_REQUIRED_UPSTREAM_GUARD,
        SQLITE_GATE: SQLITE_REQUIRED_UPSTREAM_GUARD,
    }
    for job, guard_name in gates.items():
        steps = jobs[job]["steps"]
        run_steps = [step for step in steps if "run" in step]
        guard = next(step for step in steps if step.get("name") == guard_name)
        assert run_steps[0] is guard, (job, [step.get("name") for step in run_steps[:2]])
        # The job default is `backend/`, which checkout has not created yet:
        # a guard that inherits it makes GitHub fail to start the process.
        assert guard.get("working-directory") not in (None, "backend"), job

    # The same failure class for any later pre-checkout run step in the gate
    # and checks jobs: it must opt out of the `backend/` job default.
    for job in (POSTGRES_GATE, POSTGRES_CHECKS, SQLITE_GATE, SQLITE_CHECKS):
        steps = jobs[job]["steps"]
        checkout = next(
            index
            for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith("actions/checkout@")
        )
        for step in steps[:checkout]:
            if "run" not in step:
                continue
            assert step.get("working-directory") not in (None, "backend"), (
                job,
                step.get("name"),
            )


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


def test_the_postgres_gate_restores_the_skip_wall_completeness() -> None:
    jobs = _jobs()
    uploads = [
        str(step.get("with", {}).get("name", ""))
        for step in jobs["backend"]["steps"]
        if "upload-artifact" in str(step.get("uses", ""))
    ]
    assert any(name.startswith("postgres-observations-") for name in uploads), uploads

    gate = jobs[POSTGRES_GATE]
    downloads = [
        str(step.get("with", {}).get("pattern", ""))
        for step in gate["steps"]
        if "download-artifact" in str(step.get("uses", ""))
    ]
    assert "postgres-observations-*" in downloads, downloads

    merge = str(_step(POSTGRES_GATE, MERGE_OBSERVATIONS)["run"])
    assert "--merge-observations" in merge
    assert '--lane ""' in merge

    wall = str(_step(POSTGRES_GATE, POSTGRES_OBSERVATIONS_SKIP_WALL)["run"])
    assert "check-skip-wall.py --dialect postgres" in wall
    assert '--lane ""' in wall


def test_a_merged_journal_missing_an_always_entry_fails_the_postgres_wall(
    tmp_path: Path,
) -> None:
    entries = _always_entries()
    assert entries
    observed = {
        entry["id"].replace("*", "probe"): f"prefix {entry['reason_contains']} suffix"
        for entry in entries
    }
    journal = tmp_path / "journal.json"
    journal.write_text(json.dumps({"": observed}), encoding="utf-8")

    def run() -> subprocess.CompletedProcess[str]:
        return _run_script(
            SKIP_WALL_SCRIPT,
            "--dialect",
            "postgres",
            "--lane",
            "",
            "--journal",
            str(journal),
        )

    complete = run()
    assert complete.returncode == 0, complete.stderr
    dropped = entries[0]
    observed.pop(dropped["id"].replace("*", "probe"))
    journal.write_text(json.dumps({"": observed}), encoding="utf-8")
    short = run()
    assert short.returncode == 1, short.stdout
    assert f"allowlisted skip did not fire: {dropped['id']}" in short.stderr, short.stderr


def test_the_skip_wall_self_test_passes() -> None:
    completed = _run_script(SKIP_WALL_SCRIPT, "--self-test")
    assert completed.returncode == 0, completed.stderr
    assert "self-test ok" in completed.stdout


def test_both_gates_verify_the_shard_junit_union() -> None:
    expected_files = {POSTGRES_GATE: "/tmp/nodes.txt", SQLITE_GATE: "/tmp/all.txt"}
    for gate, nodes in expected_files.items():
        step = _step(gate, VERIFY_JUNIT_UNION)
        run = str(step["run"])
        assert "--verify-junit" in run, (gate, run)
        assert f"--files {nodes}" in run, (gate, run)
        downloads = [
            str(entry.get("with", {}).get("name", ""))
            for entry in _jobs()[gate]["steps"]
            if "download-artifact" in str(entry.get("uses", ""))
        ]
        assert any(name.endswith("-nodes") for name in downloads), (gate, downloads)
    sqlite_verify = str(_step(SQLITE_GATE, VERIFY_JUNIT_UNION)["run"])
    assert "junit-serial.xml" in sqlite_verify
    serial_run = str(
        _step(SQLITE_GATE, "Run tests — serial lane (whole tree, single process)")["run"]
    )
    assert "--junitxml=junit-serial.xml" in serial_run


def test_the_gates_use_the_partition_node_manifest() -> None:
    jobs = _jobs()
    uploads = {
        POSTGRES_GATE: ("backend", "postgres-nodes"),
        SQLITE_GATE: (SQLITE_CHECKS, "sqlite-nodes"),
    }
    for gate, (producer, artifact) in uploads.items():
        names = [
            str(step.get("with", {}).get("name", ""))
            for step in jobs[producer]["steps"]
            if "upload-artifact" in str(step.get("uses", ""))
        ]
        assert artifact in names, (producer, names)
        downloads = [
            str(step.get("with", {}).get("name", ""))
            for step in jobs[gate]["steps"]
            if "download-artifact" in str(step.get("uses", ""))
        ]
        assert artifact in downloads, (gate, downloads)


def test_junit_union_verification_rejects_a_shortfall(tmp_path: Path) -> None:
    module = _shard_module()
    manifest = tmp_path / "nodes.txt"
    manifest.write_text("tests/test_a.py::t1\ntests/test_a.py::t2\n", encoding="utf-8")
    complete = tmp_path / "complete.xml"
    complete.write_text(
        '<testsuite><testcase classname="tests.test_a" name="t1" file="tests/test_a.py"/>'
        '<testcase classname="tests.test_a" name="t2" file="tests/test_a.py"/></testsuite>',
        encoding="utf-8",
    )
    assert module.verify_junit([complete], manifest) == []
    short = tmp_path / "short.xml"
    short.write_text(
        '<testsuite><testcase classname="tests.test_a" name="t1" file="tests/test_a.py"/>'
        "</testsuite>",
        encoding="utf-8",
    )
    problems = module.verify_junit([short], manifest)
    assert any("shortfall" in problem for problem in problems), problems


def test_every_shard_count_literal_in_the_workflow_matches_the_constant() -> None:
    module = _shard_module()
    workflow = WORKFLOW.read_text(encoding="utf-8")
    counts = {int(value) for value in re.findall(r"--of (\d+)", workflow)}
    assert counts == {module.SHARD_COUNT}, counts
    for job in ("backend", "backend-sqlite"):
        assert _jobs()[job]["strategy"]["matrix"]["shard"] == list(
            range(1, module.SHARD_COUNT + 1)
        ), job


def test_the_gate_guards_map_every_dependency_into_their_env() -> None:
    jobs = _jobs()
    guards = {
        POSTGRES_GATE: {"SHARDS": "backend", "CHECKS": POSTGRES_CHECKS},
        SQLITE_GATE: {"SHARDS": "backend-sqlite", "CHECKS": SQLITE_CHECKS},
    }
    for gate, mapping in guards.items():
        guard = _step(gate, jobs[gate]["steps"][0]["name"])
        env = guard["env"]
        assert set(env) == set(mapping), (gate, env)
        assert _needs(jobs[gate]) == set(mapping.values()), gate
        for key, job in mapping.items():
            assert env[key] == f"${{{{ needs.{job}.result }}}}", (gate, key, env[key])
