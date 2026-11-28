#!/usr/bin/env python3
"""Refresh the shard-balance duration table from a real pytest JUnit XML.

Plan 227 T1. Parses the JUnit report of one full lane run, sums each test
case's ``time`` per file and writes ``backend/tests/ci_durations.json``. The
table is a balance hint only: ``scripts/check-test-shards.py`` falls back to
the median for files it does not name, so a stale table degrades balance but
never correctness.

Usage::

    python3 scripts/refresh-test-durations.py /tmp/junit.xml
    python3 scripts/refresh-test-durations.py /tmp/junit.xml --out backend/tests/ci_durations.json
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "backend" / "tests" / "ci_durations.json"
COMMENT = (
    "Balance hint only, never a correctness input: per-file seconds summed from a real "
    "lane's JUnit XML. Refresh with scripts/refresh-test-durations.py <junit.xml>. A stale "
    "table is tolerated — files it does not name fall back to the median duration."
)


def case_file(case: ET.Element) -> str | None:
    """Resolve the test file of one JUnit case.

    Args:
        case: a ``testcase`` element.

    Returns:
        The forward-slash path relative to ``backend/`` (``tests/test_x.py``),
        or ``None`` when the report cannot name it.
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


def collect_durations(path: Path) -> dict[str, float]:
    """Sum every test case's duration per file.

    Args:
        path: JUnit XML path.

    Returns:
        Mapping of ``tests/...`` path to seconds, rounded to milliseconds.

    Raises:
        SystemExit: When the report is unreadable or contains no test cases.
    """
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise SystemExit(f"cannot parse JUnit XML {path}: {exc}") from exc
    totals: dict[str, float] = {}
    for case in root.iter("testcase"):
        file = case_file(case)
        if file is None or not file.startswith("tests/"):
            continue
        try:
            seconds = float(case.get("time", "0"))
        except ValueError:
            seconds = 0.0
        totals[file] = totals.get(file, 0.0) + seconds
    if not totals:
        raise SystemExit(f"{path}: no per-file test cases found")
    return {file: round(seconds, 3) for file, seconds in sorted(totals.items())}


def main(argv: list[str] | None = None) -> int:
    """Parse a JUnit XML and write the duration table.

    Args:
        argv: command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("junit", type=Path, help="JUnit XML from a full lane run")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help=f"duration table (default: {DEFAULT_OUT})"
    )
    args = parser.parse_args(argv)
    durations = collect_durations(args.junit)
    payload = {"$comment": COMMENT, **durations}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(durations)} file durations to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
