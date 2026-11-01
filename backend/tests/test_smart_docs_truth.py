"""Smart discovery's documentation truth gate (plan 179 S4.2).

The constants, knob names, toggle name and cache TTL printed in the docs
must match the code the same way the autopilot truth gate pins the graph
(``test_autopilot_docs_truth.py``): a constant change that leaves the
docs stale fails here, and vice versa.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.enums import BackgroundJobType, ScheduleKind
from app.services.postings.digest_service import (
    SMART_DIGEST_KIND,
    SMART_DIGEST_TRIGGER,
)
from app.services.postings.explore_service import (
    SMART_AFFINITY_NEUTRAL,
    SMART_AFFINITY_WEIGHT,
    SMART_FIT_WEIGHT,
    SMART_ORG_CAP,
    SMART_SEEN_DEMOTION,
)
from app.services.postings.smart_search_service import SMART_QUERY_TTL_DAYS

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_LAYER = REPO_ROOT / "docs" / "dev" / "ai-layer.md"
POSTINGS_DOC = REPO_ROOT / "docs" / "user" / "postings-and-search.md"
NOTIFICATIONS_DOC = REPO_ROOT / "docs" / "user" / "notifications-and-scheduler.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ai_layer_formula_matches_the_code():
    text = _read(AI_LAYER)
    assert f"{SMART_FIT_WEIGHT}·fit + {SMART_AFFINITY_WEIGHT}·affinity" in text
    assert f"neutral affinity term {SMART_AFFINITY_NEUTRAL}" in text
    assert f"SMART_SEEN_DEMOTION` = -{SMART_SEEN_DEMOTION}" in text, (
        "the seen demotion is pinned by name and value"
    )
    assert f"`SMART_ORG_CAP` = {SMART_ORG_CAP}" in text


def test_ai_layer_names_the_task_and_cache_contract():
    text = _read(AI_LAYER)
    assert "SMART_SEARCH" in text and "fast tier" in text
    assert "`smart_query_cache`, TTL 7d" in text
    assert "cross-user" in text
    assert "prompt version v1 + golden case" in text


def test_ai_layer_diagram_is_a_flowchart_lr_naming_the_real_pieces():
    text = _read(AI_LAYER)
    blocks = re.findall(r"^```mermaid\n(.*?)^```", text, re.MULTILINE | re.DOTALL)
    smart_blocks = [block for block in blocks if "smart" in block.lower()]
    assert smart_blocks, "the smart discovery diagram exists"
    block = smart_blocks[-1]
    assert block.lstrip().startswith("flowchart LR")
    for node in ("posting_fits cache", "ai_embeddings", "smart_query_cache", "smart_digest"):
        assert node in block, node


def test_user_docs_pin_the_deep_link_and_the_toggle():
    postings = _read(POSTINGS_DOC)
    notifications = _read(NOTIFICATIONS_DOC)
    assert "/postings?sort=smart" in notifications, "the digest deep link is the living view"
    assert SMART_DIGEST_KIND in notifications, "the toggle name matches the kind key"
    assert "0.65 \u00d7 fit + 0.35 \u00d7 affinity" in postings, "the formula appears in words"


def test_digest_trigger_and_registry_names_match_the_code():
    assert SMART_DIGEST_TRIGGER == {
        "type": "daily_at",
        "params": {"time": "08:00", "timezone": "UTC"},
    }
    assert ScheduleKind.USER_SMART_DIGEST.value == "user_smart_digest"
    assert BackgroundJobType.SMART_DIGEST.value == "smart_digest"
    assert SMART_QUERY_TTL_DAYS == 7
