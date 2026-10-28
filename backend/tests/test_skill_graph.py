"""Pure skill-graph expansion (plan 138, decision 3): the §7 corpus rows
as expansion assertions, plus the corrupt-data and hop-cap pins."""

from __future__ import annotations

import uuid

from app.models.enums import SkillExpandMode, SkillRelationType
from app.services.catalog.skill_graph import SkillEdge, SkillGraph, SkillNode, expand


def _uid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"skill-graph-test:{name}")


def _node(name: str, parent: str | None = None) -> SkillNode:
    return SkillNode(id=_uid(name), key=name, parent_id=_uid(parent) if parent else None)


def _edge(source: str, target: str, relation: SkillRelationType | str) -> SkillEdge:
    return SkillEdge(
        from_skill_id=_uid(source),
        to_skill_id=_uid(target),
        relation=str(relation.value if isinstance(relation, SkillRelationType) else relation),
    )


def _graph(*nodes: SkillNode, edges: tuple[SkillEdge, ...] = ()) -> tuple[dict, tuple]:
    return {node.id: node for node in nodes}, edges


# ---------------------------------------------------------------- off / seeds


def test_off_mode_matches_the_selected_skill_only():
    index, edges = _graph(
        _node("programming"), _node("java"), edges=(_edge("java", "programming", "is_a"),)
    )
    assert expand({_uid("programming")}, index, edges, mode=SkillExpandMode.OFF) == {
        _uid("programming")
    }


def test_unknown_seed_passes_through_unexpanded():
    index, edges = _graph(_node("programming"))
    unknown = uuid.uuid4()
    assert expand({unknown}, index, edges, mode=SkillExpandMode.DOWN) == {unknown}


def test_empty_seed_set_expands_to_nothing():
    index, edges = _graph(_node("programming"))
    assert expand(set(), index, edges) == set()


# -------------------------------------------------------------- down (is_a)


def test_down_matches_is_a_children_at_one_hop():
    """java is_a programming ⇒ filtering "programming" (down, 1) matches java."""
    index, edges = _graph(
        _node("programming"),
        _node("java"),
        _node("python"),
        edges=(
            _edge("java", "programming", "is_a"),
            _edge("python", "programming", "is_a"),
        ),
    )
    reached = expand({_uid("programming")}, index, edges, mode="down", hops=1)
    assert reached == {_uid("programming"), _uid("java"), _uid("python")}


def test_down_needs_two_hops_for_a_transitive_is_a_chain():
    """java is_a jvm-lang is_a programming: only hops=2 reaches java (§7)."""
    index, edges = _graph(
        _node("programming"),
        _node("jvm-lang"),
        _node("java"),
        edges=(
            _edge("jvm-lang", "programming", "is_a"),
            _edge("java", "jvm-lang", "is_a"),
        ),
    )
    one_hop = expand({_uid("programming")}, index, edges, mode="down", hops=1)
    two_hops = expand({_uid("programming")}, index, edges, mode="down", hops=2)
    assert one_hop == {_uid("programming"), _uid("jvm-lang")}
    assert _uid("java") in two_hops


def test_hops_are_clamped_to_two():
    index, edges = _graph(
        _node("a"),
        _node("b"),
        _node("c"),
        _node("d"),
        edges=(
            _edge("b", "a", "is_a"),
            _edge("c", "b", "is_a"),
            _edge("d", "c", "is_a"),
        ),
    )
    assert expand({_uid("a")}, index, edges, mode="down", hops=99) == {
        _uid("a"),
        _uid("b"),
        _uid("c"),
    }


def test_down_never_walks_upward():
    """Filtering "java" must not match every posting requiring "programming"."""
    index, edges = _graph(
        _node("programming"), _node("java"), edges=(_edge("java", "programming", "is_a"),)
    )
    assert expand({_uid("java")}, index, edges, mode="down", hops=2) == {_uid("java")}


def test_down_includes_the_whole_curated_parent_tree_subtree():
    """parent_id is the curated backbone: the whole subtree is trusted."""
    index, edges = _graph(
        _node("programming"),
        _node("backend", parent="programming"),
        _node("api", parent="backend"),
    )
    assert expand({_uid("programming")}, index, edges, mode="down", hops=1) == {
        _uid("programming"),
        _uid("backend"),
        _uid("api"),
    }


def test_tree_subtree_also_applies_to_is_a_children():
    index, edges = _graph(
        _node("programming"),
        _node("java"),
        _node("java-ee", parent="java"),
        edges=(_edge("java", "programming", "is_a"),),
    )
    assert _uid("java-ee") in expand({_uid("programming")}, index, edges, mode="down", hops=1)


def test_backfilled_parent_turns_hop_reach_into_free_reach():
    """Plan 138 step 7: the tree catch-up migrates hop-capped reach into
    FREE reach — the budget widens as the tree fills. Same edges both
    times; the filled display parents are the only difference."""
    edges = (
        _edge("jvm-lang", "programming", "is_a"),
        _edge("java", "jvm-lang", "is_a"),
    )
    before_nodes, before_edges = _graph(
        _node("programming"), _node("jvm-lang"), _node("java"), edges=edges
    )
    one_before = expand({_uid("programming")}, before_nodes, before_edges, mode="down", hops=1)
    assert one_before == {_uid("programming"), _uid("jvm-lang")}, "java needs two hops before"

    after_nodes, after_edges = _graph(
        _node("programming"),
        _node("jvm-lang", parent="programming"),
        _node("java", parent="jvm-lang"),
        edges=edges,
    )
    one_after = expand({_uid("programming")}, after_nodes, after_edges, mode="down", hops=1)
    assert one_after == {_uid("programming"), _uid("jvm-lang"), _uid("java")}
    assert one_after == expand(
        {_uid("programming")}, after_nodes, after_edges, mode="down", hops=2
    ), "the budget saturated — the free subtree ignores hops"


def test_unrelated_parent_fills_never_change_synonym_or_related_reach():
    """§7 machine-learning / ml and typescript / javascript: the catch-up
    migrates is_a rows only — filling display parents elsewhere in the
    catalog never changes synonym identity or related-mode reach."""
    edges = (
        _edge("ml", "machine-learning", "synonym"),
        _edge("typescript", "javascript", "related_to"),
    )
    before_nodes, before_edges = _graph(
        _node("machine-learning"),
        _node("ml"),
        _node("javascript"),
        _node("typescript"),
        edges=edges,
    )
    after_nodes, after_edges = _graph(
        _node("machine-learning", parent="data"),
        _node("ml", parent="data"),
        _node("data"),
        _node("javascript", parent="web"),
        _node("typescript", parent="web"),
        _node("web"),
        edges=edges,
    )
    for seed, mode, expected in (
        ("machine-learning", "down", {"machine-learning", "ml"}),
        ("javascript", "down", {"javascript"}),
        ("javascript", "related", {"javascript", "typescript"}),
    ):
        before = expand({_uid(seed)}, before_nodes, before_edges, mode=mode, hops=1)
        after = expand({_uid(seed)}, after_nodes, after_edges, mode=mode, hops=1)
        assert before == after == {_uid(key) for key in expected}


# ---------------------------------------------------------------- synonyms


def test_synonym_closure_is_transitive_and_free():
    """machine-learning ≡ ml ≡ mlops: identity never consumes a hop."""
    index, edges = _graph(
        _node("machine-learning"),
        _node("ml"),
        _node("mlops"),
        edges=(
            _edge("ml", "machine-learning", "synonym"),
            _edge("mlops", "ml", "synonym"),
        ),
    )
    assert expand({_uid("machine-learning")}, index, edges, mode="down", hops=1) == {
        _uid("machine-learning"),
        _uid("ml"),
        _uid("mlops"),
    }


def test_synonym_of_a_tree_child_of_the_seed_is_included():
    """Synonym identity applies to tree-discovered nodes too (plan 138 F-1).

    seed web-dev → curated child frontend → synonym front-end: the synonym
    is included at every hop budget, hops=0 included — identity is free.
    """
    index, edges = _graph(
        _node("web-dev"),
        _node("frontend", parent="web-dev"),
        _node("front-end"),
        edges=(_edge("frontend", "front-end", "synonym"),),
    )
    for hops in (0, 1, 2):
        reached = expand({_uid("web-dev")}, index, edges, mode="down", hops=hops)
        assert reached == {_uid("web-dev"), _uid("frontend"), _uid("front-end")}


def test_is_a_child_of_a_tree_discovered_node_is_included_at_the_same_hop_count():
    """Learned moves chain off tree-discovered nodes like off the seeds (F-2, (i)).

    react is_a frontend, and frontend hangs under web-dev in the curated
    tree: react is reached at hops=1 — the tree discovery is free, the
    learned edge costs its usual one hop, never hop+1 and never nothing.
    """
    index, edges = _graph(
        _node("web-dev"),
        _node("frontend", parent="web-dev"),
        _node("react"),
        edges=(_edge("react", "frontend", "is_a"),),
    )
    assert expand({_uid("web-dev")}, index, edges, mode="down", hops=1) == {
        _uid("web-dev"),
        _uid("frontend"),
        _uid("react"),
    }
    assert _uid("react") not in expand({_uid("web-dev")}, index, edges, mode="down", hops=0)


# ------------------------------------------------------------ related (opt-in)


def test_related_mode_adds_part_of_and_related_to():
    """typescript is only related_to javascript — never a synonym."""
    index, edges = _graph(
        _node("javascript"),
        _node("typescript"),
        _node("functional"),
        _node("haskell"),
        edges=(
            _edge("typescript", "javascript", "related_to"),
            _edge("haskell", "functional", "part_of"),
        ),
    )
    down = expand({_uid("javascript")}, index, edges, mode="down", hops=1)
    related = expand({_uid("javascript")}, index, edges, mode="related", hops=1)
    assert down == {_uid("javascript")}
    assert related == {_uid("javascript"), _uid("typescript")}

    part_of = expand({_uid("functional")}, index, edges, mode="related", hops=1)
    assert _uid("haskell") in part_of, "part_of walks component <- whole in related mode"


def test_related_edges_are_hop_capped():
    index, edges = _graph(
        _node("a"),
        _node("b"),
        _node("c"),
        edges=(
            _edge("a", "b", "related_to"),
            _edge("b", "c", "related_to"),
        ),
    )
    assert _uid("c") not in expand({_uid("a")}, index, edges, mode="related", hops=1)
    assert _uid("c") in expand({_uid("a")}, index, edges, mode="related", hops=2)


# ------------------------------------------------------------ corrupt safety


def test_corrupt_is_a_cycle_still_terminates():
    """Read-side visited set: even data that bypassed the write seam stops."""
    index, edges = _graph(
        _node("a"),
        _node("b"),
        edges=(
            _edge("a", "b", "is_a"),
            _edge("b", "a", "is_a"),
        ),
    )
    reached = expand({_uid("a")}, index, edges, mode="down", hops=2)
    assert reached == {_uid("a"), _uid("b")}


def test_corrupt_parent_cycle_still_terminates():
    index, edges = _graph(
        _node("a", parent="b"),
        _node("b", parent="a"),
    )
    reached = expand({_uid("a")}, index, edges, mode="down", hops=1)
    assert reached == {_uid("a"), _uid("b")}


# --------------------------------------------------------------- graph facade


def test_skill_graph_facade_expands_and_resolves_keys():
    graph = SkillGraph(
        nodes={node.id: node for node in (_node("programming"), _node("java"))},
        edges=(_edge("java", "programming", "is_a"),),
    )
    expanded = graph.expand({_uid("programming")}, mode="down", hops=1)
    assert graph.keys_for(expanded) == {"programming", "java"}
    assert graph.keys_for({uuid.uuid4()}) == set()
