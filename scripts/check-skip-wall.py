#!/usr/bin/env python3
"""Assert every ``when: always`` allowlisted skip fired in a merged journal.

Plan 227 M1. The Postgres lane is sharded, so it has no whole-tree pytest
session to judge the skip wall's completeness half. Its shards write their
observations under the empty ``-m`` lane; ``check-test-shards.py
--merge-observations --lane ""`` unions them, and this script applies the
same allowlist and wording the pytest plugin uses. The SQLite gate keeps
judging its own serial lane; this script gives the Postgres gate the same
completeness check.

Usage::

    python3 scripts/check-skip-wall.py --dialect postgres --lane ""
    python3 scripts/check-skip-wall.py --dialect sqlite --lane "not serial" \
        --journal /tmp/skip_observations.json
    python3 scripts/check-skip-wall.py --self-test
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ALLOWLIST = ROOT / "backend" / "tests" / "skip_allowlist.json"
DEFAULT_JOURNAL = ROOT / "backend" / "tests" / "_xdist" / "skip_observations.json"
SKIP_WALL = ROOT / "backend" / "tests" / "skip_wall.py"


def _skip_wall() -> ModuleType:
    """Import ``backend/tests/skip_wall.py``, the pytest plugin's implementation.

    Returns:
        The shared pure skip-wall module.
    """
    spec = importlib.util.spec_from_file_location("skip_wall", SKIP_WALL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_journal(path: Path) -> dict[str, dict[str, str]]:
    """Read a merged skip-observation journal.

    Args:
        path: the journal written by ``check-test-shards.py``.

    Returns:
        Lane (the exact ``-m`` expression) to skipped node id and reason.

    Raises:
        SystemExit: When the journal is unreadable or not a lane mapping.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read skip-observation journal {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected a JSON object")
    return {
        str(lane): {str(nodeid): str(reason) for nodeid, reason in observed.items()}
        for lane, observed in data.items()
        if isinstance(observed, dict)
    }


def judge(
    journal: dict[str, dict[str, str]],
    lane: str,
    allowlist: list[dict[str, str]],
) -> list[str]:
    """Return the completeness problems for one lane's observations.

    Args:
        journal: lane to observations, as written by the shard merge.
        lane: the exact ``-m`` expression the shard lane ran under (empty for
            no selector).
        allowlist: the dialect's reviewed skip entries.

    Returns:
        Human-readable problems (empty when every ``when: always`` entry fired).
    """
    observed = journal.get(lane)
    if observed is None:
        return [f"no observations for lane {lane!r} — merge the shard fragments first"]
    return _skip_wall().missing_allowlisted_skip_problems(observed, allowlist)


def _report(problems: list[str]) -> None:
    """Print the wall's failure block in the pytest plugin's wording.

    Args:
        problems: the completeness problems to print.
    """
    print("skip wall FAILED — expected skip list drifted:", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    print(f"  update {DEFAULT_ALLOWLIST} (documented skips only)", file=sys.stderr)


def _self_test() -> None:
    """Prove the union judgement, the fail-closed lane, and the wildcard match.

    Raises:
        AssertionError: When a wrong answer is produced.
    """
    allowlist = [
        {"id": "tests/test_x.py::a", "reason_contains": "dialect", "when": "always"},
        {"id": "tests/test_x.py::b*", "reason_contains": "optional engine", "when": "always"},
        {"id": "tests/test_x.py::c", "reason_contains": "data", "when": "conditional"},
    ]
    fired = {
        "": {
            "tests/test_x.py::a": "dialect only",
            "tests/test_x.py::b_probe": "no optional engine here",
        }
    }
    assert judge(fired, "", allowlist) == [], "self-test: a complete union failed"
    dropped = {"": {"tests/test_x.py::a": "dialect only"}}
    assert judge(dropped, "", allowlist) == [
        "allowlisted skip did not fire: tests/test_x.py::b* (optional engine)"
    ], "self-test: a dropped always entry passed"
    assert judge({}, "", allowlist), "self-test: a missing lane passed"
    assert judge(fired, "not serial", allowlist), "self-test: the wrong lane passed"

    module = _skip_wall()
    assert module.unlisted_skip_problems({"tests/test_x.py::new": "surprise"}, allowlist), (
        "self-test: an unlisted skip passed"
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "journal.json"
        path.write_text(json.dumps(fired), encoding="utf-8")
        assert read_journal(path) == fired, "self-test: journal round-trip lost an observation"
        path.write_text("not json", encoding="utf-8")
        try:
            read_journal(path)
        except SystemExit:
            pass
        else:
            raise AssertionError("self-test: an unreadable journal passed")

    print("self-test ok")


def main(argv: list[str] | None = None) -> int:
    """Judge one lane's merged skip observations, or run the self-test.

    Args:
        argv: command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit status (1 when an always entry did not fire).
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dialect", choices=("postgres", "sqlite"), help="the lane's dialect")
    parser.add_argument(
        "--lane",
        default="",
        help="the exact -m expression the lane ran under (default: empty, i.e. no selector)",
    )
    parser.add_argument(
        "--journal", type=Path, default=DEFAULT_JOURNAL, help="merged skip-observation journal"
    )
    parser.add_argument(
        "--allowlist", type=Path, default=DEFAULT_ALLOWLIST, help="reviewed skip allowlist"
    )
    parser.add_argument("--self-test", action="store_true", help="run the built-in cases")
    args = parser.parse_args(argv)

    if args.self_test:
        _self_test()
        return 0
    if not args.dialect:
        parser.error("--dialect is required outside --self-test")
    allowlist = _skip_wall().load_allowlist(args.allowlist, args.dialect)
    problems = judge(read_journal(args.journal), args.lane, allowlist)
    if not problems:
        print(
            f"skip wall ok: every `when: always` {args.dialect} entry fired "
            f"(lane {args.lane!r}, journal {args.journal})"
        )
        return 0
    _report(problems)
    return 1


if __name__ == "__main__":
    sys.exit(main())
