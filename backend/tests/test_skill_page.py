"""Plan 148 phase B — the skill page's read endpoints: positions (the
postings list projection, hidden excluded), the approved depth-1
subgraph, and the stats/merged_into additive fields on the detail."""

from uuid import uuid4

from sqlalchemy import select

from app.models.enums import SkillOrigin, SkillRelationSource
from app.models.taxonomy_model import Skill, SkillRelation
from app.services.catalog.skills_service import SkillService
from app.services.catalog.taxonomy_service import TaxonomyService
from tests.conftest import _add_posting_skill, _make_posting


async def _seed_skill(db, key: str, label: str, **kw) -> Skill:
    rows = await db.execute(select(Skill).where(Skill.key == key))
    skill = rows.scalars().first()
    if skill is not None:
        return skill
    skill = Skill(key=key, label=label, category="general", status="active", **kw)
    db.add(skill)
    await db.flush()
    return skill


async def _edge(db, a: Skill, b: Skill, relation: str, status: str = "approved") -> SkillRelation:
    lo, hi = sorted([a.id, b.id])
    directed = relation in {"is_a", "part_of"}
    row = SkillRelation(
        from_skill_id=a.id if directed else lo,
        to_skill_id=b.id if directed else hi,
        relation=relation,
        status=status,
        source=SkillRelationSource.MANUAL.value,
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------- positions


async def test_positions_returns_card_projection_excluding_hidden(
    db, client, auth_headers, seeded_catalog, source
):
    await _seed_skill(db, "sql", "SQL")
    a = await _make_posting(db, source, external_id="skl-a", title="Data A")
    b = await _make_posting(db, source, external_id="skl-b", title="Data B")
    hidden = await _make_posting(db, source, external_id="skl-h", title="Hidden One")
    await _add_posting_skill(db, a, "sql", 5, "must_have")
    await _add_posting_skill(db, b, "sql", 3, "nice_to_have")
    await _add_posting_skill(db, hidden, "sql", 4, "must_have")

    hidden.status = "hidden"
    await db.commit()

    resp = await client.get("/api/v1/skills/sql/positions", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2, "hidden postings never list"
    assert len(body["items"]) == 2
    titles = {item["title"] for item in body["items"]}
    assert titles == {"Data A", "Data B"}
    card = body["items"][0]
    assert card["ref"], "the card projection carries ref/title/status"
    assert card["status"] in ("new", "mapped")
    sql_refs = [ref for item in body["items"] for ref in item["skills"] if ref["key"] == "sql"]
    assert sql_refs, "the skills projection rides every row (cards render identically)"
    assert any(ref["required_level"] == 5 for ref in sql_refs)

    page = await client.get(
        "/api/v1/skills/sql/positions", headers=auth_headers, params={"limit": 1, "offset": 1}
    )
    assert page.status_code == 200
    assert len(page.json()["items"]) == 1
    assert page.json()["total"] == 2


async def test_positions_404s_and_requires_auth(client, auth_headers):
    resp = await client.get("/api/v1/skills/nowhere/positions")
    assert resp.status_code == 401
    resp = await client.get("/api/v1/skills/nowhere/positions", headers=auth_headers)
    assert resp.status_code == 404


# ----------------------------------------------------------------- relations


async def test_relations_returns_approved_depth1_only(db, client, auth_headers, seeded_catalog):
    focus = await _seed_skill(db, "sql", "SQL")
    parent = await _seed_skill(db, "query-lang", "Query Language")
    sibling = await _seed_skill(db, "nosql", "NoSQL")
    other = await _seed_skill(db, "cooking", "Cooking")

    await _edge(db, parent, focus, "is_a")
    await _edge(db, focus, sibling, "related_to")
    await _edge(db, focus, other, "synonym", status="proposed")
    await _edge(db, sibling, other, "related_to", status="rejected")

    resp = await client.get("/api/v1/skills/sql/relations", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    node_keys = {node["key"] for node in body["nodes"]}
    assert node_keys == {"sql", "query-lang", "nosql"}, "focus + approved neighbors only"
    assert len(body["edges"]) == 2
    assert all(edge["relation"] in ("is_a", "related_to") for edge in body["edges"])
    focus_node = next(node for node in body["nodes"] if node["key"] == "sql")
    assert focus_node["status"] == "active"
    assert focus_node["label"] == "SQL"

    await _seed_skill(db, "lonely-skill", "Lonely")
    resp = await client.get("/api/v1/skills/lonely-skill/relations", headers=auth_headers)
    body = resp.json()
    assert [node["key"] for node in body["nodes"]] == ["lonely-skill"]
    assert body["edges"] == []


async def test_relations_404s(db, client, auth_headers):
    resp = await client.get("/api/v1/skills/nowhere/relations", headers=auth_headers)
    assert resp.status_code == 404


# --------------------------------------------------------------------- stats


async def test_detail_stats_aggregate_and_merged_banner(
    db, client, auth_headers, seeded_catalog, source
):
    await _seed_skill(db, "sql", "SQL")
    a = await _make_posting(db, source, external_id="st-a", title="Stat A")
    b = await _make_posting(db, source, external_id="st-b", title="Stat B")
    await _add_posting_skill(db, a, "sql", 4, "must_have")
    await _add_posting_skill(db, b, "sql", 6, "bonus")

    resp = await client.get("/api/v1/skills/sql", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    stats = body["stats"]
    assert stats["demand_count"] == 2
    assert stats["level_histogram"] == [
        {"level": 4, "n": 1},
        {"level": 6, "n": 1},
    ]
    assert stats["avg_required_level"] == 5.0
    assert stats["user_count"] >= 0
    assert stats["corroboration"] is None, "bank-origin rows carry no corroboration"
    assert body["merged_into"] is None


async def test_detail_stats_hidden_postings_never_count(
    db, client, auth_headers, seeded_catalog, source
):
    await _seed_skill(db, "sql", "SQL")
    posting = await _make_posting(db, source, external_id="st-h", title="Hidden Stat")
    await _add_posting_skill(db, posting, "sql", 7, "must_have")

    posting.status = "hidden"
    await db.commit()

    resp = await client.get("/api/v1/skills/sql", headers=auth_headers)
    stats = resp.json()["stats"]
    assert stats["demand_count"] == 0
    assert stats["level_histogram"] == []
    assert stats["avg_required_level"] is None
    assert stats["first_seen"] is None and stats["last_seen"] is None


async def test_detail_corroboration_and_merged_into_render(
    db, client, auth_headers, seeded_catalog
):
    service = SkillService(db)
    proposed, created = await service.propose(
        "corrob-skill", label="Corrob Skill", origin=SkillOrigin.AI
    )
    assert created
    proposed.provenance = {
        "posting_id": str(uuid4()),
        "corroborated_postings": [str(uuid4()), str(uuid4())],
    }
    await db.commit()

    resp = await client.get("/api/v1/skills/corrob-skill", headers=auth_headers)
    assert resp.json()["stats"]["corroboration"] == {"postings": 3}, "origin + distinct"

    survivor = await _seed_skill(db, "sql", "SQL")
    dup = await _seed_skill(db, "sql-dup", "SQL Dup")
    await TaxonomyService(db).merge(dup.id, survivor.id)
    resp = await client.get("/api/v1/skills/sql-dup", headers=auth_headers)
    body = resp.json()
    assert body["merged_into"] == "sql", "the banner target resolves to the survivor key"
    assert body["status"] == "deprecated"
