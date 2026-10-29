"""Standing rule: the product repo never mentions the private
integration bundles — their ids, their third-party dependencies, or
their repository name (career-assistant-integrations README rule 1,
legal separation). The closeout empty-grep made mechanical: this test
fails on any tracked file carrying one of the forbidden tokens.

A legitimate new use of one of these strings does not exist by
definition; if the rule ever changes, change the token list here in the
same commit that explains why.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_TOKENS = ("patchright", "linkedin-postings", "career-assistant-integrations")
SELF_PATH = Path(__file__).resolve()


def _tracked_files() -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [REPO_ROOT / line.strip() for line in listing.stdout.splitlines() if line.strip()]


def test_no_private_integration_mentions_in_tracked_files() -> None:
    offenders: list[str] = []
    for path in _tracked_files():
        if path == SELF_PATH or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for token in FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {token}")
    assert not offenders, (
        "private-integration mentions in the product repo "
        "(standing rule: legal separation) — " + "; ".join(offenders)
    )
