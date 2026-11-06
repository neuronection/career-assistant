#!/usr/bin/env python3
"""Mypy ratchet gate: a package error budget that may only ratchet DOWN.

Plan 124.2. Mypy's ``files`` list in ``backend/pyproject.toml`` holds the
packages that are fully clean (they join and never leave). Packages still
being cleaned are pinned in ``[tool.career-mypy-ratchet]`` with their
measured error count — the wall:

* more errors than pinned → regression, the gate fails;
* fewer errors than pinned → the peg must move down in the same commit,
  otherwise the wall silently tolerates new debt.

Usage::

    cd backend && uv run python ../scripts/check-mypy-ratchet.py
    uv run python ../scripts/check-mypy-ratchet.py --update   # lower pegs only
    python scripts/check-mypy-ratchet.py --self-test
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
PYPROJECT = BACKEND / "pyproject.toml"
SUMMARY = re.compile(r"^Found (\d+) errors? in \d+ files? ")
SUCCESS = re.compile(r"^Success: no issues found in \d+ source files?\b")


def load_pegs(pyproject: Path) -> dict[str, int]:
    """Read the pinned per-package error counts.

    Args:
        pyproject: path to ``backend/pyproject.toml``.

    Returns:
        Mapping of package path to its pinned error count.
    """
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    section = data.get("tool", {}).get("career-mypy-ratchet", {})
    packages = section.get("packages", {})
    if not isinstance(packages, dict):
        raise SystemExit(f"{pyproject}: [tool.career-mypy-ratchet].packages must be a table")
    return {str(k): int(v) for k, v in packages.items()}


def parse_count(output: str) -> int:
    """Extract the mypy error count from its summary line.

    Args:
        output: combined mypy stdout/stderr.

    Returns:
        The number of reported errors (0 on a clean run).
    """
    for line in reversed(output.splitlines()):
        match = SUMMARY.match(line.strip())
        if match:
            return int(match.group(1))
        if SUCCESS.match(line.strip()):
            return 0
    raise SystemExit(f"could not find a mypy summary line in:\n{output}")


def count_errors(package: str) -> int:
    """Run mypy for one package and return its error count.

    Args:
        package: import path such as ``app/services``.

    Returns:
        Number of mypy errors reported for that package.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "mypy", package],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    return parse_count(completed.stdout + completed.stderr)


def evaluate(measured: dict[str, int], pegs: dict[str, int]) -> list[str]:
    """Compare measurements against the pegs.

    Args:
        measured: freshly counted errors per package.
        pegs: pinned counts per package.

    Returns:
        Human-readable failures (empty when the ratchet holds).
    """
    failures: list[str] = []
    for package, peg in pegs.items():
        count = measured.get(package)
        if count is None:
            failures.append(f"{package}: not measured")
        elif count > peg:
            failures.append(
                f"{package}: {count} errors > pinned {peg} — fix the new errors "
                f"(the peg may only move down)"
            )
        elif count < peg:
            failures.append(
                f"{package}: {count} errors < pinned {peg} — ratchet the peg down "
                f"in [tool.career-mypy-ratchet] (run with --update)"
            )
    for package in sorted(set(measured) - set(pegs)):
        failures.append(f"{package}: measured but not pinned")
    return failures


def update_pegs(measured: dict[str, int], pegs: dict[str, int]) -> bool:
    """Lower stale pegs in ``pyproject.toml`` (never raise one).

    Args:
        measured: freshly counted errors per package.
        pegs: pinned counts per package.

    Returns:
        True when the file was rewritten.
    """
    stale = {
        package: count
        for package, count in measured.items()
        if package in pegs and count < pegs[package]
    }
    if not stale:
        return False
    text = PYPROJECT.read_text(encoding="utf-8")
    for package, count in stale.items():
        text = re.sub(
            rf'("{re.escape(package)}"\s*=\s*){pegs[package]}\b',
            rf"\g<1>{count}",
            text,
        )
    PYPROJECT.write_text(text, encoding="utf-8")
    for package, count in stale.items():
        print(f"ratcheted {package}: {pegs[package]} -> {count}")
    return True


def _self_test() -> int:
    cases: list[tuple[str, bool]] = []
    regression = "Found 12 errors in 3 files (checked 4 source files)"
    cases.append(("parse regression", parse_count(regression) == 12))
    cases.append(("parse clean", parse_count("Success: no issues found in 7 source files") == 0))
    cases.append(("equal peg holds", not evaluate({"a": 5}, {"a": 5})))
    cases.append(("increase blocks", bool(evaluate({"a": 6}, {"a": 5}))))
    cases.append(("decrease asks for ratchet", bool(evaluate({"a": 4}, {"a": 5}))))
    cases.append(("unmeasured blocks", bool(evaluate({}, {"a": 0}))))
    cases.append(("unpinned blocks", bool(evaluate({"b": 1}, {"a": 0}))))
    failures = [name for name, ok in cases if not ok]
    for name, ok in cases:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"self-test failures: {failures}", file=sys.stderr)
        return 1
    print(f"self-test: {len(cases)} cases passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the ratchet gate.

    Args:
        argv: CLI arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="lower stale pegs in pyproject.toml")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    pegs = load_pegs(PYPROJECT)
    measured = {package: count_errors(package) for package in pegs}
    for package, count in measured.items():
        print(f"{package}: {count} errors (pinned {pegs[package]})")
    if args.update and update_pegs(measured, pegs):
        pegs = load_pegs(PYPROJECT)
    failures = evaluate(measured, pegs)
    if failures:
        for failure in failures:
            print(f"BLOCKED {failure}", file=sys.stderr)
        return 1
    print("mypy ratchet: holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
