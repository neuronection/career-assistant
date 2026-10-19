"""Per-extension documentation helpers (plan 34 wave 8 — the
``extensionDocsTree`` form, guidelines/extension-docs.md §10; health's
``app/extensions/docs.py`` is the family reference shape).

The registration-time binding gate lives in ``registry.py``
(``_validate_docs_binding`` — the vendored schema plus the contract's
wall semantics). This module carries the SERVE-side pieces:

- :func:`load_tree` — parse ``docs/docs-tree.json`` under a bundle's
  docs dir; None when the bundle ships no tree.
- :func:`landing_file` — the landing rule: array order is render
  order; the first item of the first category lands, unless exactly
  one item carries ``index: true``.
- :func:`strip_raw_html` — the markdown law (§10.7): extension-doc
  pages are markdown only. Raw HTML outside code fences/spans is
  neutralized to escaped text — the SAME fence-aware shape as the
  family's post-H3 posture (health's site removed ``rehypeRaw`` after
  a committed ``<script>`` rendered into executable static HTML);
  autolinks and full-line HTML comments stay (markdown, not HTML).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_RAW_HTML = re.compile(r"<\s*/?[a-zA-Z!][^>\n]*>")
_AUTOLINK = re.compile(r"^<[a-zA-Z][a-zA-Z0-9+.\-]*(:|@)[^>\n]*>$")
_COMMENT_LINE = re.compile(r"^\s*<!--.*-->\s*$")
_FENCE = re.compile(r"^[\t ]*(`{3,}|~{3,})")


def load_tree(docs_dir: Path) -> dict[str, Any] | None:
    """Parse ``docs/docs-tree.json`` under ``docs_dir``; None when the
    bundle ships no tree."""
    path = docs_dir / "docs-tree.json"
    if not path.is_file():
        return None
    tree = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tree, dict):
        return None
    return tree


def landing_file(tree: dict[str, Any]) -> str | None:
    """The landing rule: the FIRST item of the FIRST category, unless
    exactly one item carries ``index: true`` (registration semantics
    have already pinned at-most-one)."""
    landing: Any = None
    for category in tree.get("categories", []):
        for item in category.get("items", []):
            if item.get("index"):
                landing = item.get("file")
                break
        if landing is not None:
            break
    if landing is None:
        for category in tree.get("categories", []):
            for item in category.get("items", []):
                landing = item.get("file")
                break
            if landing is not None:
                break
    return str(landing) if landing is not None else None


def strip_raw_html(markdown: str) -> str:
    """The markdown law (§10.7): raw HTML outside code fences and
    inline code spans becomes escaped text — inert AND visible, the
    post-H3 shape. Autolinks (``<https://…>``, ``<user@host>``) and
    full-line HTML comments are markdown-adjacent exceptions, same as
    the website's gate."""
    out: list[str] = []
    in_fence = False
    for line in markdown.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        segments = re.split(r"(`[^`\n]*`)", line)
        rebuilt = ""
        for i, segment in enumerate(segments):
            if i % 2 == 1:
                rebuilt += segment
                continue
            cursor = segment
            while True:
                match = _RAW_HTML.search(cursor)
                if not match:
                    rebuilt += cursor
                    break
                tag = match.group(0)
                if _AUTOLINK.match(tag.strip()) or _COMMENT_LINE.match(line):
                    rebuilt += cursor[: match.end()]
                else:
                    rebuilt += cursor[: match.start()]
                    rebuilt += tag.replace("<", "&lt;").replace(">", "&gt;")
                cursor = cursor[match.end() :]
        out.append(rebuilt)
    return "\n".join(out)
