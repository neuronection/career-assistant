"""Pure expansion walk over the skill graph (plan 138, decision 3).

One small edge load plus an in-memory BFS — never a recursive CTE: the
desktop profile runs SQLite and health-assistant's Postgres-only
``ARRAY``/``ANY`` traversal is deliberately not ported (plan §3.3/§3.9).
No closure table, no materialized paths, no cache: a few hundred skills and
a few thousand edges are the whole graph.

Semantics (precision contract):

- ``off`` — the seeds only (exact match).
- ``down`` — the curated ``parent_id`` subtree (full, curated ⇒ trusted),
  synonym identity (always, both directions) and hop-capped ``is_a``
  children (``X is_a seed`` ⇒ include X). Never upward: filtering "java"
  must not match every posting requiring "programming".
- ``related`` — ``down`` plus ``part_of``/``related_to`` walked in both
  directions, also hop-capped. Opt-in only.
- Unknown ids pass through unexpanded; a corrupt cycle still terminates
  (visited set).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.models.enums import SkillExpandMode, SkillRelationType

DEFAULT_HOPS = 1
MAX_HOPS = 2


@dataclass(frozen=True)
class SkillNode:
    """One skill vertex: its id, stable key and display parent."""

    id: uuid.UUID
    key: str
    parent_id: uuid.UUID | None = None


@dataclass(frozen=True)
class SkillEdge:
    """One approved, directed row of ``skill_relations``."""

    from_skill_id: uuid.UUID
    to_skill_id: uuid.UUID
    relation: str


@dataclass(frozen=True)
class SkillGraph:
    """The whole catalog graph, loaded once per filter call."""

    nodes: Mapping[uuid.UUID, SkillNode]
    edges: tuple[SkillEdge, ...] = field(default_factory=tuple)

    def expand(
        self,
        seeds: Iterable[uuid.UUID],
        *,
        mode: str | SkillExpandMode = SkillExpandMode.DOWN,
        hops: int = DEFAULT_HOPS,
    ) -> set[uuid.UUID]:
        """Delegates to :func:`expand` with this graph's nodes and edges."""
        return expand(seeds, self.nodes, self.edges, mode=mode, hops=hops)

    def keys_for(self, ids: Iterable[uuid.UUID]) -> set[str]:
        """Known keys among ``ids`` (unknown ids simply resolve to nothing)."""
        return {self.nodes[skill_id].key for skill_id in ids if skill_id in self.nodes}


def _clamp_hops(hops: int) -> int:
    return max(0, min(int(hops), MAX_HOPS))


def _closure(
    seeds: Iterable[uuid.UUID], adjacency: Mapping[uuid.UUID, list[uuid.UUID]]
) -> set[uuid.UUID]:
    """Visited-set transitive closure over an undirected adjacency map."""
    reached = set(seeds)
    stack = list(reached)
    while stack:
        for neighbour in adjacency.get(stack.pop(), ()):
            if neighbour not in reached:
                reached.add(neighbour)
                stack.append(neighbour)
    return reached


def expand(
    seeds: Iterable[uuid.UUID],
    nodes: Mapping[uuid.UUID, SkillNode],
    edges: Iterable[SkillEdge],
    *,
    mode: str | SkillExpandMode = SkillExpandMode.DOWN,
    hops: int = DEFAULT_HOPS,
) -> set[uuid.UUID]:
    """Expand ``seeds`` downward over the skill graph.

    Args:
        seeds: Skill ids selected by the caller (unknown ids pass through).
        nodes: The catalog vertices, keyed by id.
        edges: Approved edges only — proposals must never widen a filter.
        mode: ``off`` | ``down`` | ``related``.
        hops: Relation hops for the learned edges (clamped to 0..2).

    Returns:
        The expanded id set, seeds included.
    """
    mode = SkillExpandMode(mode)
    selected = set(seeds)
    if mode is SkillExpandMode.OFF:
        return selected

    synonyms: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    children: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)
    moves: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    related = mode is SkillExpandMode.RELATED
    for edge in edges:
        if edge.relation == SkillRelationType.SYNONYM.value:
            synonyms[edge.from_skill_id].append(edge.to_skill_id)
            synonyms[edge.to_skill_id].append(edge.from_skill_id)
        elif edge.relation == SkillRelationType.IS_A.value:
            # specific -> general, so expansion walks the edge backwards.
            moves[edge.to_skill_id].append(edge.from_skill_id)
        elif related and edge.relation in (
            SkillRelationType.PART_OF.value,
            SkillRelationType.RELATED_TO.value,
        ):
            moves[edge.from_skill_id].append(edge.to_skill_id)
            moves[edge.to_skill_id].append(edge.from_skill_id)
    for node in nodes.values():
        children[node.parent_id].append(node.id)

    # Synonym identity is free (never consumes a hop).
    reached = _closure(selected, synonyms)
    frontier = set(reached)
    for _ in range(_clamp_hops(hops)):
        discovered = set()
        for skill_id in frontier:
            for neighbour in moves.get(skill_id, ()):
                if neighbour not in reached:
                    discovered.add(neighbour)
        discovered = _closure(discovered, synonyms) - reached
        if not discovered:
            break
        reached |= discovered
        frontier = discovered

    # The curated tree is trusted in full and only ever walked downward.
    stack = list(reached)
    while stack:
        for child in children.get(stack.pop(), ()):
            if child not in reached:
                reached.add(child)
                stack.append(child)
    return reached
