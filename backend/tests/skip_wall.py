"""The skip wall's pure logic, shared by conftest and the CI completeness check.

``tests/conftest.py::pytest_sessionfinish`` compares a session's observed skips
with ``tests/skip_allowlist.json``: an unlisted skip fails the run, and every
``when: always`` entry for the active dialect must actually fire.
``scripts/check-skip-wall.py`` judges the same allowlist over the merged
observations of the sharded CI lanes. Both import this module so the matching
rule and its wording cannot drift.
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path


def load_allowlist(path: Path, dialect: str) -> list[dict[str, str]]:
    """Load the reviewed skip entries for one dialect.

    Args:
        path: the ``skip_allowlist.json`` path.
        dialect: ``postgres`` or ``sqlite`` — the CI lanes prove different
            contracts, so entries are dialect-scoped.

    Returns:
        The dialect's entries (empty when the file names none).

    Raises:
        SystemExit: When the file is unreadable, malformed, or the dialect's
            value is not a list.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read skip allowlist {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected a JSON object")
    entries = data.get(dialect, [])
    if not isinstance(entries, list):
        raise SystemExit(f"{path}: {dialect!r} must be a list")
    return entries


def matching_allowlist_entry(
    nodeid: str, reason: str, allowlist: list[dict[str, str]]
) -> int | None:
    """Return the allowlist index a skip matches, or None when it is unlisted.

    Args:
        nodeid: the skipped test's node id.
        reason: the skip reason as pytest reported it.
        allowlist: the dialect's reviewed entries.

    Returns:
        The matching entry's index, or None when no entry claims the skip.
    """
    for index, entry in enumerate(allowlist):
        if not fnmatch.fnmatch(nodeid, entry["id"]):
            continue
        if entry["reason_contains"] in reason:
            return index
    return None


def unlisted_skip_problems(observed: dict[str, str], allowlist: list[dict[str, str]]) -> list[str]:
    """Return one problem per observed skip the allowlist does not claim.

    Args:
        observed: skipped node id to reason.
        allowlist: the dialect's reviewed entries.

    Returns:
        Human-readable problems (empty when every skip is reviewed).
    """
    return [
        f"unlisted skip: {nodeid} ({reason})"
        for nodeid, reason in observed.items()
        if matching_allowlist_entry(nodeid, reason, allowlist) is None
    ]


def missing_allowlisted_skip_problems(
    observed: dict[str, str], allowlist: list[dict[str, str]]
) -> list[str]:
    """Return one problem per ``when: always`` entry that did not fire.

    Args:
        observed: skipped node id to reason for the selection being judged.
        allowlist: the dialect's reviewed entries.

    Returns:
        Human-readable problems (empty when every always entry fired).
    """
    matched = {
        index
        for nodeid, reason in observed.items()
        if (index := matching_allowlist_entry(nodeid, reason, allowlist)) is not None
    }
    return [
        f"allowlisted skip did not fire: {entry['id']} ({entry['reason_contains']})"
        for index, entry in enumerate(allowlist)
        if entry.get("when", "always") == "always" and index not in matched
    ]
