#!/usr/bin/env python3
"""Deterministic, duration-aware shard assignment for the backend test suite.

Plan 227 T1. The manifest is the file list pytest collects (one path per
line, relative to ``backend/``); the duration table is a balance hint only,
never a correctness input. Correctness comes from the manifest plus
``--check``: every collected file is assigned exactly once, no duplicates,
no empty shard.

Usage::

    python3 scripts/check-test-shards.py --files /tmp/files.txt --of 2 \
        --shard 1 --out /tmp/shard.txt
    python3 scripts/check-test-shards.py --check --files /tmp/files.txt --of 2
    python3 scripts/check-test-shards.py --merge-observations shard-1.json shard-2.json
    python3 scripts/check-test-shards.py --merge-observations --lane "" shard-1.json shard-2.json
    python3 scripts/check-test-shards.py --verify-junit junit-1.xml junit-2.xml \
        --files /tmp/nodes.txt
    python3 scripts/check-test-shards.py --self-test
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DURATIONS = ROOT / "backend" / "tests" / "ci_durations.json"
DEFAULT_OBSERVATIONS = ROOT / "backend" / "tests" / "_xdist" / "skip_observations.json"
PARALLEL_LANE = "not serial"
SHARD_COUNT = 2


def load_durations(path: Path) -> dict[str, float]:
    """Read the per-file duration table (seconds), ignoring ``$``-prefixed metadata.

    Args:
        path: path to ``backend/tests/ci_durations.json``.

    Returns:
        Mapping of manifest-relative file path to measured seconds.

    Raises:
        SystemExit: When the table is unreadable or carries a non-numeric value.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read duration table {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"{path}: expected a JSON object")
    durations: dict[str, float] = {}
    for key, value in raw.items():
        if key.startswith("$"):
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise SystemExit(f"{path}: {key!r} must be a non-negative number")
        durations[str(key)] = float(value)
    return durations


def load_manifest(path: Path) -> list[str]:
    """Read the collected file list, one path per line.

    Args:
        path: manifest path produced by ``pytest --collect-only``.

    Returns:
        The file paths in file order (duplicates are preserved so ``--check`` sees them).

    Raises:
        SystemExit: When the manifest is missing or empty.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"cannot read manifest {path}: {exc}") from exc
    files = [line.strip() for line in lines if line.strip()]
    if not files:
        raise SystemExit(f"{path}: manifest is empty")
    return files


def file_weight(path: str, durations: dict[str, float], default: float) -> float:
    """Weight of one file: its measured seconds, or the median when absent.

    Args:
        path: manifest-relative file path.
        durations: measured per-file seconds.
        default: fallback weight for a file with no measurement.

    Returns:
        The file's weight in seconds.
    """
    return durations.get(path, default)


def assign_shards(
    files: Iterable[str], durations: dict[str, float], shard_count: int
) -> list[list[str]]:
    """Assign files greedily by longest-processing-time, deterministically.

    Files are ordered by descending weight (ties broken by path) and each goes
    to the currently lightest shard (ties broken by shard index), so the result
    does not depend on manifest order.

    Args:
        files: manifest-relative file paths.
        durations: measured per-file seconds.
        shard_count: number of shards to fill (>= 1).

    Returns:
        One path-sorted file list per shard.

    Raises:
        SystemExit: When ``shard_count`` is not positive.
    """
    if shard_count < 1:
        raise SystemExit("--of must be at least 1")
    default = statistics.median(durations.values()) if durations else 0.0
    ordered = sorted(files, key=lambda path: (-file_weight(path, durations, default), path))
    buckets: list[list[str]] = [[] for _ in range(shard_count)]
    loads = [0.0] * shard_count
    for path in ordered:
        index = min(range(shard_count), key=lambda i: (loads[i], i))
        buckets[index].append(path)
        loads[index] += file_weight(path, durations, default)
    return [sorted(bucket) for bucket in buckets]


def shard_estimates(buckets: list[list[str]], durations: dict[str, float]) -> list[float]:
    """Estimated wall per shard from the duration table.

    Args:
        buckets: per-shard file lists.
        durations: measured per-file seconds.

    Returns:
        One estimated-seconds total per shard.
    """
    default = statistics.median(durations.values()) if durations else 0.0
    return [
        round(sum(file_weight(path, durations, default) for path in bucket), 3)
        for bucket in buckets
    ]


def validate_assignment(buckets: list[list[str]], files: list[str]) -> list[str]:
    """Prove the assignment covers the manifest exactly once with no empty shard.

    Args:
        buckets: per-shard file lists.
        files: the manifest the assignment must cover.

    Returns:
        Human-readable violations (empty when the partition is sound).
    """
    problems: list[str] = []
    seen: dict[str, int] = {}
    for bucket in buckets:
        for path in bucket:
            seen[path] = seen.get(path, 0) + 1
    duplicates = sorted(path for path, count in seen.items() if count > 1)
    if duplicates:
        problems.append(f"duplicate file assignments: {', '.join(duplicates[:10])}")
    missing = sorted(set(files) - set(seen))
    if missing:
        problems.append(f"files never assigned: {', '.join(missing[:10])}")
    unexpected = sorted(set(seen) - set(files))
    if unexpected:
        problems.append(f"files assigned but not in the manifest: {', '.join(unexpected[:10])}")
    empty = [str(index + 1) for index, bucket in enumerate(buckets) if not bucket]
    if empty:
        problems.append(f"empty shards: {', '.join(empty)}")
    return problems


def merge_observations(
    fragments: list[Path], out: Path, lane: str = PARALLEL_LANE
) -> dict[str, dict[str, str]]:
    """Merge per-shard skip-observation fragments into one journal lane.

    Each fragment is a ``skip_observations.json`` written by a shard's pytest
    session; the requested lane is unioned so the final check judges every
    shard's skips, not one shard's. The SQLite shards write under ``not
    serial``; the Postgres shards run without a selector and write under the
    empty lane.

    Args:
        fragments: fragment paths, each carrying the requested lane.
        out: journal path to write.
        lane: the exact ``-m`` expression the fragments recorded (default
            ``not serial``).

    Returns:
        The merged journal.

    Raises:
        SystemExit: When a fragment is unreadable, malformed, missing the
            lane, or contradicts another fragment.
    """
    if not fragments:
        raise SystemExit("--merge-observations needs at least one fragment")
    merged: dict[str, str] = {}
    for fragment in fragments:
        try:
            data = json.loads(fragment.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"cannot read skip-observation fragment {fragment}: {exc}") from exc
        observed = data.get(lane) if isinstance(data, dict) else None
        if not isinstance(observed, dict):
            raise SystemExit(f"{fragment}: missing the {lane!r} observations")
        for nodeid, reason in observed.items():
            if nodeid in merged and merged[nodeid] != reason:
                raise SystemExit(f"{fragment}: conflicting skip reason for {nodeid}")
            merged[nodeid] = str(reason)
    existing: dict[str, dict[str, str]] = {}
    if out.exists():
        try:
            loaded = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"cannot read existing journal {out}: {exc}") from exc
        if isinstance(loaded, dict):
            existing = {
                str(key): dict(observed)
                for key, observed in loaded.items()
                if isinstance(observed, dict)
            }
    prior = existing.get(lane, {})
    for nodeid, reason in merged.items():
        if nodeid in prior and prior[nodeid] != reason:
            raise SystemExit(f"{out}: conflicting skip reason for {nodeid}")
    existing[lane] = {**prior, **merged}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return existing


def collected_node_counts(path: Path) -> dict[str, int]:
    """Count collected node ids per file.

    Args:
        path: a manifest of ``file::name`` lines, one per collected node.

    Returns:
        Mapping of manifest-relative file path to collected node count.

    Raises:
        SystemExit: When the manifest is unreadable or carries no node ids.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"cannot read node manifest {path}: {exc}") from exc
    counts: dict[str, int] = {}
    for line in lines:
        entry = line.strip()
        if "::" not in entry:
            continue
        file = entry.split("::", 1)[0]
        counts[file] = counts.get(file, 0) + 1
    if not counts:
        raise SystemExit(f"{path}: no 'file::name' node ids found")
    return counts


def junit_case_file(case: ET.Element) -> str | None:
    """Resolve the test file of one JUnit case.

    Args:
        case: a ``testcase`` element.

    Returns:
        The forward-slash path relative to ``backend/``, or None when the
        report cannot name it.
    """
    explicit = case.get("file")
    if explicit:
        return explicit.replace("\\", "/").removeprefix("./")
    classname = case.get("classname")
    if not classname:
        return None
    parts = classname.split(".")
    while parts and parts[-1][:1].isupper():
        parts.pop()
    if not parts:
        return None
    return "/".join(parts) + ".py"


def junit_file_counts(paths: Iterable[Path]) -> tuple[dict[str, int], int]:
    """Count executed JUnit cases per file across every shard report.

    Args:
        paths: the shard JUnit XML files.

    Returns:
        Mapping of file path to executed cases (skipped cases included), and
        the number of cases the reports could not attribute to a file.

    Raises:
        SystemExit: When a report is unreadable or contains no test cases.
    """
    counts: dict[str, int] = {}
    unattributed = 0
    total = 0
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as exc:
            raise SystemExit(f"cannot parse JUnit XML {path}: {exc}") from exc
        for case in root.iter("testcase"):
            total += 1
            file = junit_case_file(case)
            if file is None:
                unattributed += 1
                continue
            counts[file] = counts.get(file, 0) + 1
    if not total:
        raise SystemExit("the JUnit reports contain no test cases")
    return counts, unattributed


def verify_junit(junit_paths: Iterable[Path], manifest_path: Path) -> list[str]:
    """Prove the shard JUnit union executed every collected node exactly once.

    JUnit counts skipped cases too, so a deselected or lost node is a
    shortfall rather than a silent gap. A node executed twice (a duplicated
    shard assignment) is an overrun.

    Args:
        junit_paths: the shard (and, on SQLite, the serial lane) JUnit XML files.
        manifest_path: the whole-tree ``file::name`` collection.

    Returns:
        Human-readable violations (empty when the union matches the collection).
    """
    collected = collected_node_counts(manifest_path)
    executed, unattributed = junit_file_counts(junit_paths)
    problems: list[str] = []
    if unattributed:
        problems.append(f"{unattributed} executed case(s) name no test file")
    for file, expected in sorted(collected.items()):
        actual = executed.get(file, 0)
        if actual < expected:
            problems.append(f"{file}: {actual} executed < {expected} collected (shortfall)")
        elif actual > expected:
            problems.append(f"{file}: {actual} executed > {expected} collected (doubled?)")
    for file in sorted(set(executed) - set(collected)):
        problems.append(f"{file}: executed but not collected")
    return problems


def _self_test() -> None:
    """Prove the assignment balances, falls back, stays deterministic and fails closed."""
    weights = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
    durations = {f"tests/test_{index}.py": weight for index, weight in enumerate(weights)}
    files = sorted(durations)
    buckets = assign_shards(files, durations, 2)
    loads = shard_estimates(buckets, durations)
    assert all(buckets), "self-test: a shard is empty"
    assert max(loads) - min(loads) <= 2, f"self-test: LPT did not balance ({loads})"
    assert sum(len(bucket) for bucket in buckets) == len(files)

    measured = {"tests/a.py": 10.0, "tests/b.py": 10.0}
    fallback = assign_shards(["tests/a.py", "tests/b.py", "tests/c.py", "tests/d.py"], measured, 2)
    fallback_loads = shard_estimates(fallback, measured)
    assert fallback_loads == [20.0, 20.0], f"self-test: median fallback wrong ({fallback_loads})"

    assert assign_shards(list(reversed(files)), durations, 2) == buckets, (
        "self-test: assignment depends on input order"
    )
    assert assign_shards(files, durations, 2) == buckets, "self-test: assignment is not repeatable"

    three = ["tests/a.py", "tests/b.py", "tests/c.py"]
    duplicate = [["tests/a.py", "tests/b.py"], ["tests/b.py", "tests/c.py"]]
    assert validate_assignment(duplicate, three), "self-test: duplicate assignment passed"
    assert validate_assignment([["tests/a.py"], []], ["tests/a.py"]), (
        "self-test: empty shard passed"
    )
    assert not validate_assignment(
        [["tests/a.py"], ["tests/b.py"]], ["tests/a.py", "tests/b.py"]
    ), "self-test: sound partition rejected"

    with tempfile.TemporaryDirectory() as tmp:
        first = Path(tmp) / "shard-1.json"
        second = Path(tmp) / "shard-2.json"
        journal = Path(tmp) / "skip_observations.json"
        first.write_text(
            json.dumps({PARALLEL_LANE: {"tests/a.py::t": "skip one"}}), encoding="utf-8"
        )
        second.write_text(
            json.dumps({PARALLEL_LANE: {"tests/b.py::t": "skip two"}}), encoding="utf-8"
        )
        merged = merge_observations([first, second], journal)
        assert set(merged[PARALLEL_LANE]) == {"tests/a.py::t", "tests/b.py::t"}, (
            "self-test: journal merge lost a shard"
        )
        journal.write_text(
            json.dumps({PARALLEL_LANE: {"tests/a.py::t": "other"}}), encoding="utf-8"
        )
        try:
            merge_observations([first], journal)
        except SystemExit:
            pass
        else:
            raise AssertionError("self-test: conflicting skip reason passed")

        postgres_fragment = Path(tmp) / "postgres-shard.json"
        postgres_journal = Path(tmp) / "postgres-journal.json"
        postgres_fragment.write_text(
            json.dumps({"": {"tests/c.py::t": "no engine"}}), encoding="utf-8"
        )
        merged_postgres = merge_observations([postgres_fragment], postgres_journal, lane="")
        assert merged_postgres[""] == {"tests/c.py::t": "no engine"}, (
            "self-test: the empty lane was not merged"
        )
        try:
            merge_observations([postgres_fragment], postgres_journal)
        except SystemExit:
            pass
        else:
            raise AssertionError("self-test: a fragment missing the requested lane passed")

        manifest = Path(tmp) / "nodes.txt"
        manifest.write_text(
            "tests/a.py::t_one\ntests/a.py::t_two\ntests/b.py::t_three\n", encoding="utf-8"
        )
        junit_one = Path(tmp) / "junit-1.xml"
        junit_two = Path(tmp) / "junit-2.xml"
        junit_one.write_text(
            '<testsuite><testcase classname="tests.test_a" name="t_one" '
            'file="tests/a.py"/><testcase classname="tests.test_a" name="t_two" '
            'file="tests/a.py"/></testsuite>',
            encoding="utf-8",
        )
        junit_two.write_text(
            '<testsuite><testcase classname="tests.test_b" name="t_three" '
            'file="tests/b.py"/></testsuite>',
            encoding="utf-8",
        )
        assert verify_junit([junit_one, junit_two], manifest) == [], (
            "self-test: a complete JUnit union failed"
        )
        assert verify_junit([junit_one], manifest) == [
            "tests/b.py: 0 executed < 1 collected (shortfall)"
        ], "self-test: a shortfall passed"
        doubled = Path(tmp) / "junit-doubled.xml"
        doubled.write_text(
            '<testsuite><testcase classname="tests.test_a" name="t_one" '
            'file="tests/a.py"/></testsuite>',
            encoding="utf-8",
        )
        problems = verify_junit([junit_one, doubled], manifest)
        assert any("doubled" in problem for problem in problems), "self-test: a doubled node passed"

    print("self-test ok")


def main(argv: list[str] | None = None) -> int:
    """Run the shard selector, the assignment check, or the journal merge.

    Args:
        argv: command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--files", type=Path, help="collected file manifest, one path per line")
    parser.add_argument(
        "--of", dest="shard_count", type=int, default=SHARD_COUNT, help="shard count (default 2)"
    )
    parser.add_argument("--shard", type=int, help="1-based shard to print")
    parser.add_argument("--out", type=Path, help="write the file list here instead of stdout")
    parser.add_argument("--check", action="store_true", help="assert the assignment is a partition")
    parser.add_argument("--self-test", action="store_true", help="run the built-in cases")
    parser.add_argument(
        "--merge-observations",
        action="store_true",
        help="merge the FRAGMENT skip-observation journals",
    )
    parser.add_argument(
        "fragments",
        nargs="*",
        type=Path,
        metavar="FRAGMENT",
        help="shard skip-observation fragments (with --merge-observations)",
    )
    parser.add_argument(
        "--lane",
        default=PARALLEL_LANE,
        help=f"the -m expression the shard fragments recorded (default: {PARALLEL_LANE!r})",
    )
    parser.add_argument(
        "--verify-junit",
        nargs="+",
        type=Path,
        metavar="JUNIT",
        help="prove these shard JUnit reports executed every node in --files",
    )
    parser.add_argument("--durations", type=Path, default=DEFAULT_DURATIONS, help="duration table")
    args = parser.parse_args(argv)

    if args.self_test:
        _self_test()
        return 0
    if args.verify_junit:
        if not args.files:
            parser.error("--verify-junit needs --files (the whole-tree node manifest)")
        problems = verify_junit(args.verify_junit, args.files)
        if problems:
            for problem in problems:
                print(f"FAIL: {problem}", file=sys.stderr)
            return 1
        print(f"JUnit union covers every node in {args.files}")
        return 0
    if args.merge_observations:
        if args.files:
            parser.error("--merge-observations does not take --files")
        if not args.fragments:
            parser.error("--merge-observations needs at least one FRAGMENT")
        target = args.out or DEFAULT_OBSERVATIONS
        merge_observations(args.fragments, target, lane=args.lane)
        print(
            f"merged {len(args.fragments)} skip-observation fragments "
            f"(lane {args.lane!r}) into {target}"
        )
        return 0
    if args.fragments:
        parser.error("FRAGMENT arguments are only valid with --merge-observations")
    if not args.files:
        parser.error("--files is required outside --self-test/--merge-observations")
    durations = load_durations(args.durations)
    files = load_manifest(args.files)
    buckets = assign_shards(files, durations, args.shard_count)
    estimates = shard_estimates(buckets, durations)
    if args.check:
        problems = validate_assignment(buckets, files)
        for index, (bucket, estimate) in enumerate(zip(buckets, estimates, strict=True), start=1):
            print(f"shard {index}/{args.shard_count}: {len(bucket)} files, ~{estimate:.1f} s")
        if problems:
            for problem in problems:
                print(f"FAIL: {problem}", file=sys.stderr)
            return 1
        print(f"assignment covers {len(files)} files exactly once")
        return 0
    if args.shard is None:
        parser.error("--shard is required (or pass --check)")
    if not 1 <= args.shard <= args.shard_count:
        parser.error(f"--shard must be between 1 and {args.shard_count}")
    selected = buckets[args.shard - 1]
    if not selected:
        print(f"shard {args.shard}/{args.shard_count} is empty", file=sys.stderr)
        return 1
    text = "\n".join(selected) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(
            f"shard {args.shard}/{args.shard_count}: {len(selected)} files, "
            f"~{estimates[args.shard - 1]:.1f} s -> {args.out}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
