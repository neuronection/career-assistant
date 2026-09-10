"""Reference-discipline invariants (Phase 21): no label/title matching in code.

Relations are matched by FK ids or stable `key` slugs only. Labels and
titles are display-only (i18n-overlayable). A regression that compares
`.label`/`.title` in query paths would break the moment a label is
translated or reworded — this test keeps that class of bug out.
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# `.label ==` / `.title ==` / `!=` comparisons in application code.
FORBIDDEN = re.compile(r"\.(label|title)\s*(==|!=)")

# Raw string label matching on query inputs, e.g. `== "Physics"`.
LINE_OPT_OUT = "label-compare-ok"  # reviewed exceptions, per line


def test_no_label_or_title_comparisons_in_application_code():
    offenders = []
    for path in APP.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(source.splitlines(), start=1):
            if FORBIDDEN.search(line) and LINE_OPT_OUT not in line:
                offenders.append(
                    f"{path.relative_to(APP.parent)}:{lineno}: {line.strip()}"
                )
    assert not offenders, (
        "Label/title comparisons found — match on ids or stable keys instead:\n"
        + "\n".join(offenders)
    )
