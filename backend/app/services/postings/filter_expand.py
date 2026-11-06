"""Endpoint-seam graph expansion for the postings filter (plan 138, decision 11).

``filter_query.build_where`` is deliberately pure (no DB access, every axis
independently testable), so expansion happens one step earlier: the endpoint
resolves the selected keys against the graph, walks it, and hands
``build_where`` plain key lists as before.

Unknown keys pass through unexpanded — they resolve to no skill id and match
nothing, which is exactly what an unresolvable key meant before.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SkillExpandMode
from app.services.catalog.skill_graph import SkillGraph
from app.services.catalog.skill_relations import SkillRelationService
from app.services.postings.filter_spec import PostingFilterSpec


def _ordered_keys(keys: Iterable[str], expanded: set[UUID], graph: SkillGraph) -> list[str]:
    """Seed order first, then discovered keys sorted — stable and deduped."""
    ordered = list(keys)
    for key in sorted(graph.keys_for(expanded)):
        if key not in ordered:
            ordered.append(key)
    return ordered


def expand_keys(
    keys: list[str], graph: SkillGraph, *, mode: SkillExpandMode, hops: int
) -> list[str]:
    """Expand key slugs over an already-loaded graph."""
    if not keys or mode is SkillExpandMode.OFF:
        return keys
    key_to_id = {node.key: node.id for node in graph.nodes.values()}
    seeds = {key_to_id[key] for key in keys if key in key_to_id}
    expanded = graph.expand(seeds, mode=mode, hops=hops)
    return _ordered_keys(keys, expanded, graph)


async def expand_filter_spec(db: AsyncSession, spec: PostingFilterSpec) -> PostingFilterSpec:
    """Return a working copy whose skill keys are expanded over the graph.

    ``off`` and an empty skill axis are no-ops (no graph query at all).
    Exclusions always expand with ``down`` semantics: ``related`` is a
    precision-losing mode and must never widen what the user excluded.
    """
    skills = spec.skills
    if skills.expand is SkillExpandMode.OFF or not (skills.include or skills.exclude):
        return spec
    graph = await SkillRelationService(db).load_graph()
    if not graph.nodes:
        return spec
    include = expand_keys(skills.include, graph, mode=skills.expand, hops=skills.hops)
    exclude = expand_keys(skills.exclude, graph, mode=SkillExpandMode.DOWN, hops=skills.hops)
    return spec.model_copy(
        update={"skills": skills.model_copy(update={"include": include, "exclude": exclude})}
    )
