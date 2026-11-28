#!/usr/bin/env python3
"""Select the backend tests affected by a diff (plan 227 T4).

Iteration only: CI and the merge gate always run the full suite. The selection
combines committed changes (``git diff <base>...HEAD``) with uncommitted and
untracked files (``git status --porcelain``), maps a changed ``backend/app``
module to the test files whose static imports name that module or any parent
package, adds changed test files themselves, and always keeps the always-run
set. A changed module with no importer warns and keeps only the always-run
set; a full-suite trigger prints its reason and selects every test file.

Usage::

    python3 scripts/changed-tests.py --base origin/main
    python3 scripts/changed-tests.py --base HEAD~1 --json
    python3 scripts/changed-tests.py --diff-file /tmp/paths.txt --paths-only
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
TESTS = BACKEND / "tests"

ALWAYS_RUN = (
    "tests/test_quality_gates.py",
    "tests/test_docs_claims.py",
    "tests/test_config_contract.py",
    "tests/test_test_harness.py",
    "tests/test_ci_shards.py",
    "tests/test_ci_selection.py",
    "tests/test_no_private_integration_mentions.py",
)
FULL_SUITE_DIRS = (
    "backend/alembic/",
    "contracts/",
    "docs/user/",
    "docs/dev/",
    "scripts/",
)
FULL_SUITE_FILES = (
    "backend/pyproject.toml",
    "uv.lock",
    "backend/tests/conftest.py",
    "backend/tests/seed_pack_fixture.py",
    ".github/workflows/ci.yml",
)


@dataclass(frozen=True)
class Selection:
    """The outcome of planning a changed-test run.

    Attributes:
        changed: normalized changed paths.
        selected: pytest targets, relative to ``backend/``.
        total_test_files: how many test modules the scan found.
        full_suite: whether a full-suite trigger matched.
        reason: one-line explanation of the selection.
        warnings: honest caveats (no importer, unparseable file, ...).
        missing_importers: changed app modules no test imports.
    """

    changed: tuple[str, ...]
    selected: tuple[str, ...]
    total_test_files: int
    full_suite: bool
    reason: str
    warnings: tuple[str, ...]
    missing_importers: tuple[str, ...]


def normalize(path: str) -> str:
    """Return a repo-relative path with forward slashes and no ``./`` prefix.

    Args:
        path: a path as printed by git or supplied by a diff file.

    Returns:
        The normalized path.
    """
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _git_raw(args: list[str]) -> str:
    """Run git and return stdout as text.

    Args:
        args: arguments after ``git``.

    Returns:
        Decoded stdout.

    Raises:
        SystemExit: When git exits non-zero.
    """
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"changed-tests: git {' '.join(args)} failed: {message}")
    return completed.stdout.decode("utf-8", "replace")


def _nul_paths(raw: str) -> list[str]:
    """Split a NUL-separated path list.

    Args:
        raw: git output produced with ``-z``.

    Returns:
        Non-empty normalized paths.
    """
    return [normalize(path) for path in raw.split("\0") if path]


def _status_paths(raw: str) -> list[str]:
    """Parse ``git status --porcelain=v1 -z`` into changed paths.

    Rename/copy entries carry the original path as an extra NUL-terminated
    token; it is consumed so it is not mistaken for a second change.

    Args:
        raw: porcelain status output.

    Returns:
        Changed paths (the new path of a rename).
    """
    tokens = raw.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if len(entry) < 4:
            continue
        code = entry[:2]
        paths.append(normalize(entry[3:]))
        if "R" in code or "C" in code:
            index += 1
    return paths


def changed_paths(base: str) -> list[str]:
    """Return committed and uncommitted changed paths for ``base``.

    Args:
        base: base ref; the committed diff is three-dot (against the merge base).

    Returns:
        Sorted unique repo-relative paths.

    Raises:
        SystemExit: When git cannot resolve the base or read the status.
    """
    committed = _nul_paths(_git_raw(["diff", "--name-only", "-z", f"{base}...HEAD"]))
    uncommitted = _status_paths(_git_raw(["status", "--porcelain=v1", "-z"]))
    return sorted(set(committed) | set(uncommitted))


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
        raise SystemExit(f"changed-tests: cannot read diff file {path}: {exc}") from exc
    return sorted({normalize(line) for line in lines if normalize(line)})


def module_for_path(path: str) -> str | None:
    """Map a changed ``backend/app`` Python file to its importable module name.

    Args:
        path: repo-relative changed path.

    Returns:
        The module name (``app.a.b``), ``app`` for its root package, or None
        when the path is not an importable app module.
    """
    candidate = Path(normalize(path))
    if candidate.suffix != ".py" or not candidate.as_posix().startswith("backend/app/"):
        return None
    parts = list(candidate.relative_to("backend").with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or parts[0] != "app":
        return None
    return ".".join(parts)


def parse_imports(source: str) -> set[str]:
    """Collect the module names a test file imports statically.

    Args:
        source: Python source text.

    Returns:
        Imported module names, including the module half of ``from`` imports
        and literal arguments to ``importlib.import_module``/``__import__``.

    Raises:
        SyntaxError: When the source cannot be parsed.
    """
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module)
                modules.update(
                    f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*"
                )
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            argument = node.args[0]
            if (
                name in {"import_module", "__import__"}
                and isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
            ):
                modules.add(argument.value)
    return {module for module in modules if module == "app" or module.startswith("app.")}


def discover_test_files() -> tuple[str, ...]:
    """List the test modules under ``backend/tests``.

    Returns:
        Sorted paths relative to ``backend/``.
    """
    files = []
    for path in sorted(TESTS.rglob("test_*.py")):
        relative = path.relative_to(BACKEND)
        if any(part.startswith("_") for part in relative.parts):
            continue
        files.append(relative.as_posix())
    return tuple(files)


def build_import_index(test_files: Iterable[str]) -> tuple[dict[str, set[str]], set[str]]:
    """Build a module-to-test-files index from a static import scan.

    Args:
        test_files: paths relative to ``backend/``.

    Returns:
        A mapping of imported module to importing test files, and the set of
        test files that could not be read or parsed (they are always selected).
    """
    index: dict[str, set[str]] = defaultdict(set)
    unparsed: set[str] = set()
    for relative in test_files:
        try:
            source = (BACKEND / relative).read_text(encoding="utf-8")
            modules = parse_imports(source)
        except (OSError, SyntaxError, UnicodeDecodeError):
            unparsed.add(relative)
            continue
        for module in modules:
            index[module].add(relative)
    return dict(index), unparsed


def _module_matches(imported: str, changed: str) -> bool:
    """Return whether an imported module is the changed module or a package relative.

    A bare ``app`` import is deliberately not a match for every module below
    it: the root package does not pull submodules in, and treating it as a
    parent would make "no importer" impossible to detect.

    Args:
        imported: a module name imported by a test.
        changed: the module name derived from a changed app file.

    Returns:
        True when either name is the other or a package relative.
    """
    if imported == changed:
        return True
    if imported == "app":
        return False
    return imported.startswith(changed + ".") or changed.startswith(imported + ".")


def select_for_module(module: str, imports: Mapping[str, set[str]]) -> set[str]:
    """Select test files importing a changed module or one of its parents.

    Args:
        module: changed module name.
        imports: module-to-test-files index.

    Returns:
        The union of importing test files.
    """
    selected: set[str] = set()
    for imported, files in imports.items():
        if _module_matches(imported, module):
            selected.update(files)
    return selected


def _is_test_target(path: str) -> bool:
    """Return whether a changed path is a collected test module.

    Args:
        path: repo-relative path.

    Returns:
        True for ``backend/tests/test_*.py``.
    """
    return (
        path.startswith("backend/tests/")
        and Path(path).name.startswith("test_")
        and Path(path).suffix == ".py"
    )


def _full_suite_reason(path: str) -> str | None:
    """Return why a path triggers the full suite, or None.

    Args:
        path: repo-relative changed path.

    Returns:
        A human-readable reason when the path is a full-suite trigger.
    """
    if path in FULL_SUITE_FILES:
        return f"{path} changed"
    for prefix in FULL_SUITE_DIRS:
        if path.startswith(prefix):
            return f"{prefix} changed"
    if path.startswith("backend/tests/") and not _is_test_target(path):
        return f"{path} is test-support"
    if path.startswith("backend/") and not path.startswith(("backend/app/", "backend/tests/")):
        return f"{path} is an unmapped backend path"
    return None


def build_plan(
    changed: Iterable[str],
    test_files: Iterable[str],
    imports: Mapping[str, set[str]],
    unparsed: Iterable[str] = (),
) -> Selection:
    """Plan the selected test files for a changed set.

    Args:
        changed: repo-relative changed paths (committed plus uncommitted).
        test_files: known test modules relative to ``backend/``.
        imports: module-to-test-files index.
        unparsed: test files the scan could not parse; always selected.

    Returns:
        The :class:`Selection` for the run.
    """
    normalized = sorted({normalize(path) for path in changed if normalize(path)})
    known = set(test_files)
    unparsed_set = set(unparsed)
    triggers = sorted({reason for path in normalized if (reason := _full_suite_reason(path))})
    if triggers:
        selected = known | set(ALWAYS_RUN) | unparsed_set
        return Selection(
            changed=tuple(normalized),
            selected=tuple(sorted(selected)),
            total_test_files=len(known),
            full_suite=True,
            reason="full suite: " + "; ".join(triggers),
            warnings=tuple(
                f"{path} could not be parsed; selecting it unconditionally"
                for path in sorted(unparsed_set)
            ),
            missing_importers=(),
        )

    selected = set(ALWAYS_RUN) | unparsed_set
    warnings: list[str] = [
        f"{path} could not be parsed; selecting it unconditionally" for path in sorted(unparsed_set)
    ]
    missing_importers: list[str] = []
    notes: list[str] = []
    changed_tests: list[str] = []
    for path in normalized:
        if path.startswith("backend/tests/"):
            relative = path.removeprefix("backend/")
            if relative in known:
                selected.add(relative)
                changed_tests.append(relative)
            else:
                warnings.append(
                    f"{path} is a deleted or uncollected test module; the always-run set still runs"
                )
        elif path.startswith("backend/app/"):
            module = module_for_path(path)
            if module is None:
                warnings.append(f"{path} is not an importable app module; always-run set only")
                continue
            importers = select_for_module(module, imports)
            if importers:
                selected.update(importers)
                notes.append(f"importers of {module}")
            else:
                missing_importers.append(module)
                warnings.append(f"no importer for {module} (changed {path}); always-run set only")
        elif path.startswith("backend/"):
            warnings.append(f"{path} is an unmapped backend path; always-run set only")

    reasons = []
    if notes:
        reasons.append(", ".join(dict.fromkeys(notes)))
    if changed_tests:
        reasons.append(f"{len(changed_tests)} changed test module(s)")
    reasons.append("always-run set")
    return Selection(
        changed=tuple(normalized),
        selected=tuple(sorted(selected)),
        total_test_files=len(known),
        full_suite=False,
        reason="; ".join(reasons),
        warnings=tuple(warnings),
        missing_importers=tuple(sorted(missing_importers)),
    )


def summarize(selection: Selection, base: str | None) -> str:
    """Return the one-line human summary.

    Args:
        selection: the planned selection.
        base: base ref, or None for a synthetic diff.

    Returns:
        ``n changed file(s); selected n of N test files; reason: ...``.
    """
    source = "synthetic diff" if base is None else f"base {base}"
    return (
        f"{len(selection.changed)} changed file(s) ({source}); "
        f"selected {len(selection.selected)} of {selection.total_test_files} test files; "
        f"reason: {selection.reason}"
    )


def _emit_warnings(selection: Selection) -> None:
    """Write warnings to stderr.

    Args:
        selection: the planned selection.
    """
    for warning in selection.warnings:
        print(f"changed-tests: warning: {warning}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Select tests for a diff or a synthetic path list.

    Args:
        argv: command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", default="origin/main", help="base ref (default: origin/main)")
    parser.add_argument("--diff-file", type=Path, help="read synthetic paths instead of git")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument(
        "--paths-only", action="store_true", help="print only pytest targets (for run-tests.sh)"
    )
    args = parser.parse_args(argv)
    if args.json and args.paths_only:
        parser.error("--json and --paths-only are mutually exclusive")

    changed = read_diff_file(args.diff_file) if args.diff_file else changed_paths(args.base)
    test_files = discover_test_files()
    imports, unparsed = build_import_index(test_files)
    selection = build_plan(changed, test_files, imports, unparsed)
    base = None if args.diff_file else args.base
    _emit_warnings(selection)

    if args.json:
        payload = {
            "base": base,
            "changed": list(selection.changed),
            "selected": list(selection.selected),
            "total_test_files": selection.total_test_files,
            "full_suite": selection.full_suite,
            "reason": selection.reason,
            "warnings": list(selection.warnings),
            "missing_importers": list(selection.missing_importers),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.paths_only:
        print(summarize(selection, base), file=sys.stderr)
        if not selection.selected:
            print("changed-tests: no tests selected", file=sys.stderr)
            return 1
        print("\n".join(selection.selected))
        return 0
    print(summarize(selection, base))
    for path in selection.selected:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
