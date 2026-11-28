#!/usr/bin/env python3
"""Classify a diff against the committed backend-read and frontend path sets.

Plan 227 T4. This classifier exists for a deferred decision: it is **not**
wired into any workflow, and the merge gate always runs the full suite. Its
job is to report which path classes a diff touches:

* ``backend`` — the backend-read set: any change here can affect backend tests.
* ``frontend`` — the frontend set, including the assistant-ui pin files.
* ``docs`` — documentation paths.
* ``infra`` — workflows, packaging, docker, scripts and dependency pins.
* ``unknown`` — paths no set claims; they fail closed and count as backend.

The backend-read set is derived from the path literals ``backend/tests``
actually reads, not from assumption: ``test_docs_claims`` reads ``README.md``,
``frontend/src/App.tsx`` and ``frontend/src/config/features.json``,
``test_product_capabilities`` reads ``docs/capabilities.json``, and
``test_no_private_integration_mentions`` scans every tracked file. Because of
that last one no non-empty diff is provably backend-disjoint, so
``skippable_backend`` is always false and the mapping carries
``skippable_reason``.

Usage::

    python3 scripts/changed-paths.py --base origin/main
    python3 scripts/changed-paths.py --base HEAD~1 --json
    python3 scripts/changed-paths.py --diff-file /tmp/paths.txt
    python3 scripts/changed-paths.py --check
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_BACKEND_READ = (
    "backend/",
    "contracts/",
    "docs/",
    "README.md",
    "frontend/",
    "scripts/",
    "docker/",
    "packaging/",
    ".github/",
    "pyproject.toml",
    "uv.lock",
)
REQUIRED_FRONTEND = (
    "frontend/",
    "frontend/package.json",
    "frontend/package-lock.json",
)
BACKEND_READ_PATHS = REQUIRED_BACKEND_READ
FRONTEND_PATHS = REQUIRED_FRONTEND
DOCS_PATHS = (
    "docs/",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "AGENTS.md",
    "LICENSE",
)
INFRA_PATHS = (
    "docker/",
    "packaging/",
    ".github/",
    "scripts/",
    "pyproject.toml",
    "uv.lock",
)
REPO_WIDE_SCANNER_TESTS = ("tests/test_no_private_integration_mentions.py",)


def normalize(path: str) -> str:
    """Return a repo-relative path with forward slashes and no ``./`` prefix.

    Args:
        path: a path as printed by git or typed on the command line.

    Returns:
        The normalized path.
    """
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def matches_pattern(path: str, patterns: Iterable[str]) -> bool:
    """Return whether ``path`` is an exact pattern or below a pattern ending in ``/``.

    Args:
        path: normalized repo-relative path.
        patterns: exact file names and directory prefixes.

    Returns:
        True when a pattern claims the path.
    """
    for pattern in patterns:
        if path == pattern:
            return True
        if pattern.endswith("/") and path.startswith(pattern):
            return True
    return False


def missing_required_paths(required: Iterable[str], actual: Iterable[str]) -> list[str]:
    """Return the required entries absent from a committed path set.

    Args:
        required: the minimum contract for the set.
        actual: the committed set being checked.

    Returns:
        Missing entries in contract order (empty when the set is complete).
    """
    actual_set = set(actual)
    return [path for path in required if path not in actual_set]


def classify_paths(
    paths: Iterable[str],
    backend_read: Iterable[str] = BACKEND_READ_PATHS,
    frontend: Iterable[str] = FRONTEND_PATHS,
    docs: Iterable[str] = DOCS_PATHS,
    infra: Iterable[str] = INFRA_PATHS,
) -> dict[str, object]:
    """Classify a diff into backend/frontend/docs/infra and an unknown bucket.

    An unknown path cannot be proven disjoint from backend behaviour, so it
    also sets ``backend`` (fail closed). ``skippable_backend`` is always
    false: ``tests/test_no_private_integration_mentions.py`` scans **every
    tracked file**, so no non-empty diff is provably backend-disjoint. The
    reason is reported instead of a certification the suite cannot back.

    Args:
        paths: changed repo-relative paths.
        backend_read: the backend-read set (overridable for self-tests).
        frontend: the frontend set.
        docs: documentation paths.
        infra: infrastructure paths.

    Returns:
        A mapping with ``backend``, ``frontend``, ``docs``, ``infra``,
        ``unknown`` (the unclaimed paths), ``backend_read_hits``,
        ``has_unknown``, ``skippable_backend`` and ``skippable_reason``.
    """
    normalized = [normalize(path) for path in paths if normalize(path)]
    backend_read_hits = [path for path in normalized if matches_pattern(path, backend_read)]
    unknown = [
        path
        for path in normalized
        if not any(
            matches_pattern(path, patterns) for patterns in (backend_read, frontend, docs, infra)
        )
    ]
    reason = (
        "the diff is empty; there is nothing to skip"
        if not normalized
        else (
            f"{REPO_WIDE_SCANNER_TESTS[0]} scans every tracked file, so no "
            "non-empty diff is provably backend-disjoint"
        )
    )
    return {
        "backend": bool(backend_read_hits or unknown),
        "backend_read_hits": backend_read_hits,
        "frontend": any(matches_pattern(path, frontend) for path in normalized),
        "docs": any(matches_pattern(path, docs) for path in normalized),
        "infra": any(matches_pattern(path, infra) for path in normalized),
        "unknown": unknown,
        "has_unknown": bool(unknown),
        "skippable_backend": False,
        "skippable_reason": reason,
    }


def git_changed_paths(base: str) -> list[str]:
    """Return the committed paths changed between ``base`` and ``HEAD``.

    Args:
        base: a commit, branch or tag; the diff is three-dot (merge base) merged
            with the names in ``base...HEAD``.

    Returns:
        Sorted unique repo-relative paths.

    Raises:
        SystemExit: When git cannot resolve the base or run the diff.
    """
    completed = subprocess.run(
        ["git", "diff", "--name-only", "-z", f"{base}...HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"changed-paths: git diff failed for {base!r}: {message}")
    paths = [path for path in completed.stdout.decode("utf-8", "replace").split("\0") if path]
    return sorted(set(paths))


def read_diff_file(path: Path) -> list[str]:
    """Read a synthetic diff, one path per line.

    Args:
        path: newline-separated path list.

    Returns:
        Sorted unique normalized paths.

    Raises:
        SystemExit: When the file is unreadable.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"changed-paths: cannot read diff file {path}: {exc}") from exc
    return sorted({normalize(line) for line in lines if normalize(line)})


def _print_human(result: dict[str, object]) -> None:
    """Print the classification as short lines.

    Args:
        result: the mapping returned by :func:`classify_paths`.
    """
    print(f"backend: {'yes' if result['backend'] else 'no'}")
    print(f"frontend: {'yes' if result['frontend'] else 'no'}")
    print(f"docs: {'yes' if result['docs'] else 'no'}")
    print(f"infra: {'yes' if result['infra'] else 'no'}")
    unknown = result["unknown"]
    if unknown:
        print(f"unknown (counted as backend): {', '.join(unknown)}")
    else:
        print("unknown: none")
    skip = "yes" if result["skippable_backend"] else "no"
    print(f"backend jobs skippable: {skip}")
    print(f"skippable why: {result['skippable_reason']}")


def _self_check() -> None:
    """Prove the sets, the classes and the honest skip answer.

    Raises:
        AssertionError: When a class is wrong or the tool certifies a skip.
    """
    cases: list[tuple[list[str], dict[str, bool]]] = [
        (["backend/app/x.py"], {"backend": True, "frontend": False, "docs": False}),
        (["frontend/src/App.tsx"], {"backend": True, "frontend": True}),
        (["frontend/package-lock.json"], {"backend": True, "frontend": True}),
        (["docs/user/guide.md"], {"backend": True, "docs": True}),
        (["docs/dev/testing.md"], {"backend": True, "docs": True}),
        (["docs/deploy.md"], {"backend": True, "docs": True}),
        (["README.md"], {"backend": True, "docs": True}),
        (["CHANGELOG.md"], {"backend": False, "docs": True}),
        (["scripts/run-tests.sh"], {"backend": True, "infra": True}),
        (["docker/Dockerfile"], {"backend": True, "infra": True}),
        (["packaging/spec.py"], {"backend": True, "infra": True}),
        (["pyproject.toml"], {"backend": True, "infra": True}),
        (["uv.lock"], {"backend": True, "infra": True}),
        ([".github/workflows/ci.yml"], {"backend": True, "infra": True}),
        (["unknown/file.txt"], {"backend": True, "has_unknown": True}),
        ([], {"backend": False, "has_unknown": False}),
    ]
    for paths, expected in cases:
        result = classify_paths(paths)
        for key, value in expected.items():
            assert result[key] == value, f"self-check: {paths} -> {key}={result[key]!r}"
        assert result["skippable_backend"] is False, f"self-check: {paths} certified a skip"
    assert "every tracked file" in classify_paths(["backend/app/x.py"])["skippable_reason"]
    reduced = tuple(path for path in BACKEND_READ_PATHS if path != "backend/")
    assert missing_required_paths(REQUIRED_BACKEND_READ, reduced) == ["backend/"]
    print("self-check ok")


def main(argv: list[str] | None = None) -> int:
    """Classify a diff or run the built-in self-check.

    Args:
        argv: command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="base ref for the committed diff (default: origin/main)",
    )
    parser.add_argument("--diff-file", type=Path, help="read synthetic paths instead of git")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--check", action="store_true", help="run the built-in self-check")
    args = parser.parse_args(argv)

    if args.check:
        _self_check()
        return 0
    paths = read_diff_file(args.diff_file) if args.diff_file else git_changed_paths(args.base)
    result = classify_paths(paths)
    payload = {"base": None if args.diff_file else args.base, "paths": paths, **result}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{len(paths)} changed path(s)")
        _print_human(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
