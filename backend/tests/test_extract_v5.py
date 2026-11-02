"""Plan 153 slice 3 — the extract v5 cutover: pass 1 emits verbatim raw
labels, alias-index exact hits resolve without the LLM, remaining labels
ride ONE batched pass-2 call whose verdicts apply directly, twin labels
corroborate on one row, the dedup gate blocks near-duplicate promotions,
and `mode: "resolve"` replay re-resolves stored labels without pass-1
spend."""

from sqlalchemy import select

import app.services.postings.extract_service as extract_service
from app.ai.agents.skill_resolver import SkillLabelVerdict, SkillResolution
from app.core.errors import AINotConfiguredError
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType, SkillOrigin
from app.models.posting_model import PostingChange, PostingSkill
from app.models.taxonomy_model import Skill
from app.services.postings.extract_service import (
    EXTRACT_VERSION,
    extract_posting_now,
    run_extract_job,
)
from tests.conftest import _make_posting


async def _resolve_calls(db) -> int:
    rows = await db.execute(
        select(AIGeneration).where(AIGeneration.task_type == AITaskType.POSTING_SKILL_RESOLVE.value)
    )
    return len(rows.scalars().all())


async def _extract_calls(db) -> int:
    rows = await db.execute(
        select(AIGeneration).where(AIGeneration.task_type == AITaskType.POSTING_EXTRACT.value)
    )
    return len(rows.scalars().all())


# ------------------------------------------------------- exact hits + pass 2


async def test_exact_hits_resolve_without_pass2(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source)
    result = await extract_posting_now(db, posting)
    assert result["extracted"] is True

    assert await _resolve_calls(db) == 0, "alias-index exact hits skip the pass-2 call"
    await db.refresh(posting)
    entries = (posting.extract or {}).get("skills") or []
    assert entries
    assert all(entry["raw_label"] and entry["skill_key"] for entry in entries), (
        "v5 entries carry BOTH the verbatim label and the stamped key"
    )
    edges = (
        (await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id)))
        .scalars()
        .all()
    )
    assert all(edge.required_level is not None for edge in edges)
    assert all(edge.priority in ("must_have", "nice_to_have", "bonus") for edge in edges)


async def test_fuzzy_label_resolves_via_pass2(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    posting = await _make_posting(
        db,
        source,
        external_id="fuzzy-1",
        skills_raw=["programmer"],
        raw={"description": "A strong programmer joins the platform team."},
    )
    result = await extract_posting_now(db, posting)
    assert result["extracted"] is True

    assert await _resolve_calls(db) == 1, "exactly one batched pass-2 call"
    await db.refresh(posting)
    entry = (posting.extract or {}).get("skills")[0]
    assert entry["raw_label"] == "programmer"
    assert entry["skill_key"] == "programming", "the adjudicated verdict tags the posting"
    programming = (
        (await db.execute(select(Skill).where(Skill.key == "programming"))).scalars().first()
    )
    edge = (
        (
            await db.execute(
                select(PostingSkill).where(
                    PostingSkill.posting_id == posting.id,
                    PostingSkill.skill_id == programming.id,
                )
            )
        )
        .scalars()
        .first()
    )
    assert edge is not None and edge.required_level == entry["required_level"]


async def test_invented_key_degrades_to_new_proposal(
    db, client, auth_headers, seeded_catalog, source, kinds, monkeypatch
):
    """A verdict naming a key outside the offered candidates is filtered
    by the resolver seam (§8) — the label lands as a proposal, and no
    invented row is ever tagged."""

    async def _invented(db, task, schema, system, user, **kwargs):
        return SkillResolution(
            verdicts=[
                SkillLabelVerdict(
                    label_ref="0",
                    match_key="ghost-key",
                    new=False,
                    confidence=0.9,
                    rationale="invented key",
                )
            ],
            bounded=False,
        )

    monkeypatch.setattr("app.ai.agents.skill_resolver.ainvoke_structured", _invented)
    posting = await _make_posting(
        db,
        source,
        external_id="invent-1",
        skills_raw=["programmer"],
        raw={"description": "A strong programmer joins the platform team."},
    )
    await extract_posting_now(db, posting)
    await db.refresh(posting)

    entry = (posting.extract or {}).get("skills")[0]
    assert entry["skill_key"] is None, "the off-candidate key degraded to new"
    proposed = (await db.execute(select(Skill).where(Skill.key == "programmer"))).scalars().first()
    assert proposed is not None and proposed.status == "proposed"
    edges = (
        (await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id)))
        .scalars()
        .all()
    )
    assert not edges, "an invented key never tags the posting"


async def test_unconfigured_pass2_degrades_to_proposals(
    db, client, auth_headers, seeded_catalog, source, kinds, monkeypatch
):
    """No provider for the resolve task: every remaining label proposes
    deterministically — the extract itself never fails."""

    async def _unconfigured(*args, **kwargs):
        raise AINotConfiguredError("AI is not configured yet")

    monkeypatch.setattr("app.ai.agents.skill_resolver.resolve_skills", _unconfigured)
    posting = await _make_posting(
        db,
        source,
        external_id="noai-1",
        skills_raw=["programmer"],
        raw={"description": "A strong programmer joins the platform team."},
    )
    result = await extract_posting_now(db, posting)
    assert result["extracted"] is True
    await db.refresh(posting)
    entry = (posting.extract or {}).get("skills")[0]
    assert entry["skill_key"] is None
    proposed = (await db.execute(select(Skill).where(Skill.key == "programmer"))).scalars().first()
    assert proposed is not None and proposed.status == "proposed"


# ------------------------------------------------- corroboration on one row


async def test_twin_labels_corroborate_on_one_row(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    """The fragmentation fix: a fuzzy twin label resolves onto the SAME
    proposed ai-origin row (pass 2 over proposed candidates) — the
    corroboration count accrues there and auto-promotes after the
    extract commit."""
    first = await _make_posting(
        db,
        source,
        external_id="twin-1",
        title="Container Engineer",
        skills_raw=["docker"],
        raw={"description": "We deploy everything with docker."},
    )
    await extract_posting_now(db, first)
    proposed = (await db.execute(select(Skill).where(Skill.key == "docker"))).scalars().first()
    assert proposed is not None and proposed.status == "proposed"

    second = await _make_posting(
        db,
        source,
        external_id="twin-2",
        title="Fleet Ops",
        skills_raw=["dockers"],
        raw={"description": "Dockers run on every host."},
    )
    await extract_posting_now(db, second)

    await db.refresh(proposed)
    assert proposed.status == "active", "twin labels corroborate the one row into promotion"
    assert proposed.provenance["auto_promoted"]["postings"] == 2
    assert proposed.provenance["corroborated_postings"] == [str(second.id)]
    twins = (
        (await db.execute(select(Skill).where(Skill.key.in_(["docker", "dockers"]))))
        .scalars()
        .all()
    )
    assert len(twins) == 1, "no second proposal for the near-duplicate label"
    edge = (
        (
            await db.execute(
                select(PostingSkill).where(
                    PostingSkill.posting_id == second.id,
                    PostingSkill.skill_id == proposed.id,
                )
            )
        )
        .scalars()
        .first()
    )
    assert edge is not None, "matches onto proposed rows tag the posting"


# ----------------------------------------------------------- the dedup gate


async def test_dedup_gate_blocks_and_stamps(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    """An ACTIVE near-duplicate above the bars keeps the row proposed and
    stamps `auto_promote_blocked` (near, scores, at) — never auto-merged."""
    seed_a = await _make_posting(
        db,
        source,
        external_id="gate-a",
        title="Team Lead",
        skills_raw=["Leaderships"],
        raw={"description": "Show Leaderships skills every day."},
    )
    seed_b = await _make_posting(
        db,
        source,
        external_id="gate-b",
        title="Mentor",
        skills_raw=["Leaderships"],
        raw={"description": "Leaderships matter when guiding teams."},
    )
    await db.flush()
    proposed = Skill(
        key="leaderships",
        label="Leaderships",
        category="test",
        status="proposed",
        origin=SkillOrigin.AI.value,
        provenance={
            "posting_id": str(seed_a.id),
            "corroborated_postings": [str(seed_b.id)],
            "extract_version": EXTRACT_VERSION,
            "required_level": 4,
            "priority": "must_have",
        },
    )
    db.add(proposed)
    await db.commit()
    await db.refresh(proposed)

    third = await _make_posting(
        db,
        source,
        external_id="gate-c",
        title="Coach",
        skills_raw=["Leaderships"],
        raw={"description": "Leaderships grow through practice."},
    )
    await extract_posting_now(db, third)

    await db.refresh(proposed)
    assert proposed.status == "proposed", "the active near-duplicate blocks promotion"
    blocked = proposed.provenance["auto_promote_blocked"]
    assert blocked["near"]["key"] == "leadership"
    assert blocked["scores"]["signal"] == "trigram"
    assert blocked["scores"]["score"] >= 0.75
    assert blocked["at"]
    assert "auto_promoted" not in proposed.provenance
    assert proposed.provenance["corroborated_postings"] == [str(seed_b.id), str(third.id)]
    entry = next(
        entry
        for entry in (third.extract or {}).get("skills")
        if entry["raw_label"] == "Leaderships"
    )
    assert entry["skill_key"] == "leaderships", "the proposed target still tags the posting"


# ------------------------------------------------------------------- replay


async def test_replay_after_merge_reresolves_without_pass1(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    posting = await _make_posting(
        db,
        source,
        external_id="replay-1",
        skills_raw=["programming"],
        raw={"description": "We need programming daily for the platform."},
    )
    await extract_posting_now(db, posting)
    await db.refresh(posting)
    assert posting.extract_version == EXTRACT_VERSION

    before_extract, before_pass2 = await _extract_calls(db), await _resolve_calls(db)

    merged = (await db.execute(select(Skill).where(Skill.key == "programming"))).scalars().first()
    target = (
        (await db.execute(select(Skill).where(Skill.key == "problem-solving"))).scalars().first()
    )
    from app.services.catalog.taxonomy_service import TaxonomyService

    await TaxonomyService(db).merge(merged.id, target.id)

    result = await run_extract_job(db, {"posting_id": str(posting.id), "mode": "resolve"})
    assert result.get("replayed") is True
    assert await _extract_calls(db) == before_extract, "replay never re-pays pass 1"
    assert await _resolve_calls(db) == before_pass2, "absorbed aliases re-resolve exactly"

    await db.refresh(posting)
    assert posting.extract_version == EXTRACT_VERSION
    by_label = {
        entry["raw_label"]: entry["skill_key"] for entry in (posting.extract or {})["skills"]
    }
    assert by_label["programming"] == "problem-solving", "the merge redirect re-resolved"
    edge = (
        (
            await db.execute(
                select(PostingSkill).where(
                    PostingSkill.posting_id == posting.id,
                    PostingSkill.skill_id == target.id,
                )
            )
        )
        .scalars()
        .first()
    )
    assert edge is not None, "the re-resolved label tags the surviving skill"

    rows = await db.execute(
        select(PostingChange)
        .where(PostingChange.posting_id == posting.id, PostingChange.actor_kind == "extract_llm")
        .order_by(PostingChange.occurred_at, PostingChange.id)
    )
    journal = rows.scalars().all()
    assert journal[-1].operation == {"replay": True, "extract_version": EXTRACT_VERSION}
    assert journal[-1].diff["skills"]["added"] == ["problem-solving"]


async def test_replay_reresolves_through_pass2_when_the_exact_claim_is_gone(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    """Replay is a full re-resolution: a stored label that lost its exact
    index claim rides candidate match + pass 2 again (one audited call)."""
    posting = await _make_posting(
        db,
        source,
        external_id="replay-2",
        title="Fleet Ops",
        skills_raw=["dockers"],
        raw={"description": "Dockers run on every host."},
    )
    await extract_posting_now(db, posting)
    await db.refresh(posting)
    dockers = (await db.execute(select(Skill).where(Skill.key == "dockers"))).scalars().first()
    assert dockers is not None and dockers.status == "proposed"

    before_pass2 = await _resolve_calls(db)
    from app.services.catalog.taxonomy_service import TaxonomyService

    await TaxonomyService(db).delete_skill(dockers.id)
    db.add(Skill(key="docker", label="Docker", category="test", status="active"))
    await db.commit()

    result = await run_extract_job(db, {"posting_id": str(posting.id), "mode": "resolve"})
    assert result.get("replayed") is True
    assert await _resolve_calls(db) == before_pass2 + 1, "exactly one pass-2 call on replay"

    await db.refresh(posting)
    entry = (posting.extract or {}).get("skills")[0]
    assert entry["raw_label"] == "dockers"
    assert entry["skill_key"] == "docker", "the pass-2 verdict re-resolved the orphaned label"
    docker = (await db.execute(select(Skill).where(Skill.key == "docker"))).scalars().first()
    edge = (
        (
            await db.execute(
                select(PostingSkill).where(
                    PostingSkill.posting_id == posting.id,
                    PostingSkill.skill_id == docker.id,
                )
            )
        )
        .scalars()
        .first()
    )
    assert edge is not None


async def test_replay_skips_without_replayable_labels(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source)
    posting.extract_version = 4
    posting.extract = {
        "skills": [
            {
                "skill_key": "programming",
                "raw_label": None,
                "required_level": 4,
                "priority": "must_have",
                "evidence_quote": "we need programming",
                "confidence": 0.9,
            }
        ],
        "_suppressed_fields": [],
    }
    await db.commit()
    result = await run_extract_job(db, {"posting_id": str(posting.id), "mode": "resolve"})
    assert result == {"skipped": "no replayable labels"}
    assert await _extract_calls(db) == 0


async def test_v4_row_reextracts_on_demand(db, client, auth_headers, seeded_catalog, source, kinds):
    posting = await _make_posting(db, source)
    posting.extract_version = 4
    posting.extract = {
        "skills": [
            {
                "skill_key": "programming",
                "raw_label": None,
                "required_level": 4,
                "priority": "must_have",
                "evidence_quote": "we need programming",
                "confidence": 0.9,
            }
        ],
        "_suppressed_fields": [],
    }
    await db.commit()
    result = await run_extract_job(db, {"posting_id": str(posting.id)})
    assert result.get("extracted") is True
    await db.refresh(posting)
    assert posting.extract_version == EXTRACT_VERSION
    entries = (posting.extract or {}).get("skills") or []
    assert entries and all(entry.get("raw_label") for entry in entries)


# --------------------------------------------------------- commit boundaries


async def test_auto_promote_runs_after_the_extract_journal(
    db, client, auth_headers, seeded_catalog, source, kinds, monkeypatch
):
    """The corroborated promotion fires only after the apply transaction's
    journal exists — the extract journal + data stay one commit boundary,
    promotion commits on its own terms."""
    real_promote = extract_service._auto_promote
    journal_of: dict = {}
    seen: list[bool] = []

    async def _spy(db, skill, count, _thresholds):
        rows = await db.execute(
            select(PostingChange).where(
                PostingChange.posting_id == journal_of["posting_id"],
                PostingChange.actor_kind == "extract_llm",
            )
        )
        seen.append(rows.scalars().first() is not None)
        await real_promote(db, skill, count, _thresholds)

    monkeypatch.setattr(extract_service, "_auto_promote", _spy)

    first = await _make_posting(
        db,
        source,
        external_id="order-1",
        title="Container Engineer",
        skills_raw=["docker"],
        raw={"description": "We deploy everything with docker."},
    )
    await extract_posting_now(db, first)
    second = await _make_posting(
        db,
        source,
        external_id="order-2",
        title="Fleet Ops",
        skills_raw=["dockers"],
        raw={"description": "Dockers run on every host."},
    )
    journal_of["posting_id"] = second.id
    await extract_posting_now(db, second)
    assert seen == [True], "promotion started only after the extract journal was written"


# ------------------------------------------------------------ admin variant


async def test_admin_reextract_grows_the_resolve_variant(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().first()
    user.is_admin = True
    await db.commit()

    posting = await _make_posting(db, source)
    await extract_posting_now(db, posting)
    await db.refresh(posting)
    assert posting.extract_version == EXTRACT_VERSION

    replayed = await client.post(
        f"/api/v1/admin/postings/{posting.id}/extract",
        json={"mode": "resolve"},
        headers=auth_headers,
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replayed"] is True

    full = await client.post(f"/api/v1/admin/postings/{posting.id}/extract", headers=auth_headers)
    assert full.status_code == 200, full.text
    assert full.json()["extracted"] is True
