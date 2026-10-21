"""Docs are a tested surface (plan 115).

Three claims the manual makes are machine-checked here:

- every user-facing route named in ``docs/user/*.md`` exists in the
  frontend router (redirect-only routes are not documentation targets) or
  in the backend router;
- every row of the README feature-status table maps to a
  ``frontend/src/config/features.json`` entry with the same state and the
  same documentation page, and no registry entry is missing from it;
- every ``file`` reference in ``docs/docs-tree.json`` resolves.

The gate exists because the manual once advertised a shipped cover-letter
feature while the feature catalog called it "coming soon", and the sidebar
hid four pages the dashboard linked to.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DOCS = REPO_ROOT / "docs"
APP_TSX = REPO_ROOT / "frontend" / "src" / "App.tsx"
FEATURES_JSON = REPO_ROOT / "frontend" / "src" / "config" / "features.json"
README = REPO_ROOT / "README.md"

_ROUTE_TAG = re.compile(r"<Route\b")
_PATH_ATTR = re.compile(r'path="([^"]+)"')
_INLINE_CODE_ROUTE = re.compile(r"`(/[^`\s]+)`")
_MD_LINK_ROUTE = re.compile(r"\]\((/[^)\s#]+)(?:#[^)]*)?\)")
_NON_UI_PREFIXES = ("/api/", "/docs", "/static/", "/assets/", "/uploads/")


def _frontend_routes() -> tuple[set[str], set[str]]:
    """Parse App.tsx into (reachable routes, redirect-only routes).

    Child routes are joined onto their nearest absolute parent; a route
    whose element is a ``<Navigate>`` is a legacy deep link, not a page a
    guide may document.
    """
    routes: set[str] = set()
    redirects: set[str] = set()
    stack: list[tuple[int, str]] = []
    for line in APP_TSX.read_text(encoding="utf-8").splitlines():
        if not _ROUTE_TAG.search(line):
            continue
        indent = len(line) - len(line.lstrip())
        while stack and stack[-1][0] >= indent:
            stack.pop()
        match = _PATH_ATTR.search(line)
        if match is None:
            continue
        raw = match.group(1)
        if raw.startswith("/"):
            full = raw
        elif stack:
            full = f"{stack[-1][1].rstrip('/')}/{raw}"
        else:
            full = f"/{raw}"
        (redirects if "<Navigate" in line else routes).add(full)
        if not line.rstrip().endswith("/>"):
            stack.append((indent, full))
    return routes, redirects


def _backend_routes() -> set[str]:
    from app.main import app

    paths = set(app.openapi()["paths"])
    paths |= {route.path for route in app.routes if hasattr(route, "path")}
    return paths | {path.removeprefix("/api/v1") or "/" for path in paths}


def _segment_matches(documented: str, actual: str) -> bool:
    left = documented.strip("/").split("/")
    right = actual.strip("/").split("/")
    if len(left) != len(right):
        return False
    for documented_part, actual_part in zip(left, right, strict=True):
        if documented_part[:1] in (":", "{"):
            continue
        if actual_part[:1] in (":", "{"):
            continue
        if documented_part != actual_part:
            return False
    return True


def _documented_routes() -> list[tuple[str, str]]:
    claims: list[tuple[str, str]] = []
    for page in sorted((DOCS / "user").glob("*.md")):
        text = page.read_text(encoding="utf-8")
        seen: set[str] = set()
        for match in (*_INLINE_CODE_ROUTE.finditer(text), *_MD_LINK_ROUTE.finditer(text)):
            route = match.group(1).split("?")[0].split("#")[0].rstrip(".,;:")
            if route in seen or route.startswith(_NON_UI_PREFIXES):
                continue
            seen.add(route)
            claims.append((page.relative_to(REPO_ROOT).as_posix(), route))
    return claims


def test_every_documented_user_route_exists():
    frontend, redirects = _frontend_routes()
    backend = _backend_routes()
    broken: list[str] = []
    for page, route in _documented_routes():
        if any(_segment_matches(route, known) for known in frontend | backend):
            continue
        if any(_segment_matches(route, known) for known in redirects):
            broken.append(f"{page}: {route} is a redirect — document its target")
        else:
            broken.append(f"{page}: {route} matches no route")
    assert not broken, "\n".join(broken)


def _feature_registry() -> dict[str, dict]:
    return {entry["key"]: entry for entry in json.loads(FEATURES_JSON.read_text())["features"]}


def _readme_feature_rows() -> list[dict[str, str]]:
    text = README.read_text(encoding="utf-8")
    section = text.split("### Feature status", 1)
    assert len(section) == 2, "README must carry a '### Feature status' table"
    rows: list[dict[str, str]] = []
    for line in section[1].splitlines()[1:]:
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[1] in ("Route", "---"):
            continue
        route = re.fullmatch(r"`([^`]+)`", cells[1])
        docs_link = re.fullmatch(r"\[[^\]]+\]\(([^)]+)\)", cells[3])
        assert route and docs_link, f"malformed feature-status row: {line}"
        rows.append(
            {
                "surface": cells[0],
                "key": route.group(1),
                "state": cells[2],
                "docs": docs_link.group(1),
            }
        )
    return rows


def test_readme_feature_table_matches_the_app_registry():
    registry = _feature_registry()
    rows = _readme_feature_rows()
    assert rows, "the README feature-status table must list every registered surface"
    problems: list[str] = []
    claimed = {row["key"] for row in rows}
    for key in sorted(set(registry) - claimed):
        problems.append(f"{key}: registered but missing from the README table")
    for key in sorted(claimed - set(registry)):
        problems.append(f"{key}: in the README table but not in features.json")
    for row in rows:
        entry = registry.get(row["key"])
        if entry is None:
            continue
        if row["state"] != entry["state"]:
            problems.append(
                f"{row['key']}: README says {row['state']}, features.json says {entry['state']}"
            )
        if row["docs"] != entry["docs"]:
            problems.append(
                f"{row['key']}: README documents {row['docs']}, registry says {entry['docs']}"
            )
        if not (REPO_ROOT / entry["docs"]).is_file():
            problems.append(f"{row['key']}: documentation page {entry['docs']} does not exist")
    assert not problems, "\n".join(problems)


def _tree_files(node: object) -> list[str]:
    if isinstance(node, dict):
        return [
            value for key, value in node.items() if key == "file" and isinstance(value, str)
        ] + [ref for value in node.values() for ref in _tree_files(value)]
    if isinstance(node, list):
        return [ref for item in node for ref in _tree_files(item)]
    return []


def test_docs_tree_references_real_files():
    tree = json.loads((DOCS / "docs-tree.json").read_text(encoding="utf-8"))
    missing = [ref for ref in sorted(set(_tree_files(tree))) if not (DOCS / ref).is_file()]
    assert not missing, "docs-tree.json points at missing files:\n" + "\n".join(missing)


def test_redirect_only_routes_are_not_documentation_targets():
    routes, redirects = _frontend_routes()
    assert "/settings/automations" in routes
    assert "/settings/scheduler" in redirects
    assert "/settings/scheduler" not in routes


def test_feature_table_and_tour_read_the_same_registry():
    scenes = REPO_ROOT / "scripts" / "ui-capture" / "scenes.mjs"
    paths = [
        path.split("?")[0]
        for path in re.findall(r'path:\s*"([^"]+)"', scenes.read_text(encoding="utf-8"))
    ]
    registry = _feature_registry()
    offenders = [
        path
        for path in paths
        for key, entry in registry.items()
        if entry["state"] == "hidden" and (path == key or path.startswith(f"{key}/"))
    ]
    assert not offenders, f"tour scenes target hidden features: {offenders}"
    missing = [
        key
        for key, entry in registry.items()
        if entry["state"] == "beta"
        and not any(path == key or path.startswith(f"{key}/") for path in paths)
    ]
    assert not missing, f"beta surfaces with no tour scene: {missing}"
