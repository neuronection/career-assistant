"""Runtime data files the packaged app reads from its own source tree.

The frozen (PyInstaller) bundle and the container image both need the
builtin extension bundles: the registry validates every manifest at
registration and fails closed, and the admin docs surface serves the
per-bundle markdown trees. PyInstaller only collects Python modules, so
these files must be added explicitly.
"""

from __future__ import annotations

from pathlib import Path

BUILTIN_REL = Path("backend") / "app" / "extensions" / "builtin"
BUILTIN_DEST = "app/extensions/builtin"
DATA_SUFFIXES = (".json", ".md")


def builtin_data_entries(repo_root: Path) -> list[tuple[str, str]]:
    """Return ``(source, destination)`` pairs for every builtin bundle data file."""
    root = repo_root / BUILTIN_REL
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in DATA_SUFFIXES:
            continue
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root)
        destination = (Path(BUILTIN_DEST) / relative.parent).as_posix()
        entries.append((str(path), destination))
    return entries
