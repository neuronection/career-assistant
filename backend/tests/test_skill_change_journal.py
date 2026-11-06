"""Plan 148 — the skill change journal: seam units (diff shapes, caps,
empty-diff gate, params-not-content) plus one integration test per
instrumented writer and the history read endpoint."""

from uuid import uuid4

from sqlalchemy import select

from app.models.enums import SkillChangeActor, SkillEventKind, SkillOrigin
from app.models.taxonomy_model import SkillChange
from app.services.catalog.skill_change_journal import (
    DIFF_STRING_CAP,
    SkillChangeJournal,
    compute_diff,
)
from app.services.catalog.skills_service import SkillService
from app.services.catalog.taxonomy_service import TaxonomyService


async def _events(db, key: str) -> list[SkillChange]:
    rows = await db.execute(
        select(SkillChange)
        .where(SkillChange.skill_key == key)
        .order_by(SkillChange.occurred_at, SkillChange.id)
    )
    return list(rows.scalars().all())


# ------------------------------------------------------------------ units


def test_diff_add_change_remove_shapes():
    diff = compute_diff(
        {"label": "Old", "category": "general"},
        {"label": "New", "category": "general", "description": "d"},
    )
    assert diff == {
        "label": {"from": "Old", "to": "New"},
        "description": {"from": None, "to": "d"},
    }


def test_diff_caps_long_strings_with_marker():
    payload = "x" * 5000
    diff = compute_diff({"label": "short"}, {"label": payload})
    assert diff["label"]["to"] == "x" * DIFF_STRING_CAP + "…"
    assert len(diff["label"]["to"]) == DIFF_STRING_CAP + 1


def test_diff_normalizes_uuids_and_lists():
    parent = uuid4()
    diff = compute_diff(
        {"parent_id": None, "aliases": ["b", "a"]},
        {"parent_id": parent, "aliases": ["a", "b"]},
    )
    assert diff["parent_id"] == {"from": None, "to": str(parent)}
    assert diff["aliases"] == {
        "from": '["b","a"]',
        "to": '["a","b"]',
    }, "alias order is display order — a reorder is a change"


async def test_empty_diff_records_nothing(db):
    service = TaxonomyService(db)
    skill = await service.create_skill({"key": "noop-skill", "label": "Noop"})
    assert await _events(db, "noop-skill")

    before = {f: getattr(skill, f) for f in ("label", "category")}
    skill.label = skill.label
    SkillChangeJournal.record_snapshot_change(
        db,
        skill,
        before,
        {f: getattr(skill, f) for f in ("label", "category")},
        SkillEventKind.UPDATED,
        SkillChangeActor.ADMIN,
    )
    await db.commit()
    events = await _events(db, "noop-skill")
    assert [e.event for e in events] == ["created"], "the no-op update wrote no row"


# ------------------------------------------------------------- seam routes


async def test_admin_seams_journal_their_events(db):
    service = TaxonomyService(db)
    skill = await service.create_skill({"key": "hist-skill", "label": "Hist"})
    await service.update_skill(skill.id, {"description": "Now described"})
    await service.update_skill(skill.id, {"status": "deprecated"})
    await service.update_skill(skill.id, {"status": "active"})

    events = await _events(db, "hist-skill")
    kinds = [(e.event, e.actor_kind) for e in events]
    assert kinds == [
        ("created", "admin"),
        ("updated", "admin"),
        ("deprecated", "admin"),
        ("restored", "admin"),
    ]
    updated = events[1]
    assert updated.detail["description"] == {"from": "", "to": "Now described"}
    deprecated = events[2]
    assert deprecated.detail["status"] == {"from": "active", "to": "deprecated"}
    assert events[0].actor_ref is None, "no actor id passed — role only"


async def test_promote_and_auto_promote_journal_from_one_seam(db):
    service = TaxonomyService(db)
    proposed, _ = await SkillService(db).propose(
        "auto-prom", label="Auto Prom", origin=SkillOrigin.AI
    )
    await db.commit()

    promoted = await service.promote(proposed.id, auto=True, detail={"postings": 3})
    events = await _events(db, "auto-prom")
    assert [e.event for e in events] == ["created", "auto_promoted"]
    assert events[-1].actor_kind == "job"
    assert events[-1].detail == {"postings": 3}
    assert promoted.status == "active"

    admin_promoted, _ = await SkillService(db).propose(
        "admin-prom", label="Admin Prom", origin=SkillOrigin.USER
    )
    await db.commit()
    await service.promote(admin_promoted.id, actor_ref={"user_id": "u-1"})
    events = await _events(db, "admin-prom")
    assert [e.event for e in events] == ["created", "promoted"]
    assert events[-1].actor_kind == "admin"
    assert events[-1].actor_ref == {"user_id": "u-1"}


async def test_merge_journals_both_sides(db):
    service = TaxonomyService(db)
    survivor = await service.create_skill({"key": "merge-target", "label": "Target"})
    dup = await service.create_skill({"key": "merge-source", "label": "Dup"})
    await service.merge(dup.id, survivor.id, actor_ref={"user_id": "u-2"})

    target_events = await _events(db, "merge-target")
    source_events = await _events(db, "merge-source")
    assert target_events[-1].event == "merged"
    assert target_events[-1].detail == {"absorbed": "merge-source"}
    assert source_events[-1].event == "merged"
    assert source_events[-1].detail == {
        "merged_into": "merge-target",
        "target_id": str(survivor.id),
    }


async def test_delete_journals_and_survives(db):
    service = TaxonomyService(db)
    skill = await service.create_skill({"key": "doomed-skill", "label": "Doomed"})
    await service.delete_skill(skill.id, actor_ref={"user_id": "u-3"})

    rows = (
        (await db.execute(select(SkillChange).where(SkillChange.skill_key == "doomed-skill")))
        .scalars()
        .all()
    )
    assert [r.event for r in rows] == ["created", "deleted"]
    assert all(r.skill_id is None for r in rows), "ON DELETE SET NULL kept the trail"
    assert {r.skill_label for r in rows} == {"Doomed"}, "snapshot renders post-delete"


async def test_propose_journals_created_by_origin(db):
    service = SkillService(db)
    _skill, created = await service.propose(
        "self-typed", label="Self Typed", origin=SkillOrigin.USER
    )
    assert created
    _ai_skill, ai_created = await service.propose(
        "ai-coined", label="AI Coined", origin=SkillOrigin.AI
    )
    assert ai_created
    await db.commit()

    mine = await _events(db, "self-typed")
    assert [(e.event, e.actor_kind) for e in mine] == [("created", "user")]
    ai = await _events(db, "ai-coined")
    assert [(e.event, e.actor_kind) for e in ai] == [("created", "job")]

    _again, second = await service.propose(
        "self-typed", label="Self Typed", origin=SkillOrigin.USER
    )
    assert not second
    await db.commit()
    assert len(await _events(db, "self-typed")) == 1, "find-or-propose dedups the journal"


async def test_tree_maintenance_journals_system(db):
    service = TaxonomyService(db)
    parent = await service.create_skill({"key": "tree-parent", "label": "Parent"})
    child = await service.create_skill({"key": "tree-child", "label": "Child"})
    from app.models.enums import SkillParentSource

    await service.update_skill(
        child.id,
        {"parent_id": parent.id},
        only_if_parent_empty=True,
        parent_source=SkillParentSource.LEARNED,
    )
    events = await _events(db, "tree-child")
    fill = events[-1]
    assert fill.actor_kind == "system"
    assert fill.detail["parent_id"]["to"] == str(parent.id)

    await service.heal_learned_placement(child.id)
    events = await _events(db, "tree-child")
    heal = events[-1]
    assert heal.actor_kind == "system"
    assert heal.detail["parent_id"] == {"from": str(parent.id), "to": None}


# ---------------------------------------------------------------- read API


async def test_history_endpoint_paginated_newest_first(db, client, auth_headers):
    service = TaxonomyService(db)
    skill = await service.create_skill({"key": "page-skill", "label": "Page"})
    await service.update_skill(skill.id, {"label": "Page II"})
    await service.update_skill(skill.id, {"status": "deprecated"})

    resp = await client.get("/api/v1/skills/page-skill/history", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3 == len(body["items"])
    assert body["skill_key"] == "page-skill"
    assert [entry["event"] for entry in body["items"]] == [
        "deprecated",
        "updated",
        "created",
    ], "newest first"
    entry = body["items"][0]
    assert entry["actor_kind"] == "admin"
    assert entry["detail"]["status"]["to"] == "deprecated"

    page = await client.get(
        "/api/v1/skills/page-skill/history",
        headers=auth_headers,
        params={"limit": 1, "offset": 1},
    )
    assert page.status_code == 200
    assert len(page.json()["items"]) == 1
    assert page.json()["items"][0]["id"] != entry["id"]
    assert page.json()["total"] == 3


async def test_history_endpoint_scoped_and_404s(client, auth_headers):
    resp = await client.get("/api/v1/skills/nowhere-skill/history")
    assert resp.status_code == 401, "the read is user-scoped like the postings one"
    resp = await client.get("/api/v1/skills/nowhere-skill/history", headers=auth_headers)
    assert resp.status_code == 404
