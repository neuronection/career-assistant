"""Pure expansion walk over the skill graph (plan 138, decision 3).

One small edge load plus an in-memory walk — never a recursive CTE: the
desktop profile runs SQLite and health-assistant's Postgres-only
``ARRAY``/``ANY`` traversal is deliberately not ported (plan §3.3/§3.9).
No closure table, no materialized paths, no cache: a few hundred skills and
a few thousand edges are the whole graph.

Semantics (precision contract) — one 0/1-cost walk (deque: free edges relax
at the front, hop edges at the back):

- Free, at every step and over everything already reached: synonym identity
  (transitive, both directions) and the curated ``parent_id`` subtree
  (full — curated ⇒ trusted; downward only; ``hops`` never bounds tree
  depth). A synonym of a tree-discovered node is included, a node's
  subtrees and synonyms apply whether it was a seed, learned or
  tree-discovered, and learned moves chain off tree-discovered nodes
  exactly like off the seeds.
- ``off`` — the seeds only (exact match).
- ``down`` — the free closure above plus hop-capped ``is_a`` children
  (``X is_a seed`` ⇒ include X at one hop). Learned edges are the only
  hop cost. Never upward: filtering "java" must not match every posting
  requiring "programming".
- ``related`` — ``down`` plus ``part_of``/``related_to`` walked in both
  directions, also hop-capped. Opt-in only.
- Unknown ids pass through unexpanded; a corrupt cycle still terminates
  (visited set).
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
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

    # One 0/1-cost walk: synonym identity and the curated subtree are free
    # (relax at the front, at every step, over everything reached so far);
    # the learned edges are the only hop cost (relax at the back) and chain
    # off tree-discovered and synonym nodes exactly like off the seeds. The
    # depth map is the visited set, so even corrupt cycles terminate.
    budget = _clamp_hops(hops)
    depth: dict[uuid.UUID, int] = dict.fromkeys(selected, 0)
    queue = deque(depth)
    while queue:
        skill_id = queue.popleft()
        cost = depth[skill_id]
        for neighbour in (*synonyms.get(skill_id, ()), *children.get(skill_id, ())):
            if neighbour not in depth:
                depth[neighbour] = cost
                queue.appendleft(neighbour)
        if cost < budget:
            for neighbour in moves.get(skill_id, ()):
                if neighbour not in depth:
                    depth[neighbour] = cost + 1
                    queue.append(neighbour)
    return set(depth)
