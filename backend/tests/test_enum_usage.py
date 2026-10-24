"""Enum-usage wall (plan 114.2).

`app/models/enums.py` is the app's closed-vocabulary registry, so an enum
member has to be *reachable* from app code. A member is live when any of
these holds:

1. **Attribute reference** — `Enum.MEMBER` appears in `backend/app/**`
   (write paths, comparisons, model defaults, registry mappings).
2. **Typed boundary** — the enum class itself is referenced in
   `backend/app/**`: it is imported by a schema or model and validated on
   input, so every member is accepted vocabulary (a user can submit any
   of them). The reference is read from the AST, never from comments or
   docstrings.
3. **Mirrored DB CHECK** — the enum backs a `CHECK` constraint asserted by
   `tests/test_schema_contracts.py`, which makes the member part of the
   stored contract even when no Python branch names it.

Anything else is dead code: delete the member (and its mirrored CHECK in
the same commit, family-migration §5b) or justify it in
`ALLOWED_UNUSED` with the reason it must exist. The allowlist starts
empty and may never hold a stale entry.
"""

import ast
from pathlib import Path

from tests.test_schema_contracts import CHECKS

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
ENUMS_MODULE = APP / "models" / "enums"  # plan 123.6: package directory

#: `"Class.MEMBER": "why this member is kept without an app reference"`.
ALLOWED_UNUSED: dict[str, str] = {}


def _enum_members() -> dict[str, list[str]]:
    enums: dict[str, list[str]] = {}
    # Plan 123.6: the registry is the ``app/models/enums/`` package; the
    # AST walk covers every module file (same liveness rules as when the
    # registry was one file).
    for module_file in sorted(ENUMS_MODULE.glob("*.py")):
        tree = ast.parse(module_file.read_text())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            members = [
                statement.targets[0].id
                for statement in node.body
                if isinstance(statement, ast.Assign)
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id.isupper()
            ]
            if members:
                enums[node.name] = members
    return enums


def _references() -> tuple[set[str], set[tuple[str, str]]]:
    """(enum class names, `Class.MEMBER` pairs) referenced by app code."""
    classes: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                classes.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                classes.add(node.value.id)
                pairs.add((node.value.id, node.attr))
    return classes, pairs


def _check_mirrored() -> set[str]:
    return {spec.__name__ for _table, _constraint, spec in CHECKS if not isinstance(spec, set)}


def dead_members() -> dict[str, list[str]]:
    """Members no app code path can reach, keyed by enum class."""
    classes, pairs = _references()
    mirrored = _check_mirrored()
    dead: dict[str, list[str]] = {}
    for enum, members in _enum_members().items():
        if enum in classes or enum in mirrored:
            continue
        missing = [member for member in members if (enum, member) not in pairs]
        if missing:
            dead[enum] = missing
    return dead


def _keys(dead: dict[str, list[str]]) -> set[str]:
    return {f"{enum}.{member}" for enum, members in dead.items() for member in members}


def test_no_dead_enum_members():
    dead = _keys(dead_members()) - set(ALLOWED_UNUSED)
    assert not dead, (
        "dead enum members (no app reference, no typed boundary, no mirrored CHECK): "
        + ", ".join(sorted(dead))
        + " — delete them with their mirrored CHECKs (family-migration §5b) or "
        "record why in ALLOWED_UNUSED"
    )


def test_allowlist_has_no_stale_entries():
    dead = _keys(dead_members())
    stale = set(ALLOWED_UNUSED) - dead
    assert not stale, (
        "ALLOWED_UNUSED entries that are no longer dead (delete the entry): "
        + ", ".join(sorted(stale))
    )
