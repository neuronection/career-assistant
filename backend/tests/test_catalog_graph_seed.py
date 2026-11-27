"""Catalog seed relations: the graph constellation's data contract.

The catalog graph renders every job as a node and every typed relation as an
edge, so the shipped catalog pack has to stay a clean, connected graph:
unique typed triples, existing endpoints, no self-loops, and no job stranded
without a relation.
"""

from collections import Counter

import pytest

from tests.seed_pack_fixture import pack_items


def _jobs() -> tuple[dict, ...]:
    return pack_items("job_types/jobs.json")


def _relations() -> tuple[dict, ...]:
    return pack_items("job_relations/relations.json")


def _triples() -> Counter[tuple[str, str, str]]:
    return Counter((rel["from"], rel["to"], rel["type"]) for rel in _relations())


def test_catalog_keeps_its_known_shape() -> None:
    assert len(_jobs()) == 45
    assert len(_relations()) == 40


def test_relation_triples_are_unique() -> None:
    duplicated = [triple for triple, count in _triples().items() if count > 1]
    assert duplicated == []


def test_relation_endpoints_exist() -> None:
    codes = {job["code"] for job in _jobs()}
    dangling = [
        (rel["from"], rel["to"])
        for rel in _relations()
        if rel["from"] not in codes or rel["to"] not in codes
    ]
    assert dangling == []


def test_relations_have_no_self_loops() -> None:
    assert [rel["from"] for rel in _relations() if rel["from"] == rel["to"]] == []


def test_relation_weights_are_positive_and_bounded() -> None:
    assert all(0 < rel["weight"] <= 1 for rel in _relations())


@pytest.mark.parametrize("relation_type", ["similar_to", "leads_to", "alternative_to"])
def test_relation_types_are_canonical(relation_type: str) -> None:
    assert any(rel["type"] == relation_type for rel in _relations())


def test_sales_representative_is_similar_to_marketing_specialist() -> None:
    relation = {
        "from": "sales-representative",
        "to": "marketing-specialist",
        "type": "similar_to",
        "weight": 0.5,
    }
    assert relation in [
        {
            "from": rel["from"],
            "to": rel["to"],
            "type": rel["type"],
            "weight": rel["weight"],
        }
        for rel in _relations()
    ]


def test_no_job_is_isolated() -> None:
    connected = {rel["from"] for rel in _relations()}
    connected |= {rel["to"] for rel in _relations()}
    isolated = sorted(job["code"] for job in _jobs() if job["code"] not in connected)
    assert isolated == []


async def test_applying_the_catalog_pack_twice_is_idempotent(db, fixture_catalog) -> None:
    from app.services.seeds.applier import SeedApplyService

    result = await SeedApplyService(db, packs=fixture_catalog.store).apply(
        fixture_catalog.source, fixture_catalog.version
    )

    assert result.status == "noop"
