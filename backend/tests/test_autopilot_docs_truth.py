"""The Autopilot graph's documentation truth gate (plan 158 S8.3).

Family law: "a code block that lies is a bug; a structure gate is not a
truth gate". The topology diagram, the candidate-funnel diagram and the
pinned-constants table in ``docs/dev/ai-layer.md`` are compared with the
compiled graph and the module constants, so a constant change that leaves
the diagram stale fails CI (precedent: ``test_sdk_docs_truth.py``). The
user page carries a plain-language diagram and must never print internal
constant names.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.ai.graphs.autopilot import (
    CANDIDATE_CAP,
    DEFAULT_TOP_N,
    GRAPH_NEIGHBORS,
    GRAPH_SEEDS,
    REPLAN_LIMIT,
    SEARCH_LIMIT,
    SEARCH_VARIANTS,
    SEMANTIC_K,
    GraphDeps,
    build_autopilot_graph,
    curator_pool,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_LAYER = REPO_ROOT / "docs" / "dev" / "ai-layer.md"
USER_DOC = REPO_ROOT / "docs" / "user" / "career-autopilot.md"

MERMAID_RE = re.compile(r"^```mermaid\n(.*?)^```", re.MULTILINE | re.DOTALL)
CONSTANT_ROW_RE = re.compile(r"^\| `([A-Z_]+)` \| (\d+) \|", re.MULTILINE)
QUOTED_NODE_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\["([^"]+)"\]')
TERMINAL_NODE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\(\[([A-Za-z_]+)\]\)")

TERMINALS = {"START": "__start__", "END": "__end__"}


def _ai_layer() -> str:
    return AI_LAYER.read_text(encoding="utf-8")


def _doc_node_names(block: str) -> set[str]:
    names = set(TERMINALS.values())
    for _node_id, label in QUOTED_NODE_RE.findall(block):
        names.add(label.split("·")[0].strip().split()[0].lower())
    for _node_id, label in TERMINAL_NODE_RE.findall(block):
        names.add(TERMINALS.get(label, label.lower()))
    return names


def _code_node_names() -> set[str]:
    return set(build_autopilot_graph(GraphDeps(db=None)).nodes)


def _mermaid_blocks(text: str) -> list[str]:
    return MERMAID_RE.findall(text)


def test_topology_diagram_names_the_real_nodes():
    blocks = _mermaid_blocks(_ai_layer())
    topology = next(block for block in blocks if "flowchart TD" in block)
    names = _doc_node_names(topology)
    assert "-->" in topology and "__end__" in names
    assert names - {"__end__"} == _code_node_names()


def test_pinned_constants_table_matches_the_code():
    rows = dict(CONSTANT_ROW_RE.findall(_ai_layer()))
    expected = {
        "SEARCH_VARIANTS": SEARCH_VARIANTS,
        "SEARCH_LIMIT": SEARCH_LIMIT,
        "SEMANTIC_K": SEMANTIC_K,
        "GRAPH_SEEDS": GRAPH_SEEDS,
        "GRAPH_NEIGHBORS": GRAPH_NEIGHBORS,
        "CANDIDATE_CAP": CANDIDATE_CAP,
        "CURATOR_POOL": curator_pool(DEFAULT_TOP_N),
        "REPLAN_LIMIT": REPLAN_LIMIT,
    }
    assert {name: int(value) for name, value in rows.items()} == expected


def test_candidate_funnel_prints_the_same_bounds():
    text = _ai_layer()
    assert f"CANDIDATE_CAP {CANDIDATE_CAP}" in text
    assert f"top {SEMANTIC_K} " in text
    assert f"up to {SEARCH_VARIANTS} x {SEARCH_LIMIT} examined" in text
    assert f"{curator_pool(DEFAULT_TOP_N)} at the default top_n {DEFAULT_TOP_N}" in text
    assert f"up to {GRAPH_SEEDS} seeds, {GRAPH_NEIGHBORS} neighbour roles" in text
    assert f"replan_attempts < {REPLAN_LIMIT}" in text


def test_state_channels_and_routing_tables_are_present():
    text = _ai_layer()
    for channel in (
        "`plan`",
        "`candidates`",
        "`searches`",
        "`replan_attempts`",
        "`curation`",
        "`progress_pct`",
    ):
        assert channel in text
    for reason in ("`budget`", "`cancelled`", "`error`"):
        assert f"| {reason} |" in text


def test_user_page_diagram_stays_user_level():
    text = USER_DOC.read_text(encoding="utf-8")
    blocks = _mermaid_blocks(text)
    assert len(blocks) == 1, "one plain-language diagram"
    assert "your goal" in blocks[0]
    for constant in (
        "CANDIDATE_CAP",
        "CURATOR_POOL",
        "SEMANTIC_K",
        "GRAPH_SEEDS",
        "GRAPH_NEIGHBORS",
        "SEARCH_LIMIT",
        "REPLAN_LIMIT",
    ):
        assert constant not in text, f"{constant} is an internal bound, not user prose"
