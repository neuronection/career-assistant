"""The single write seam for skill edges (plan 138, decision 5):
canonical ordering, matrix/vocabulary guards, cycles, negative edges."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.errors import NotFoundError, ValidationError
from app.models.enums import SkillRelationSource, SkillRelationStatus, SkillRelationType
from app.models.taxonomy_model import Skill, SkillRelation
from app.services.catalog.skill_relations import SkillRelationService


async def _skill(db, key: str, *, parent: Skill | None = None) -> Skill:
    skill = Skill(
        key=key,
        label=key.replace("-", " ").title(),
        category="test",
        parent_id=parent.id if parent else None,
    )
    db.add(skill)
    await db.flush()
    return skill


async def _edge_count(db) -> int:
    return (await db.execute(select(func.count()).select_from(SkillRelation))).scalar_one()


async def test_manual_and_import_edges_land_approved(db):
    svc = SkillRelationService(db)
    manual_a, manual_b = await _skill(db, "sr-manual-a"), await _skill(db, "sr-manual-b")
    import_a, import_b = await _skill(db, "sr-import-a"), await _skill(db, "sr-import-b")

    manual = await svc.add(manual_a.key, manual_b.key, "is_a")
    imported = await svc.add(import_a.key, import_b.key, "is_a", source=SkillRelationSource.IMPORT)
    assert (manual.status, manual.source) == ("approved", "manual")
    assert (imported.status, imported.source) == ("approved", "import")


async def test_ai_edges_land_proposed(db):
    svc = SkillRelationService(db)
    a, b = await _skill(db, "sr-llm-a"), await _skill(db, "sr-llm-b")
    derived_a, derived_b = await _skill(db, "sr-derived-a"), await _skill(db, "sr-derived-b")

    llm = await svc.add(a.key, b.key, "related_to", source="llm", confidence=0.72)
    derived = await svc.add(derived_a.key, derived_b.key, "related_to", source="derived")
    assert (llm.status, llm.source, llm.confidence) == ("proposed", "llm", 0.72)
    assert (derived.status, derived.source) == ("proposed", "derived")


async def test_symmetric_pairs_store_canonically_and_dedupe(db):
    svc = SkillRelationService(db)
    a, b = await _skill(db, "sr-sym-a"), await _skill(db, "sr-sym-b")

    edge = await svc.add(a.key, b.key, "synonym")
    assert str(edge.from_skill_id) <= str(edge.to_skill_id), "canonical endpoint order"

    again = await svc.add(b.key, a.key, "synonym")
    assert again.id == edge.id, "the reversed pair is the same row"
    assert await _edge_count(db) == 1


async def test_directed_pairs_keep_their_direction(db):
    svc = SkillRelationService(db)
    general, specific = await _skill(db, "sr-dir-general"), await _skill(db, "sr-dir-specific")

    edge = await svc.add(specific.key, general.key, "is_a")
    assert (edge.from_skill_id, edge.to_skill_id) == (specific.id, general.id)

    with pytest.raises(ValidationError, match="cycle"):
        await svc.add(general.key, specific.key, "is_a")


async def test_canonical_pair_matches_the_schema_ordering():
    for _ in range(20):
        first, second = uuid.uuid4(), uuid.uuid4()
        low, high = SkillRelationService._canonical_pair(first, second, SkillRelationType.SYNONYM)
        assert str(low) <= str(high), "schema CHECK compares the canonical text form"
        assert {low, high} == {first, second}
    low, high = SkillRelationService._canonical_pair(first, second, SkillRelationType.IS_A)
    assert (low, high) == (first, second), "directed kinds never reorder"


async def test_self_loop_is_rejected(db):
    svc = SkillRelationService(db)
    a = await _skill(db, "sr-loop-a")
    with pytest.raises(ValidationError, match="itself"):
        await svc.add(a.key, a.key, "related_to")


async def test_unknown_relation_and_unknown_skill_are_rejected(db):
    svc = SkillRelationService(db)
    a, b = await _skill(db, "sr-bad-a"), await _skill(db, "sr-bad-b")
    with pytest.raises(ValidationError, match="Unknown skill relation"):
        await svc.add(a.key, b.key, "brother_of")
    with pytest.raises(NotFoundError):
        await svc.add(a.key, "does-not-exist", "related_to")


async def test_rejected_edge_blocks_resuggestion_forever(db):
    svc = SkillRelationService(db)
    a, b = await _skill(db, "sr-neg-a"), await _skill(db, "sr-neg-b")

    proposed = await svc.add(a.key, b.key, "related_to", source="llm", confidence=0.4)
    rejected = await svc.reject(proposed.id)
    assert rejected.status == SkillRelationStatus.REJECTED.value
    assert rejected.decided_at is not None

    again = await svc.add(b.key, a.key, "related_to", source="llm", confidence=0.95)
    assert again.id == proposed.id, "the negative edge keeps its row"
    assert again.status == SkillRelationStatus.REJECTED.value
    assert await _edge_count(db) == 1


async def test_approve_stamps_the_reviewer_and_can_override_a_rejection(db, auth_headers):
    from tests.conftest import user_id_from_headers

    svc = SkillRelationService(db)
    a, b = await _skill(db, "sr-ok-a"), await _skill(db, "sr-ok-b")
    reviewer = user_id_from_headers(auth_headers)

    proposed = await svc.add(a.key, b.key, "is_a", source="llm")
    approved = await svc.approve(proposed.id, decided_by=reviewer)
    assert approved.status == SkillRelationStatus.APPROVED.value
    assert approved.decided_by == reviewer
    assert approved.decided_at is not None

    await svc.reject(approved.id, decided_by=reviewer)
    revived = await svc.approve(approved.id, decided_by=reviewer)
    assert revived.status == SkillRelationStatus.APPROVED.value, "explicit human override"


async def test_is_a_cycle_is_rejected(db):
    svc = SkillRelationService(db)
    java, jvm, programming = (
        await _skill(db, "sr-cyc-java"),
        await _skill(db, "sr-cyc-jvm"),
        await _skill(db, "sr-cyc-programming"),
    )
    await svc.add(java.key, jvm.key, "is_a")
    await svc.add(jvm.key, programming.key, "is_a")
    with pytest.raises(ValidationError, match="cycle"):
        await svc.add(programming.key, java.key, "is_a")


async def test_part_of_cycle_is_rejected(db):
    svc = SkillRelationService(db)
    wheel, car = await _skill(db, "sr-po-wheel"), await _skill(db, "sr-po-car")
    await svc.add(wheel.key, car.key, "part_of")
    with pytest.raises(ValidationError, match="cycle"):
        await svc.add(car.key, wheel.key, "part_of")


async def test_is_a_cycle_through_the_parent_tree_is_rejected(db):
    """The curated tree is part of the is_a axis — not a parallel universe."""
    svc = SkillRelationService(db)
    root = await _skill(db, "sr-tree-root")
    child = await _skill(db, "sr-tree-child", parent=root)
    with pytest.raises(ValidationError, match="cycle"):
        await svc.add(root.key, child.key, "is_a")


async def test_approve_rechecks_the_cycle(db):
    """A row written outside the seam must not become approved into a cycle."""
    svc = SkillRelationService(db)
    general, specific = await _skill(db, "sr-re-a"), await _skill(db, "sr-re-b")
    await svc.add(specific.key, general.key, "is_a")

    rogue = SkillRelation(
        from_skill_id=general.id,
        to_skill_id=specific.id,
        relation="is_a",
        status=SkillRelationStatus.PROPOSED.value,
        source=SkillRelationSource.LLM.value,
    )
    db.add(rogue)
    await db.commit()

    with pytest.raises(ValidationError, match="cycle"):
        await svc.approve(rogue.id)


async def test_remove_deletes_the_row(db):
    svc = SkillRelationService(db)
    a, b = await _skill(db, "sr-rm-a"), await _skill(db, "sr-rm-b")
    edge = await svc.add(a.key, b.key, "related_to")
    await svc.remove(edge.id)
    assert await _edge_count(db) == 0
    with pytest.raises(NotFoundError):
        await svc.remove(edge.id)


async def test_load_graph_returns_approved_edges_only(db):
    svc = SkillRelationService(db)
    a, b, c = (
        await _skill(db, "sr-graph-a"),
        await _skill(db, "sr-graph-b"),
        await _skill(db, "sr-graph-c"),
    )
    await svc.add(a.key, b.key, "is_a")
    await svc.add(b.key, c.key, "is_a", source="llm")

    graph = await svc.load_graph()
    assert {node.key for node in graph.nodes.values()} >= {"sr-graph-a", "sr-graph-b", "sr-graph-c"}
    assert [(edge.from_skill_id, edge.to_skill_id) for edge in graph.edges] == [(a.id, b.id)], (
        "proposals never widen a filter"
    )


async def test_matrix_rejects_relations_outside_the_endpoint_pair():
    from app.services.catalog.skill_relations import SKILL_LINK_MATRIX

    assert SKILL_LINK_MATRIX[("skill", "skill")] == frozenset(SkillRelationType)
    assert set(SKILL_LINK_MATRIX) == {("skill", "skill")}, "v1 has one endpoint kind"
