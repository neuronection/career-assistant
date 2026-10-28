"""Admin skill-relations surface (plan 138, step 6): the review queue
listing, manual add/edit/remove, accept/dismiss actions, the thresholds
override and the run ledger — every write through the single seam."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobType, SkillRelationStatus
from app.models.taxonomy_model import Skill, SkillRelation
from app.services.catalog.skill_relations import SkillRelationService
from tests.conftest import session_headers


@pytest.fixture
async def _admin_and_user(client, db):
    """First user = admin, second = regular. Returns (admin_headers, user_headers)."""
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "relations-admin@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201
    admin = session_headers(first)
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "relations-user@example.com", "password": "supersecret1"},
    )
    assert second.status_code == 201
    return admin, session_headers(second)


async def _seed_skills(db, *keys: str) -> dict[str, Skill]:
    skills = {
        key: Skill(key=key, label=key.replace("-", " ").title(), category="test") for key in keys
    }
    db.add_all(skills.values())
    await db.flush()
    return skills


async def _rows(db) -> list[SkillRelation]:
    rows = await db.execute(select(SkillRelation).execution_options(populate_existing=True))
    return list(rows.scalars().all())


async def test_admin_surface_requires_admin(client, _admin_and_user):
    admin, user = _admin_and_user
    assert (await client.get("/api/v1/admin/skill-relations")).status_code == 401
    assert (await client.get("/api/v1/admin/skill-relations", headers=user)).status_code == 403
    assert (
        await client.put(
            "/api/v1/admin/skill-relations/thresholds",
            json={
                "min_support": 2,
                "batch_size": 40,
                "max_pairs_per_run": 200,
                "min_negative_confidence": 0.6,
            },
            headers=user,
        )
    ).status_code == 403
    assert (await client.get("/api/v1/admin/skill-relations", headers=admin)).status_code == 200


async def test_list_relations_grain_filters_and_pair_facts(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    skills = await _seed_skills(db, "java", "programming", "jvm-languages")
    skills["java"].provenance = {"evidence_quote": "Java and Spring required"}
    await db.flush()
    service = SkillRelationService(db)
    await service.add("java", "programming", "is_a", source="llm", confidence=0.9)
    await service.add("java", "jvm-languages", "is_a", source="manual")
    await service.add("java", "programming", "synonym", status="rejected", source="llm")

    listing = (await client.get("/api/v1/admin/skill-relations", headers=admin)).json()
    assert len(listing) == 3, "one row per (pair, relation)"
    by_kind = {(row["relation"], row["status"]): row for row in listing}
    assert set(by_kind) == {("is_a", "proposed"), ("is_a", "approved"), ("synonym", "rejected")}
    proposed = by_kind[("is_a", "proposed")]
    assert proposed["confidence"] == 0.9
    assert proposed["from_skill"]["key"] == "java"
    assert proposed["from_skill"]["evidence_quote"] == "Java and Spring required"
    assert proposed["to_skill"]["key"] == "programming"
    assert proposed["alias_candidate"] is False

    only_proposed = (
        await client.get("/api/v1/admin/skill-relations?status=proposed", headers=admin)
    ).json()
    assert {row["relation"] for row in only_proposed} == {"is_a"}
    assert all(row["status"] == "proposed" for row in only_proposed)

    bounded = (
        await client.get("/api/v1/admin/skill-relations", params={"limit": 2}, headers=admin)
    ).json()
    assert len(bounded) == 2, "the listing is bounded — newest first"
    assert bounded[0]["id"] != bounded[1]["id"]

    for_skill = (
        await client.get(
            "/api/v1/admin/skill-relations",
            params={"skill_id": str(skills["jvm-languages"].id)},
            headers=admin,
        )
    ).json()
    assert [row["to_skill"]["key"] for row in for_skill] == ["jvm-languages"]


async def test_alias_candidate_marks_proposed_label_pairs(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    skills = await _seed_skills(db, "js", "javascript")
    skills["js"].status = "proposed"
    await db.flush()
    service = SkillRelationService(db)
    await service.add("js", "javascript", "synonym", source="llm", confidence=0.7)

    listing = (await client.get("/api/v1/admin/skill-relations", headers=admin)).json()
    assert listing[0]["alias_candidate"] is True


async def test_manual_add_creates_an_approved_row(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    await _seed_skills(db, "java", "programming")
    response = await client.post(
        "/api/v1/admin/skill-relations",
        json={
            "from_skill": "java",
            "to_skill": "programming",
            "relation": "is_a",
            "confidence": 1.0,
        },
        headers=admin,
    )
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["status"] == "approved", "admin-curated edges land approved"
    assert row["source"] == "manual"
    assert row["decided_by"] is not None

    multi = await client.post(
        "/api/v1/admin/skill-relations",
        json={"from_skill": "java", "to_skill": "programming", "relation": "related_to"},
        headers=admin,
    )
    assert multi.status_code == 201
    assert len(await _rows(db)) == 2, "multi-relation rows per pair are possible"


async def test_manual_add_refreshes_confidence_instead_of_duplicating(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    await _seed_skills(db, "java", "programming")
    payload = {"from_skill": "java", "to_skill": "programming", "relation": "is_a"}
    await client.post("/api/v1/admin/skill-relations", json=payload, headers=admin)
    again = await client.post(
        "/api/v1/admin/skill-relations",
        json={**payload, "confidence": 0.4},
        headers=admin,
    )
    assert again.status_code == 201
    rows = await _rows(db)
    assert len(rows) == 1
    assert rows[0].confidence == 0.4


async def test_accept_approves_and_runs_the_tree_catch_up(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    skills = await _seed_skills(db, "java", "programming")
    service = SkillRelationService(db)
    edge = await service.add("java", "programming", "is_a", source="llm", confidence=0.9)
    assert edge.status == "proposed"

    response = await client.post(f"/api/v1/admin/skill-relations/{edge.id}/accept", headers=admin)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["decided_by"] is not None

    await db.refresh(skills["java"])
    assert skills["java"].parent_id == skills["programming"].id, (
        "an accepted is_a catches the tree up immediately"
    )


async def test_accept_refuses_a_cycle_and_leaves_the_row_proposed(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    skills = await _seed_skills(db, "a", "b")
    service = SkillRelationService(db)
    edge = await service.add("a", "b", "is_a", source="llm", confidence=0.9)
    skills["b"].parent_id = skills["a"].id
    await db.flush()

    response = await client.post(f"/api/v1/admin/skill-relations/{edge.id}/accept", headers=admin)
    assert response.status_code == 400
    assert "cycle" in response.text

    rows = await _rows(db)
    assert rows[0].status == SkillRelationStatus.PROPOSED.value, "the row survives the refusal"


async def test_dismiss_writes_the_negative_edge(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    await _seed_skills(db, "java", "programming")
    service = SkillRelationService(db)
    edge = await service.add("java", "programming", "is_a", source="llm", confidence=0.2)

    response = await client.post(f"/api/v1/admin/skill-relations/{edge.id}/dismiss", headers=admin)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "rejected"
    assert body["decided_by"] is not None

    rows = await _rows(db)
    assert rows[0].status == SkillRelationStatus.REJECTED.value
    reloaded = await service.list_relations(status="rejected")
    assert len(reloaded) == 1


async def test_remove_deletes_the_row(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    await _seed_skills(db, "java", "programming")
    service = SkillRelationService(db)
    edge = await service.add("java", "programming", "is_a", source="manual")

    response = await client.delete(f"/api/v1/admin/skill-relations/{edge.id}", headers=admin)
    assert response.status_code == 204
    assert await _rows(db) == []
    missing = await client.delete(f"/api/v1/admin/skill-relations/{edge.id}", headers=admin)
    assert missing.status_code == 404


async def test_thresholds_round_trip_and_bounds(db, client, _admin_and_user):
    from app.ai.agents.skill_relation_suggest import MAX_PAIRS_PER_CALL

    admin, _ = _admin_and_user
    defaults = (await client.get("/api/v1/admin/skill-relations/thresholds", headers=admin)).json()
    assert defaults == {
        "min_support": 2,
        "batch_size": MAX_PAIRS_PER_CALL,
        "max_pairs_per_run": 200,
        "min_negative_confidence": 0.6,
    }

    saved = await client.put(
        "/api/v1/admin/skill-relations/thresholds",
        json={
            "min_support": 5,
            "batch_size": 10,
            "max_pairs_per_run": 50,
            "min_negative_confidence": 0.8,
        },
        headers=admin,
    )
    assert saved.status_code == 200, saved.text
    reread = (await client.get("/api/v1/admin/skill-relations/thresholds", headers=admin)).json()
    assert (
        reread
        == saved.json()
        == {
            "min_support": 5,
            "batch_size": 10,
            "max_pairs_per_run": 50,
            "min_negative_confidence": 0.8,
        }
    )

    over_cap = await client.put(
        "/api/v1/admin/skill-relations/thresholds",
        json={
            "min_support": 1,
            "batch_size": MAX_PAIRS_PER_CALL + 1,
            "max_pairs_per_run": 1,
            "min_negative_confidence": 0.5,
        },
        headers=admin,
    )
    assert over_cap.status_code == 422, "batch_size is clamped to the per-call cap"

    over_confidence = await client.put(
        "/api/v1/admin/skill-relations/thresholds",
        json={
            "min_support": 1,
            "batch_size": 1,
            "max_pairs_per_run": 1,
            "min_negative_confidence": 1.5,
        },
        headers=admin,
    )
    assert over_confidence.status_code == 422


async def test_runs_ledger_renders_and_handles_null_watermark(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    newer = datetime.now(UTC)
    older = newer - timedelta(hours=1)
    db.add_all(
        [
            BackgroundJob(
                job_type=BackgroundJobType.SKILL_RELATION_LEARN.value,
                status="succeeded",
                payload={},
                created_at=older,
                result={
                    "materialized": 2,
                    "backfilled": 1,
                    "candidates": 3,
                    "capped": True,
                    "watermark": None,
                },
            ),
            BackgroundJob(
                job_type=BackgroundJobType.SKILL_RELATION_LEARN.value,
                status="failed",
                payload={},
                created_at=newer,
                result={"candidates": 7, "watermark": "2026-10-28T00:00:00+00:00"},
            ),
            BackgroundJob(
                job_type=BackgroundJobType.DIGEST.value,
                status="succeeded",
                payload={},
                created_at=newer,
                result={"watermark": None},
            ),
        ]
    )
    await db.flush()

    runs = (await client.get("/api/v1/admin/skill-relations/runs", headers=admin)).json()
    assert len(runs) == 2, "only discovery runs"
    first, second = runs
    assert first["status"] == "failed", "newest first"
    assert first["ledger"]["watermark"] == "2026-10-28T00:00:00+00:00"
    assert second["ledger"]["watermark"] is None, "a capped/failed run renders a null watermark"
    assert second["ledger"]["candidates"] == 3
    assert second["ledger"]["capped"] is True
    assert second["ledger"]["backfilled"] == 1
    assert first["ledger"]["backfilled"] == 0, "an old ledger without the counter renders 0"
    assert set(second["ledger"].keys()) >= {
        "candidates",
        "batches",
        "judged_batches",
        "failed_batches",
        "uncovered",
        "derived",
        "edges_proposed",
        "negatives",
        "dropped",
        "below_bar",
        "materialized",
        "backfilled",
        "capped",
        "watermark",
    }


async def test_run_ledger_renders_junk_counters_as_defaults():
    from app.schemas.skill_relations import SkillRelationRunLedgerOut

    ledger = SkillRelationRunLedgerOut.from_result(
        {"candidates": True, "capped": "yes", "watermark": 7, "batches": 2}
    )
    assert ledger.candidates == 0, "a bool never passes as a counter"
    assert ledger.capped is False
    assert ledger.watermark is None
    assert ledger.batches == 2


# --------------------------------------------- alias-add path (decision 6)


async def test_save_alias_merges_the_label_row_and_writes_the_negative_edge(
    db, client, _admin_and_user
):
    admin, _ = _admin_and_user
    skills = await _seed_skills(db, "js", "javascript")
    skills["js"].status = "proposed"
    skills["js"].provenance = {"evidence_quote": "JS and React required"}
    await db.flush()
    service = SkillRelationService(db)
    edge = await service.add("js", "javascript", "synonym", source="llm", confidence=0.7)

    response = await client.post(
        f"/api/v1/admin/skill-relations/{edge.id}/save-alias", headers=admin
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target"]["key"] == "javascript"
    assert "js" in body["aliases"], "the label lands on the surviving skill's aliases"
    assert body["relation"]["status"] == "rejected", "the edge is dismissed — the negative edge"

    db.expire_all()
    rows = await _rows(db)
    assert rows[0].status == SkillRelationStatus.REJECTED.value
    assert rows[0].decided_by is not None
    merged_away = (await db.execute(select(Skill).where(Skill.key == "js"))).scalars().first()
    assert merged_away.status == "deprecated", "the label row is merged away"


async def test_save_alias_makes_the_matcher_resolve_the_label(db, client, _admin_and_user):
    """§7 "js" label / javascript row: after the alias save the matcher
    resolves the label to the surviving skill — no edge needed."""
    from app.services.catalog.skills_service import SkillService
    from app.services.postings.postings_service import _taxonomy_index

    admin, _ = _admin_and_user
    skills = await _seed_skills(db, "js", "javascript")
    skills["js"].status = "proposed"
    await db.flush()
    service = SkillRelationService(db)
    edge = await service.add("js", "javascript", "synonym", source="llm", confidence=0.7)
    await client.post(f"/api/v1/admin/skill-relations/{edge.id}/save-alias", headers=admin)
    db.expire_all()

    resolved = await SkillService(db).resolve("js")
    assert resolved is not None
    assert resolved.key == "javascript", "the deprecated label row no longer shadows the alias"
    merged_away = (await db.execute(select(Skill).where(Skill.key == "js"))).scalars().first()
    index = await _taxonomy_index(db)
    assert merged_away.id not in index.values(), "a merged-away label row never shadows the matcher"
    assert index["javascript"] == skills["javascript"].id


async def test_matcher_index_deprecated_fallback_never_shadows_active(db):
    """F1 pin 2: deprecated rows fill only tokens no active row claimed —
    a deprecated key/label never shadows an active row's key/label/alias."""
    from app.services.postings.postings_service import _taxonomy_index

    skills = await _seed_skills(db, "modern", "legacy-one", "old-e")
    skills["legacy-one"].status = "deprecated"
    skills["old-e"].status = "deprecated"
    skills["old-e"].label = "Modern"
    skills["modern"].aliases = ["legacy-one", "Legacy One"]
    await db.flush()

    index = await _taxonomy_index(db)

    assert index["legacy-one"] == skills["modern"].id, "an active alias beats a deprecated key"
    assert index["legacy one"] == skills["modern"].id, "an active alias beats a deprecated label"
    assert index["modern"] == skills["modern"].id, "a deprecated label never shadows an active key"
    assert skills["legacy-one"].id not in index.values(), (
        "a row shadowed on every token contributes nothing (the merged-away shape)"
    )
    assert index["old-e"] == skills["old-e"].id, "the fallback still fills unmatched tokens"


async def test_matchers_agree_on_the_deprecated_exact_key_fallback(db):
    """F1: `SkillService.resolve` and the postings index answer the same
    deprecated exact-key fallback when no active row claims the token."""
    from app.services.catalog.skills_service import SkillService
    from app.services.postings.postings_service import _taxonomy_index

    skills = await _seed_skills(db, "javascript", "jsx")
    skills["jsx"].status = "deprecated"
    await db.flush()

    resolved = await SkillService(db).resolve("jsx")
    assert resolved is not None and resolved.id == skills["jsx"].id

    index = await _taxonomy_index(db)
    assert index["jsx"] == skills["jsx"].id
    assert index["javascript"] == skills["javascript"].id


async def test_save_alias_works_on_a_dismissed_label_row(db, client, _admin_and_user):
    """Even after a `none` verdict pinned the pair, the label can still be
    saved as the alias it really is."""
    admin, _ = _admin_and_user
    skills = await _seed_skills(db, "js", "javascript")
    skills["js"].status = "proposed"
    await db.flush()
    service = SkillRelationService(db)
    edge = await service.add(
        "js", "javascript", "synonym", source="llm", status="rejected", confidence=0.9
    )

    response = await client.post(
        f"/api/v1/admin/skill-relations/{edge.id}/save-alias", headers=admin
    )
    assert response.status_code == 200, response.text
    assert "js" in response.json()["aliases"]


async def test_save_alias_requires_a_proposed_label_pair(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    await _seed_skills(db, "java", "programming")
    service = SkillRelationService(db)
    edge = await service.add("java", "programming", "synonym", source="llm", confidence=0.7)

    denied = await client.post(f"/api/v1/admin/skill-relations/{edge.id}/save-alias", headers=admin)
    assert denied.status_code == 400, "two active skills are not an alias candidate"

    await service.approve(edge.id)
    denied = await client.post(f"/api/v1/admin/skill-relations/{edge.id}/save-alias", headers=admin)
    assert denied.status_code == 400, "an approved edge is not an alias candidate"


async def test_save_alias_on_an_approved_edge_recommends_dismiss_not_delete(
    db, client, _admin_and_user
):
    """F7: the hint names the working path — dismissing keeps the row
    handle save-alias needs; removing destroys it."""
    admin, _ = _admin_and_user
    skills = await _seed_skills(db, "js", "javascript")
    skills["js"].status = "proposed"
    await db.flush()
    service = SkillRelationService(db)
    edge = await service.add("js", "javascript", "synonym", source="llm", confidence=0.7)
    await service.approve(edge.id)

    denied = await client.post(f"/api/v1/admin/skill-relations/{edge.id}/save-alias", headers=admin)

    assert denied.status_code == 400
    detail = str(denied.json()["detail"]).lower()
    assert "dismiss" in detail, "dismiss first is the working path"
    assert "remove" not in detail, "removing the row destroys the handle save-alias needs"


async def test_admin_dismiss_blocks_the_pair_from_the_next_collection(db, client, _admin_and_user):
    """F8 bridge: a dismissal through the admin endpoint settles the pair
    — the next collection never re-suggests it (the real entry points:
    collect → verdict application → dismiss → collect)."""
    from app.ai.agents.skill_relation_suggest import SkillEdgeVerdict
    from app.services.catalog.skill_relation_learn import (
        Thresholds,
        apply_verdicts,
        collect_candidates,
    )
    from tests.test_skill_relation_learn import _tagged_postings

    admin, _ = _admin_and_user
    skills = await _seed_skills(db, "c-sharp", "java")
    await _tagged_postings(
        db,
        skills,
        [("p-1", ("c-sharp", "java")), ("p-2", ("c-sharp", "java"))],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    assert len(candidates) == 1, "the pair is suggested before any adjudication"

    await apply_verdicts(
        db,
        candidates,
        [
            SkillEdgeVerdict(
                pair_ref=candidates[0].pair_ref,
                relation="related_to",
                confidence=0.8,
                rationale="Frequently co-occurring languages.",
            )
        ],
    )
    row = (await _rows(db))[0]
    assert row.status == SkillRelationStatus.PROPOSED.value

    response = await client.post(f"/api/v1/admin/skill-relations/{row.id}/dismiss", headers=admin)
    assert response.status_code == 200, response.text

    again, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    assert again == [], "a dismissed pair is never re-suggested"
