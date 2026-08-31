#!/usr/bin/env python3
"""Semver bump/set for the single version source (backend/app/__init__.py).

Usage:
    version_manager.py bump major|minor|patch
    version_manager.py set X.Y.Z
    version_manager.py show
"""

import pathlib
import re
import sys

VERSION_FILE = pathlib.Path(__file__).resolve().parents[1] / "backend/app/__init__.py"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def read_version() -> str:
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', VERSION_FILE.read_text(), re.M)
    if match is None:
        raise SystemExit(f"No __version__ found in {VERSION_FILE}")
    return match.group(1)


def write_version(new: str) -> None:
    if not SEMVER.match(new):
        raise SystemExit(f"Not semver: {new!r}")
    text = VERSION_FILE.read_text()
    updated = re.sub(
        r'^__version__\s*=\s*"[^"]+"', f'__version__ = "{new}"', text, count=1, flags=re.M
    )
    VERSION_FILE.write_text(updated)


def bump(version: str, part: str) -> str:
    major, minor, patch = (int(p) for p in version.split("."))
    return {
        "major": f"{major + 1}.0.0",
        "minor": f"{major}.{minor + 1}.0",
        "patch": f"{major}.{minor}.{patch + 1}",
    }[part]


def main(argv: list[str]) -> int:
    if len(argv) == 1 and argv[0] == "show":
        print(read_version())
        return 0
    if len(argv) == 2 and argv[0] == "bump" and argv[1] in ("major", "minor", "patch"):
        new = bump(read_version(), argv[1])
    elif len(argv) == 2 and argv[0] == "set":
        new = argv[1]
        if not SEMVER.match(new):
            raise SystemExit(f"Not semver: {new!r}")
    else:
        print(__doc__)
        return 2
    write_version(new)
    print(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
