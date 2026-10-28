"""Skill-relation discovery job (plan 138, step 5).

Deterministic candidate generation (co-occurrence, proposed-label
matching, parent-chain materialization), batched verdict application
through the write seam (the §7 corpus pairs as named expected-edge /
expected-non-edge tests), the negative-edge blocks-resuggestion loop, the
unconfigured-AI derived fallback, batch caps, delta watermark and
idempotent re-tick.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from app.ai.agents.skill_relation_suggest import (
    MAX_PAIRS_PER_CALL,
    SkillEdgeVerdict,
    SkillEdgeVerdictSet,
)
from app.models.background_job_model import BackgroundJob
from app.models.enums import (
    BackgroundJobType,
    ScheduleKind,
    SkillRelationSource,
    SkillRelationStatus,
    SkillRelationType,
    SkillStatus,
)
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting, JobSource, PostingSkill
from app.models.schedule_model import Schedule
from app.models.settings_model import AppSetting
from app.models.taxonomy_model import Skill, SkillRelation
from app.services.catalog.skill_relation_learn import (
    Thresholds,
    apply_verdicts,
    backfill_parent_edges,
    collect_candidates,
    load_thresholds,
    materialize_parent_edges,
    run_skill_relation_learn,
)
from app.services.catalog.skill_relations import SkillRelationService


def _now() -> datetime:
    return datetime.now(UTC)


def _skill(key: str, **fields) -> Skill:
    fields.setdefault("label", key.replace("-", " ").title())
    fields.setdefault("category", "test")
    return Skill(key=key, **fields)


async def _seed(db, *skills: Skill) -> dict[str, Skill]:
    db.add_all(skills)
    await db.flush()
    return {skill.key: skill for skill in skills}


async def _tagged_postings(db, skills: dict[str, Skill], rows: list[tuple[str, tuple[str, ...]]]):
    source = JobSource(
        key=f"learn-{uuid.uuid4().hex[:8]}",
        connector_key="synthetic",
        kind="posting",
        config={},
    )
    db.add(source)
    await db.flush()
    postings = {}
    for external_id, keys in rows:
        posting = JobPosting(
            source_id=source.id,
            external_id=external_id,
            title=external_id,
            org="TestCo",
            content_hash=f"{external_id}-hash",
        )
        db.add(posting)
        await db.flush()
        for key in keys:
            db.add(PostingSkill(posting_id=posting.id, skill_id=skills[key].id, required_level=5))
        postings[external_id] = posting
    await db.flush()
    return postings


async def _tagged_jobs(db, skills: dict[str, Skill], rows: list[tuple[str, tuple[str, ...]]]):
    family = JobFamily(key=f"learn-fam-{uuid.uuid4().hex[:8]}", label="Learn")
    db.add(family)
    await db.flush()
    for code, keys in rows:
        job = Job(code=f"{code}-{uuid.uuid4().hex[:6]}", title=code, family_id=family.id)
        db.add(job)
        await db.flush()
        for key in keys:
            db.add(JobSkill(job_id=job.id, skill_id=skills[key].id, required_level=5))
    await db.flush()


async def _relation_rows(db) -> list[SkillRelation]:
    return list((await db.execute(select(SkillRelation))).scalars().all())


async def _set_thresholds(db, **values):
    db.add(AppSetting(key="skill_relation_learn.thresholds", value=dict(values)))
    await db.flush()


class _CallSpy:
    """Wrapper around the agent call that records batch sizes and can fail."""

    def __init__(self, real, fail_on: set[int] | None = None):
        self.real = real
        self.fail_on = fail_on or set()
        self.sizes: list[int] = []

    async def __call__(self, db, pairs, **kwargs):
        self.sizes.append(len(pairs))
        if len(self.sizes) in self.fail_on:
            return None
        return await self.real(db, pairs, **kwargs)


def _spy(monkeypatch, fail_on: set[int] | None = None):
    from app.services.catalog import skill_relation_learn as learn

    spy = _CallSpy(learn.suggest_skill_edges, fail_on=fail_on)
    monkeypatch.setattr(learn, "suggest_skill_edges", spy)
    return spy


# -------------------------------------------------------------- thresholds


async def test_thresholds_defaults_and_clamping(db):
    assert await load_thresholds(db) == Thresholds()
    await _set_thresholds(
        db,
        min_support=0,
        batch_size=500,
        max_pairs_per_run=-3,
        min_negative_confidence=2.0,
    )
    thresholds = await load_thresholds(db)
    assert thresholds.min_support == 1
    assert thresholds.batch_size == MAX_PAIRS_PER_CALL
    assert thresholds.max_pairs_per_run == 1
    assert thresholds.min_negative_confidence == 1.0


async def test_thresholds_ignore_invalid_values(db):
    await _set_thresholds(db, min_support="junk", batch_size=None, min_negative_confidence=[])
    thresholds = await load_thresholds(db)
    assert thresholds == Thresholds()


def test_verdict_set_bounds_the_batch():
    with pytest.raises(PydanticValidationError):
        SkillEdgeVerdictSet(
            verdicts=[
                SkillEdgeVerdict(
                    pair_ref=f"p{i}",
                    relation="none",
                    confidence=0.5,
                    rationale="x",
                )
                for i in range(MAX_PAIRS_PER_CALL + 1)
            ]
        )


# ------------------------------------------------------ candidate generation


async def test_candidates_cooccurrence_min_support_ranking_and_signals(db):
    skills = await _seed(
        db,
        _skill("java"),
        _skill("python"),
        _skill("sql"),
        _skill("docker"),
    )
    await _tagged_postings(
        db,
        skills,
        [
            ("c-1", ("java", "python")),
            ("c-2", ("java", "python")),
            ("c-3", ("java", "sql")),
        ],
    )
    await _tagged_jobs(db, skills, [("c-job", ("java", "python"))])

    candidates, capped = await collect_candidates(db, since=None, thresholds=Thresholds())

    assert not capped
    assert [(c.first.key, c.second.key) for c in candidates] == [("java", "python")]
    candidate = candidates[0]
    assert candidate.hypothesis is SkillRelationType.RELATED_TO
    assert candidate.signals["cooccurrence"] == {"postings": 2, "jobs": 1}
    assert candidate.pair_ref == "p1"


async def test_candidates_exclude_pair_level_adjudicated_pairs(db):
    skills = await _seed(
        db,
        _skill("java"),
        _skill("python"),
        _skill("c-sharp"),
        _skill("javascript"),
    )
    await _tagged_postings(
        db,
        skills,
        [
            ("x-1", ("java", "python", "c-sharp", "javascript")),
            ("x-2", ("java", "python", "c-sharp", "javascript")),
        ],
    )
    service = SkillRelationService(db)
    await service.add("java", "python", "related_to", source="llm")
    await service.add("java", "c-sharp", "synonym", status="rejected")
    await service.add("python", "javascript", "is_a", source="import")

    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())

    pairs = {(c.first.key, c.second.key) for c in candidates}
    assert pairs == {
        ("java", "javascript"),
        ("c-sharp", "python"),
        ("c-sharp", "javascript"),
    }, "pair-level adjudication hides every pair carrying any row"


async def test_candidates_label_equality_and_initialism(db):
    await _seed(
        db,
        _skill("machine-learning", label="Machine Learning"),
        _skill("javascript", label="JavaScript", aliases=["JS"]),
        _skill(
            "ml",
            label="ML",
            status=SkillStatus.PROPOSED.value,
            origin="ai",
            provenance={"evidence_quote": "ML required"},
        ),
        _skill(
            "js",
            label="JS",
            status=SkillStatus.PROPOSED.value,
            origin="ai",
            provenance={"evidence_quote": "JS daily"},
        ),
        _skill("noisy", label="Noisy", status=SkillStatus.PROPOSED.value, origin="user"),
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())

    pairs = {(c.first.key, c.second.key) for c in candidates}
    assert pairs == {("machine-learning", "ml"), ("javascript", "js")}
    by_pair = {(c.first.key, c.second.key): c for c in candidates}
    assert by_pair[("machine-learning", "ml")].hypothesis is SkillRelationType.SYNONYM
    assert by_pair[("machine-learning", "ml")].signals["label_match"] == {"kind": "initialism"}
    assert by_pair[("javascript", "js")].signals["label_match"] == {"kind": "equal"}


async def test_initialism_ignores_single_character_keys(db):
    from app.services.catalog.skill_relation_learn import _initialism_match

    await _seed(
        db,
        _skill("machine-learning", label="Machine Learning"),
        _skill(
            "m",
            label="M",
            status=SkillStatus.PROPOSED.value,
            origin="ai",
            provenance={"evidence_quote": "M required"},
        ),
    )

    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())

    assert candidates == []
    assert not _initialism_match({"m"}, {"machine learning"})
    assert _initialism_match({"ml"}, {"machine learning"})


async def test_label_candidates_re_emerge_when_the_matching_skill_arrives(db):
    skills = await _seed(
        db,
        _skill("machine-learning", label="Machine Learning"),
        _skill(
            "ml",
            label="ML",
            status=SkillStatus.PROPOSED.value,
            origin="ai",
            provenance={"evidence_quote": "ML required"},
        ),
    )
    skills["ml"].created_at = _now() - timedelta(hours=3)
    await db.flush()

    candidates, _ = await collect_candidates(
        db, since=_now() - timedelta(hours=1), thresholds=Thresholds()
    )

    assert [(c.first.key, c.second.key) for c in candidates] == [("machine-learning", "ml")], (
        "label matches are existence-bound: a skill created after the run still pairs up"
    )


async def test_candidates_co_tag_adjacency_reaches_unrelated_strings(db):
    skills = await _seed(
        db,
        _skill("kubernetes", label="Kubernetes"),
        _skill("k8s", label="K8s", status=SkillStatus.PROPOSED.value, origin="ai"),
    )
    postings = await _tagged_postings(db, skills, [("k-1", ("kubernetes",))])
    skills["k8s"].provenance = {
        "posting_id": str(postings["k-1"].id),
        "evidence_quote": "k8s clusters daily",
    }
    await db.flush()

    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())

    assert [(c.first.key, c.second.key) for c in candidates] == [("k8s", "kubernetes")]
    assert candidates[0].hypothesis is SkillRelationType.SYNONYM
    assert candidates[0].signals["label_match"] == {"kind": "co_tag"}


async def test_parent_chain_materialization_is_idempotent_and_respects_negatives(db):
    skills = await _seed(
        db,
        _skill("programming"),
        _skill("java", parent_id=None),
        _skill("databases"),
        _skill("sql"),
    )
    skills["java"].parent_id = skills["programming"].id
    skills["sql"].parent_id = skills["databases"].id
    await db.flush()
    service = SkillRelationService(db)
    await service.add("sql", "databases", "is_a", status="rejected")

    assert await materialize_parent_edges(db) == 1
    assert await materialize_parent_edges(db) == 0

    rows = await _relation_rows(db)
    edges = {(r.relation, r.status, r.source) for r in rows}
    assert (SkillRelationType.IS_A.value, SkillRelationStatus.APPROVED.value, "import") in edges
    rejected = [r for r in rows if r.status == SkillRelationStatus.REJECTED.value]
    assert len(rejected) == 1
    assert {str(rejected[0].from_skill_id), str(rejected[0].to_skill_id)} == {
        str(skills["sql"].id),
        str(skills["databases"].id),
    }


async def test_reparenting_rejects_stale_import_mirrors_and_writes_new(db):
    skills = await _seed(db, _skill("programming"), _skill("java"), _skill("databases"))
    skills["java"].parent_id = skills["programming"].id
    await db.flush()

    assert await materialize_parent_edges(db) == 1

    skills["java"].parent_id = skills["databases"].id
    await db.flush()
    assert await materialize_parent_edges(db) == 1

    rows = await _relation_rows(db)
    by_pair = {(str(r.from_skill_id), str(r.to_skill_id)): r for r in rows}
    old = by_pair[(str(skills["java"].id), str(skills["programming"].id))]
    new = by_pair[(str(skills["java"].id), str(skills["databases"].id))]
    assert old.status == SkillRelationStatus.REJECTED.value, "the stale mirror is rejected"
    assert new.status == SkillRelationStatus.APPROVED.value
    assert new.source == SkillRelationSource.IMPORT.value
    assert await materialize_parent_edges(db) == 0


# -------------------------------------------- tree catch-up (plan 138, step 7)


async def test_backfill_fills_only_empty_parents_and_is_idempotent(db):
    skills = await _seed(
        db,
        _skill("programming"),
        _skill("jvm-languages"),
        _skill("java"),
        _skill("databases"),
        _skill("sql"),
    )
    skills["sql"].parent_id = skills["databases"].id
    await db.flush()
    service = SkillRelationService(db)
    await service.add("java", "jvm-languages", "is_a", source="manual")
    await service.add("jvm-languages", "programming", "is_a", source="manual")
    await service.add("sql", "programming", "is_a", source="manual")

    assert await backfill_parent_edges(db) == 2

    assert skills["java"].parent_id == skills["jvm-languages"].id
    assert skills["jvm-languages"].parent_id == skills["programming"].id
    assert skills["programming"].parent_id is None
    assert skills["sql"].parent_id == skills["databases"].id, "a filled parent is never re-parented"
    assert await backfill_parent_edges(db) == 0


async def test_backfill_prefers_the_highest_scored_is_a_target(db):
    """§7 multi-parent java: both expansion paths stay, but `parent_id`
    gets exactly one display parent — the highest-confidence target."""
    skills = await _seed(db, _skill("java"), _skill("programming"), _skill("jvm-languages"))
    service = SkillRelationService(db)
    weak = await service.add("java", "programming", "is_a", source="llm", confidence=0.6)
    strong = await service.add("java", "jvm-languages", "is_a", source="llm", confidence=0.9)
    await service.approve(weak.id)
    await service.approve(strong.id)

    assert await backfill_parent_edges(db) == 1

    assert skills["java"].parent_id == skills["jvm-languages"].id


async def test_backfill_unscored_rows_never_outrank_a_scored_one(db):
    """NULL confidence is "not scored" — never fabricated into a number
    that could win the comparison."""
    skills = await _seed(db, _skill("java"), _skill("programming"), _skill("jvm-languages"))
    service = SkillRelationService(db)
    await service.add("java", "programming", "is_a", source="manual")
    scored = await service.add("java", "jvm-languages", "is_a", source="llm", confidence=0.2)
    await service.approve(scored.id)

    assert await backfill_parent_edges(db) == 1

    assert skills["java"].parent_id == skills["jvm-languages"].id


async def test_backfill_unscored_ties_fall_to_curation_then_age(db):
    skills = await _seed(
        db,
        _skill("alpha"),
        _skill("beta"),
        _skill("gamma"),
        _skill("delta"),
    )
    service = SkillRelationService(db)
    manual = await service.add("alpha", "beta", "is_a", source="manual")
    learned = await service.add("alpha", "gamma", "is_a", source="llm")
    older = await service.add("delta", "beta", "is_a", source="llm")
    newer = await service.add("delta", "gamma", "is_a", source="llm")
    for row in (learned, older, newer):
        await service.approve(row.id)
    manual.created_at = _now()
    learned.created_at = _now() - timedelta(days=1)
    older.created_at = _now() - timedelta(days=1)
    newer.created_at = _now()
    await db.commit()

    assert await backfill_parent_edges(db) == 2

    assert skills["alpha"].parent_id == skills["beta"].id, (
        "curation beats age — the manual edge wins even though it is newer"
    )
    assert skills["delta"].parent_id == skills["beta"].id, "equal rows fall to the earliest edge"


async def test_backfill_skips_a_cycle_candidate_and_tries_the_next(db):
    skills = await _seed(db, _skill("a"), _skill("b"), _skill("c"))
    service = SkillRelationService(db)
    await service.add("a", "b", "is_a", source="manual", confidence=0.9)
    await service.add("a", "c", "is_a", source="manual", confidence=0.5)
    skills["b"].parent_id = skills["a"].id
    await db.flush()

    assert await backfill_parent_edges(db) == 1

    assert skills["a"].parent_id == skills["c"].id, (
        "the cycle guard skips b and the next candidate wins"
    )


async def test_backfill_leaves_the_parent_empty_when_every_candidate_cycles(db):
    skills = await _seed(db, _skill("a"), _skill("b"))
    service = SkillRelationService(db)
    await service.add("a", "b", "is_a", source="manual")
    skills["b"].parent_id = skills["a"].id
    await db.flush()

    assert await backfill_parent_edges(db) == 0

    assert skills["a"].parent_id is None


async def test_backfill_skips_deprecated_label_rows(db):
    skills = await _seed(
        db, _skill("javascript"), _skill("js", status=SkillStatus.DEPRECATED.value)
    )
    service = SkillRelationService(db)
    await service.add("js", "javascript", "is_a", source="manual")

    assert await backfill_parent_edges(db) == 0

    assert skills["js"].parent_id is None, "a merged-away label row is never placed in the tree"

    extra = await _seed(db, _skill("x"), _skill("web"))
    skills.update(extra)
    await service.add("x", "js", "is_a", source="manual", confidence=0.9)
    await service.add("x", "web", "is_a", source="manual")

    assert await backfill_parent_edges(db) == 1

    assert skills["x"].parent_id == skills["web"].id, (
        "the mirror case: a deprecated TARGET is skipped and the next candidate wins"
    )


async def test_backfill_never_overwrites_a_concurrently_filled_parent(db, monkeypatch):
    """F10: the fill re-checks emptiness at write time — a stale "parent
    empty" snapshot never overwrites a parent filled after it was taken."""
    from dataclasses import replace

    from app.services.catalog import skill_relation_learn as learn

    skills = await _seed(db, _skill("a"), _skill("b"), _skill("c"))
    service = SkillRelationService(db)
    await service.add("a", "c", "is_a", source="manual")

    real_load = learn._load_skills

    async def stale_load(session):
        infos = await real_load(session)
        return {
            info.id: replace(info, parent_key=None) if info.id == skills["a"].id else info
            for info in infos.values()
        }

    monkeypatch.setattr(learn, "_load_skills", stale_load)
    skills["a"].parent_id = skills["b"].id
    await db.flush()

    assert await backfill_parent_edges(db) == 0

    assert skills["a"].parent_id == skills["b"].id, (
        "the concurrent fill wins — the backfill never re-parents"
    )


async def test_backfill_stamps_learned_provenance(db):
    skills = await _seed(db, _skill("programming"), _skill("java"))
    service = SkillRelationService(db)
    await service.add("java", "programming", "is_a", source="manual")

    assert await backfill_parent_edges(db) == 1

    assert skills["java"].parent_source == "learned", "the fill claims machine provenance"


async def test_clear_then_re_tick_never_refills(db):
    """The core regression (plan 139): a deliberate clear stamps `curated`
    and the next catch-up pass leaves the slot empty — the undo sticks."""
    from app.services.catalog.taxonomy_service import TaxonomyService

    skills = await _seed(db, _skill("programming"), _skill("java"))
    service = SkillRelationService(db)
    await service.add("java", "programming", "is_a", source="manual")
    assert await backfill_parent_edges(db) == 1
    await TaxonomyService(db).update_skill(skills["java"].id, {"parent_id": None})

    assert skills["java"].parent_id is None
    assert skills["java"].parent_source == "curated", "the clear claims human provenance"

    assert await backfill_parent_edges(db) == 0
    assert await materialize_parent_edges(db) == 0, "an empty slot mirrors nothing"

    assert skills["java"].parent_id is None, "the undo sticks across ticks"
    assert skills["java"].parent_source == "curated"


async def test_guarded_fill_refuses_a_stamped_empty_slot(db, monkeypatch):
    """F10 extension: the write-time guard re-checks BOTH parent and
    source — a deliberate clear survives even a stale 'untouched'
    snapshot (the guard runs in the same write as the stamp)."""
    from dataclasses import replace

    from app.services.catalog import skill_relation_learn as learn
    from app.services.catalog.taxonomy_service import TaxonomyService

    skills = await _seed(db, _skill("a"), _skill("b"))
    service = SkillRelationService(db)
    await service.add("a", "b", "is_a", source="manual")
    await TaxonomyService(db).update_skill(skills["a"].id, {"parent_id": None})

    real_load = learn._load_skills

    async def stale_load(session):
        infos = await real_load(session)
        return {
            info.id: replace(info, parent_key=None, parent_source=None)
            if info.id == skills["a"].id
            else info
            for info in infos.values()
        }

    monkeypatch.setattr(learn, "_load_skills", stale_load)

    assert await backfill_parent_edges(db) == 0

    assert skills["a"].parent_id is None
    assert skills["a"].parent_source == "curated"


async def test_curated_placement_is_never_overwritten_by_backfill(db):
    from app.services.catalog.taxonomy_service import TaxonomyService

    skills = await _seed(db, _skill("programming"), _skill("jvm-languages"), _skill("java"))
    service = SkillRelationService(db)
    strong = await service.add("java", "programming", "is_a", source="llm", confidence=0.9)
    await service.approve(strong.id)
    await TaxonomyService(db).update_skill(
        skills["java"].id, {"parent_id": skills["jvm-languages"].id}
    )

    assert await backfill_parent_edges(db) == 0

    assert skills["java"].parent_id == skills["jvm-languages"].id
    assert skills["java"].parent_source == "curated"


async def test_legacy_null_placement_is_untouched(db):
    """Pre-139 placements (parent set, source NULL) are skipped by the
    catch-up — provenance unknown, never re-stamped or re-parented."""
    skills = await _seed(db, _skill("programming"), _skill("databases"), _skill("java"))
    service = SkillRelationService(db)
    await service.add("java", "programming", "is_a", source="manual")
    skills["java"].parent_id = skills["databases"].id
    await db.flush()

    assert await backfill_parent_edges(db) == 0

    assert skills["java"].parent_id == skills["databases"].id
    assert skills["java"].parent_source is None


async def test_a_guarded_fill_must_stamp_learned(db):
    """The fill-only guard and the machine stamp are one contract: a
    guarded fill that forgets `parent_source='learned'` fails loudly
    instead of silently stamping `curated` (plan 139 decision 3)."""
    from app.core.errors import ValidationError
    from app.services.catalog.taxonomy_service import TaxonomyService

    skills = await _seed(db, _skill("a"), _skill("b"))

    with pytest.raises(ValidationError, match="learned"):
        await TaxonomyService(db).update_skill(
            skills["a"].id, {"parent_id": skills["b"].id}, only_if_parent_empty=True
        )

    assert skills["a"].parent_id is None
    assert skills["a"].parent_source is None


# ------------------------------------- placement heal (plan 139, step 3)


async def test_remove_filling_edge_clears_unsupported_learned_placement(db):
    skills = await _seed(db, _skill("programming"), _skill("java"))
    service = SkillRelationService(db)
    edge = await service.add("java", "programming", "is_a", source="manual")
    assert await backfill_parent_edges(db) == 1

    await service.remove(edge.id)

    assert skills["java"].parent_id is None
    assert skills["java"].parent_source is None, "the slot is untouched again"


async def test_remove_of_an_unrelated_edge_keeps_a_supported_placement(db):
    """The keep branch: the heal fires for the skill, but the placement's
    own approved `is_a` row still stands — kept, still `learned`. (A
    same-pair second row cannot exist — `uq_skill_relation_edge` dedupes
    (pair, relation) — so "other support" always means a different pair's
    row triggered the heal.)"""
    skills = await _seed(db, _skill("programming"), _skill("jvm-languages"), _skill("java"))
    service = SkillRelationService(db)
    await service.add("java", "programming", "is_a", source="manual", confidence=0.9)
    other = await service.add("java", "jvm-languages", "is_a", source="manual")
    assert await backfill_parent_edges(db) == 1
    assert skills["java"].parent_id == skills["programming"].id

    await service.remove(other.id)

    assert skills["java"].parent_id == skills["programming"].id
    assert skills["java"].parent_source == "learned"


async def test_reject_filling_edge_clears_unsupported_learned_placement(db):
    """Dismissal strands a placement exactly like deletion — reject() heals
    too, and the negative edge keeps the slot from re-filling."""
    skills = await _seed(db, _skill("programming"), _skill("java"))
    service = SkillRelationService(db)
    edge = await service.add("java", "programming", "is_a", source="manual")
    assert await backfill_parent_edges(db) == 1

    await service.reject(edge.id)

    assert skills["java"].parent_id is None
    assert skills["java"].parent_source is None
    assert await backfill_parent_edges(db) == 0, "the negative edge never re-fills it"


async def test_remove_leaves_curated_and_legacy_placements_alone(db):
    from app.services.catalog.taxonomy_service import TaxonomyService

    skills = await _seed(
        db, _skill("programming"), _skill("databases"), _skill("java"), _skill("sql")
    )
    service = SkillRelationService(db)
    curated_edge = await service.add("java", "programming", "is_a", source="manual")
    await TaxonomyService(db).update_skill(
        skills["java"].id, {"parent_id": skills["programming"].id}
    )
    legacy_edge = await service.add("sql", "databases", "is_a", source="manual")
    skills["sql"].parent_id = skills["databases"].id
    await db.flush()

    await service.remove(curated_edge.id)
    await service.remove(legacy_edge.id)

    assert skills["java"].parent_id == skills["programming"].id
    assert skills["java"].parent_source == "curated"
    assert skills["sql"].parent_id == skills["databases"].id
    assert skills["sql"].parent_source is None
    assert await materialize_parent_edges(db) == 2, (
        "curated and legacy placements keep the sticky mirror semantics (documented)"
    )


async def test_delete_resurrection_is_gone(db):
    """Plan 138's weak point dies for learned placements: hard-deleting the
    filling edge heals the slot to untouched, so the next materialization
    has nothing to resurrect as an import mirror."""
    await _seed(db, _skill("programming"), _skill("java"))
    service = SkillRelationService(db)
    edge = await service.add("java", "programming", "is_a", source="manual")
    assert await backfill_parent_edges(db) == 1

    await service.remove(edge.id)

    assert await materialize_parent_edges(db) == 0
    rows = await _relation_rows(db)
    assert rows == [], "no import mirror resurrects the placement"


async def test_run_reports_backfilled_on_the_ledger(db, monkeypatch):
    from app.ai.providers import resolution

    async def _no_ai(*_args, **_kwargs):
        return None

    monkeypatch.setattr(resolution, "resolve_task_model", _no_ai)
    skills = await _seed(db, _skill("programming"), _skill("jvm-languages"), _skill("java"))
    service = SkillRelationService(db)
    edge = await service.add("java", "jvm-languages", "is_a", source="llm", confidence=0.9)
    await service.approve(edge.id)

    result = await run_skill_relation_learn(db)

    assert result["materialized"] == 0
    assert result["backfilled"] == 1
    assert skills["java"].parent_id == skills["jvm-languages"].id


# --------------------------------------------- verdict application (§7 corpus)


async def test_verdict_is_a_redirect_lands_the_verdict_relation(db):
    """§7 java / programming — co-occurrence hypothesizes related_to, the
    verdict redirects to is_a (java → programming) and lands proposed."""
    skills = await _seed(db, _skill("java"), _skill("programming"))
    await _tagged_postings(
        db,
        skills,
        [("j-1", ("java", "programming")), ("j-2", ("java", "programming"))],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    candidate = candidates[0]
    assert candidate.hypothesis is SkillRelationType.RELATED_TO

    stats, settled = await apply_verdicts(
        db,
        candidates,
        [
            SkillEdgeVerdict(
                pair_ref=candidate.pair_ref,
                relation="is_a",
                subject_key="java",
                confidence=0.9,
                rationale="Java is a programming language.",
            )
        ],
    )

    assert stats == {"edges_proposed": 1, "negatives": 0, "dropped": 0, "below_bar": 0}
    assert settled == {candidate.pair_ref}
    rows = await _relation_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert str(row.from_skill_id) == str(skills["java"].id)
    assert str(row.to_skill_id) == str(skills["programming"].id)
    assert row.relation == SkillRelationType.IS_A.value
    assert row.status == SkillRelationStatus.PROPOSED.value
    assert row.source == SkillRelationSource.LLM.value
    assert row.confidence == 0.9
    assert row.evidence["rationale"] == "Java is a programming language."
    assert row.evidence["prompt_version"] == "v2"
    assert row.evidence["signals"]["cooccurrence"] == {"postings": 2, "jobs": 0}


async def test_verdict_synonym_for_ml_machine_learning(db):
    """§7 machine-learning / ml — the synonym the label signal hypothesized."""
    skills = await _seed(
        db,
        _skill("machine-learning", label="Machine Learning"),
        _skill(
            "ml",
            label="ML",
            status=SkillStatus.PROPOSED.value,
            origin="ai",
            provenance={"evidence_quote": "ML required"},
        ),
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    candidate = candidates[0]

    stats, _settled = await apply_verdicts(
        db,
        candidates,
        [
            SkillEdgeVerdict(
                pair_ref=candidate.pair_ref,
                relation="synonym",
                confidence=0.95,
                rationale="ML is the common abbreviation of machine learning.",
            )
        ],
    )

    assert stats["edges_proposed"] == 1
    rows = await _relation_rows(db)
    assert len(rows) == 1
    assert rows[0].relation == SkillRelationType.SYNONYM.value
    assert {str(rows[0].from_skill_id), str(rows[0].to_skill_id)} == {
        str(skills["machine-learning"].id),
        str(skills["ml"].id),
    }


async def test_verdict_typescript_javascript_is_related_never_synonym(db):
    """§7 typescript / javascript — related_to, and never a synonym row."""
    skills = await _seed(db, _skill("javascript"), _skill("typescript"))
    await _tagged_postings(
        db,
        skills,
        [("t-1", ("javascript", "typescript")), ("t-2", ("javascript", "typescript"))],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    candidate = candidates[0]

    await apply_verdicts(
        db,
        candidates,
        [
            SkillEdgeVerdict(
                pair_ref=candidate.pair_ref,
                relation="related_to",
                confidence=0.9,
                rationale="TypeScript compiles to JavaScript.",
            )
        ],
    )

    rows = await _relation_rows(db)
    assert [r.relation for r in rows] == [SkillRelationType.RELATED_TO.value]


async def test_none_verdict_pins_the_negative_and_blocks_resuggestion(db):
    """§7 c# / java — the P&G pair: none above the bar writes the negative
    and the pair never becomes a candidate again."""
    skills = await _seed(db, _skill("c-sharp", label="C#"), _skill("java"))
    await _tagged_postings(
        db,
        skills,
        [("p-1", ("c-sharp", "java")), ("p-2", ("c-sharp", "java"))],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())

    stats, settled = await apply_verdicts(
        db,
        candidates,
        [
            SkillEdgeVerdict(
                pair_ref=candidates[0].pair_ref,
                relation="none",
                confidence=0.9,
                rationale="Co-occurrence only; distinct languages.",
            )
        ],
    )

    assert stats == {"edges_proposed": 0, "negatives": 1, "dropped": 0, "below_bar": 0}
    assert settled == {candidates[0].pair_ref}
    rows = await _relation_rows(db)
    assert len(rows) == 1
    assert rows[0].relation == SkillRelationType.RELATED_TO.value
    assert rows[0].status == SkillRelationStatus.REJECTED.value

    again, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    assert again == []


async def test_none_below_the_confidence_bar_settles_and_goes_dormant(db, monkeypatch):
    """F9 decision: the uncertainty band lands nothing but IS adjudicated —
    the pair goes dormant under the watermark (re-asking the identical
    question would re-bill it daily) and only fresh evidence re-opens it."""
    from app.services.catalog import skill_relation_learn as learn

    async def _uncertain(_db, pairs, **_kwargs):
        return SkillEdgeVerdictSet(
            verdicts=[
                SkillEdgeVerdict(
                    pair_ref=pair["pair_ref"],
                    relation="none",
                    confidence=0.3,
                    rationale="Unsure.",
                )
                for pair in pairs
            ]
        )

    skills = await _seed(db, _skill("c-sharp", label="C#"), _skill("java"))
    await _tagged_postings(
        db,
        skills,
        [("p-1", ("c-sharp", "java")), ("p-2", ("c-sharp", "java"))],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())

    stats, settled = await apply_verdicts(
        db,
        candidates,
        [
            SkillEdgeVerdict(
                pair_ref=candidates[0].pair_ref,
                relation="none",
                confidence=0.3,
                rationale="Unsure.",
            )
        ],
    )

    assert stats["negatives"] == 0
    assert stats["below_bar"] == 1
    assert settled == {candidates[0].pair_ref}, "below-bar settles the pair (F9)"
    assert await _relation_rows(db) == []

    from app.services.job_worker import JobWorker, enqueue

    monkeypatch.setattr(learn, "suggest_skill_edges", _uncertain)
    job = await enqueue(db, BackgroundJobType.SKILL_RELATION_LEARN.value, {})
    assert await JobWorker(db).run_once() is True
    await db.refresh(job)
    assert job.result["below_bar"] == 1
    assert job.result["uncovered"] == 0
    assert job.result["watermark"] is not None, "settled uncertainty lets the watermark advance"

    second = await enqueue(db, BackgroundJobType.SKILL_RELATION_LEARN.value, {})
    assert await JobWorker(db).run_once() is True
    await db.refresh(second)
    assert second.result["candidates"] == 0, (
        "the dormant pair is not re-billed without fresh evidence"
    )


async def test_invalid_verdicts_are_dropped_never_trusted(db):
    skills = await _seed(db, _skill("java"), _skill("python"))
    await _tagged_postings(
        db,
        skills,
        [("v-1", ("java", "python")), ("v-2", ("java", "python"))],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())

    stats, settled = await apply_verdicts(
        db,
        candidates,
        [
            SkillEdgeVerdict(
                pair_ref="p99",
                relation="synonym",
                confidence=0.9,
                rationale="Ghost pair.",
            ),
            SkillEdgeVerdict(
                pair_ref=candidates[0].pair_ref,
                relation="is_a",
                subject_key="go",
                confidence=0.9,
                rationale="Subject outside the pair.",
            ),
        ],
    )

    assert stats == {"edges_proposed": 0, "negatives": 0, "dropped": 2, "below_bar": 0}
    assert settled == set(), "dropped verdicts never settle their pair"
    assert await _relation_rows(db) == []


async def test_dropped_relation_and_confidence_are_counted_not_trusted(db):
    skills = await _seed(db, _skill("java"), _skill("python"), _skill("sql"))
    await _tagged_postings(
        db,
        skills,
        [
            ("r-1", ("java", "python")),
            ("r-2", ("java", "python")),
            ("r-3", ("sql", "python")),
            ("r-4", ("sql", "python")),
        ],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    by_pair = {(c.first.key, c.second.key): c for c in candidates}

    stats, settled = await apply_verdicts(
        db,
        candidates,
        [
            SkillEdgeVerdict(
                pair_ref=by_pair[("java", "python")].pair_ref,
                relation="kind_of",
                confidence=0.9,
                rationale="Not in the closed vocabulary.",
            ),
            SkillEdgeVerdict(
                pair_ref=by_pair[("python", "sql")].pair_ref,
                relation="is_a",
                subject_key="python",
                confidence=4.2,
                rationale="Confidence outside 0-1.",
            ),
        ],
    )

    assert stats == {"edges_proposed": 0, "negatives": 0, "dropped": 2, "below_bar": 0}
    assert settled == set()
    assert await _relation_rows(db) == []


async def test_duplicate_pair_ref_verdicts_are_deduped(db):
    skills = await _seed(db, _skill("java"), _skill("python"))
    await _tagged_postings(
        db,
        skills,
        [("d-1", ("java", "python")), ("d-2", ("java", "python"))],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())

    stats, settled = await apply_verdicts(
        db,
        candidates,
        [
            SkillEdgeVerdict(
                pair_ref=candidates[0].pair_ref,
                relation="is_a",
                subject_key="java",
                confidence=0.9,
                rationale="First answer wins.",
            ),
            SkillEdgeVerdict(
                pair_ref=candidates[0].pair_ref,
                relation="synonym",
                confidence=0.5,
                rationale="Second answer for the same pair.",
            ),
        ],
    )

    assert stats == {"edges_proposed": 1, "negatives": 0, "dropped": 1, "below_bar": 0}
    assert settled == {candidates[0].pair_ref}
    assert len(await _relation_rows(db)) == 1


async def test_verdict_on_a_pair_gained_mid_run_counts_no_new_edge(db):
    skills = await _seed(db, _skill("java"), _skill("python"))
    await _tagged_postings(
        db,
        skills,
        [("mo-1", ("java", "python")), ("mo-2", ("java", "python"))],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    service = SkillRelationService(db)
    await service.add("java", "python", "is_a", source="manual")

    stats, settled = await apply_verdicts(
        db,
        candidates,
        [
            SkillEdgeVerdict(
                pair_ref=candidates[0].pair_ref,
                relation="is_a",
                subject_key="java",
                confidence=0.9,
                rationale="Java is a programming language.",
            )
        ],
    )

    assert stats["edges_proposed"] == 0, "the mid-run human row settles it; no new edge"
    assert stats["dropped"] == 0
    assert settled == {candidates[0].pair_ref}
    assert len(await _relation_rows(db)) == 1


async def test_prompt_pair_carries_endpoint_evidence_quotes(db):
    from app.services.catalog.skill_relation_learn import _prompt_pair

    await _seed(
        db,
        _skill("machine-learning", label="Machine Learning"),
        _skill(
            "ml",
            label="ML",
            status=SkillStatus.PROPOSED.value,
            origin="ai",
            provenance={"evidence_quote": "ML required"},
        ),
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    payload = _prompt_pair(candidates[0])

    quotes = {skill["key"]: skill["evidence_quote"] for skill in payload["skills"]}
    assert quotes == {"machine-learning": None, "ml": "ML required"}


# ----------------------------------------------------------------- run loop


async def test_unconfigured_run_derives_label_matches_and_holds_the_watermark(db, monkeypatch):
    from app.ai.providers import resolution

    async def _no_ai(*_args, **_kwargs):
        return None

    monkeypatch.setattr(resolution, "resolve_task_model", _no_ai)
    prior = (_now() - timedelta(hours=1)).isoformat()
    db.add(
        BackgroundJob(
            job_type=BackgroundJobType.SKILL_RELATION_LEARN.value,
            status="succeeded",
            payload={},
            result={"watermark": prior},
        )
    )
    await db.flush()
    skills = await _seed(
        db,
        _skill("machine-learning", label="Machine Learning"),
        _skill(
            "ml",
            label="ML",
            status=SkillStatus.PROPOSED.value,
            origin="ai",
            provenance={"evidence_quote": "ML required"},
        ),
        _skill("java"),
        _skill("python"),
    )
    await _tagged_postings(db, skills, [("f-1", ("java", "python")), ("f-2", ("java", "python"))])

    result = await run_skill_relation_learn(db)

    assert result["judged_batches"] == 0
    assert result["failed_batches"] == 0
    assert result["derived"] == 1, "only the string-grounded label match derives"
    rows = await _relation_rows(db)
    assert len(rows) == 1
    assert rows[0].source == SkillRelationSource.DERIVED.value
    assert rows[0].status == SkillRelationStatus.PROPOSED.value
    assert rows[0].confidence is None
    assert {str(rows[0].from_skill_id), str(rows[0].to_skill_id)} == {
        str(skills["machine-learning"].id),
        str(skills["ml"].id),
    }
    assert "label_match" in rows[0].evidence["signals"]
    assert result["watermark"] == prior, "an unconfigured run never advances the watermark"
    again, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    assert [(c.first.key, c.second.key) for c in again] == [("java", "python")], (
        "co-occurrence pairs wait for a configured provider"
    )


async def test_derived_fallback_leaves_cooccurrence_for_the_first_configured_run(db, monkeypatch):
    from app.ai.providers import resolution

    original = resolution.resolve_task_model

    async def _no_ai(*_args, **_kwargs):
        return None

    monkeypatch.setattr(resolution, "resolve_task_model", _no_ai)
    skills = await _seed(db, _skill("java"), _skill("python"))
    await _tagged_postings(db, skills, [("d-1", ("java", "python")), ("d-2", ("java", "python"))])

    first = await run_skill_relation_learn(db)

    assert first["derived"] == 0
    assert await _relation_rows(db) == []

    monkeypatch.setattr(resolution, "resolve_task_model", original)
    second = await run_skill_relation_learn(db)

    assert second["edges_proposed"] == 1
    rows = await _relation_rows(db)
    assert [row.source for row in rows] == [SkillRelationSource.LLM.value], (
        "the first configured run judges the pair, not the fallback"
    )


async def test_partial_failure_holds_the_watermark_and_retries_the_failed_pair(db, monkeypatch):
    await _set_thresholds(db, batch_size=1)
    spy = _spy(monkeypatch, fail_on={2})
    skills = await _seed(db, _skill("java"), _skill("python"), _skill("sql"))
    await _tagged_postings(
        db,
        skills,
        [
            ("f-1", ("java", "python")),
            ("f-2", ("java", "python")),
            ("f-3", ("sql", "python")),
            ("f-4", ("sql", "python")),
        ],
    )

    result = await run_skill_relation_learn(db)

    assert spy.sizes == [1, 1]
    assert result["batches"] == 2
    assert result["judged_batches"] == 1
    assert result["failed_batches"] == 1
    assert result["derived"] == 0
    assert result["watermark"] is None, "unfinished work holds the watermark floor"
    rows = await _relation_rows(db)
    assert len(rows) == 1, "the failed batch writes nothing"
    again, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    assert len(again) == 1, "the failed pair stays a candidate"


async def test_batch_caps_split_calls_and_cap_the_run(db, monkeypatch):
    await _set_thresholds(db, batch_size=2, max_pairs_per_run=3)
    spy = _spy(monkeypatch)
    skills = await _seed(db, _skill("a"), _skill("b"), _skill("c"), _skill("d"))
    await _tagged_postings(
        db,
        skills,
        [("cap-1", ("a", "b", "c", "d")), ("cap-2", ("a", "b", "c", "d"))],
    )

    result = await run_skill_relation_learn(db)

    assert result["candidates"] == 3
    assert result["capped"] is True
    assert result["watermark"] is None, "a capped run holds the watermark floor"
    assert spy.sizes == [2, 1]
    assert all(size <= 2 for size in spy.sizes)


async def test_idempotent_re_tick_is_a_no_op(db, monkeypatch):
    spy = _spy(monkeypatch)
    skills = await _seed(db, _skill("java"), _skill("python"))
    await _tagged_postings(
        db,
        skills,
        [("i-1", ("java", "python")), ("i-2", ("java", "python"))],
    )

    first = await run_skill_relation_learn(db)
    assert first["edges_proposed"] == 1
    rows_after_first = await _relation_rows(db)
    calls_after_first = list(spy.sizes)

    second = await run_skill_relation_learn(db)

    assert second["candidates"] == 0
    assert second["batches"] == 0
    assert spy.sizes == calls_after_first, "no new batches on a re-tick"
    assert await _relation_rows(db) == rows_after_first
    assert second["watermark"] is not None


async def test_watermark_only_reexamines_fresh_evidence(db):
    skills = await _seed(db, _skill("java"), _skill("python"), _skill("javascript"))
    source = JobSource(
        key=f"learn-{uuid.uuid4().hex[:8]}",
        connector_key="synthetic",
        kind="posting",
        config={},
    )
    db.add(source)
    await db.flush()
    old = _now() - timedelta(hours=3)
    seeded = [
        ("w-old-1", ("java", "python"), old),
        ("w-old-2", ("java", "python"), old),
        ("w-new-1", ("java", "javascript"), _now()),
        ("w-new-2", ("java", "javascript"), _now()),
    ]
    for external_id, keys, stamp in seeded:
        posting = JobPosting(
            source_id=source.id,
            external_id=external_id,
            title=external_id,
            org="TestCo",
            content_hash=f"{external_id}-hash",
        )
        db.add(posting)
        await db.flush()
        for key in keys:
            db.add(
                PostingSkill(
                    posting_id=posting.id,
                    skill_id=skills[key].id,
                    required_level=5,
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
    await db.flush()

    everything, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    fresh, _ = await collect_candidates(
        db, since=_now() - timedelta(hours=1), thresholds=Thresholds()
    )

    assert {(c.first.key, c.second.key) for c in everything} == {
        ("java", "python"),
        ("java", "javascript"),
    }
    assert [(c.first.key, c.second.key) for c in fresh] == [("java", "javascript")]


async def test_incomplete_verdict_coverage_holds_the_watermark(db, monkeypatch):
    from app.services.catalog import skill_relation_learn as learn

    async def _partial(_db, pairs, **_kwargs):
        return SkillEdgeVerdictSet(
            verdicts=[
                SkillEdgeVerdict(
                    pair_ref=pairs[0]["pair_ref"],
                    relation="related_to",
                    confidence=0.9,
                    rationale="Answered only the first pair.",
                )
            ]
        )

    monkeypatch.setattr(learn, "suggest_skill_edges", _partial)
    skills = await _seed(db, _skill("java"), _skill("python"), _skill("sql"))
    await _tagged_postings(
        db,
        skills,
        [
            ("f-1", ("java", "python")),
            ("f-2", ("java", "python")),
            ("f-3", ("sql", "python")),
            ("f-4", ("sql", "python")),
        ],
    )

    result = await run_skill_relation_learn(db)

    assert result["judged_batches"] == 1
    assert result["uncovered"] == 1
    assert result["edges_proposed"] == 1
    assert result["watermark"] is None, "an unanswered pair holds the watermark floor"
    again, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    assert len(again) == 1, "the unanswered pair stays a candidate"


async def test_answered_but_invalid_pairs_re_pick_under_a_held_watermark(db, monkeypatch):
    from app.services.catalog import skill_relation_learn as learn

    async def _bad_subject(_db, pairs, **_kwargs):
        return SkillEdgeVerdictSet(
            verdicts=[
                SkillEdgeVerdict(
                    pair_ref=pair["pair_ref"],
                    relation="is_a",
                    subject_key="cobol-nonsense",
                    confidence=0.9,
                    rationale="Subject outside the pair.",
                )
                for pair in pairs
            ]
        )

    monkeypatch.setattr(learn, "suggest_skill_edges", _bad_subject)
    skills = await _seed(db, _skill("java"), _skill("python"))
    await _tagged_postings(
        db,
        skills,
        [("iv-1", ("java", "python")), ("iv-2", ("java", "python"))],
    )

    result = await run_skill_relation_learn(db)

    assert result["judged_batches"] == 1
    assert result["dropped"] == 1
    assert result["uncovered"] == 1, "an answered-but-dropped pair is unfinished work"
    assert result["watermark"] is None, "the dropped pair holds the watermark floor"
    again, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    assert [(c.first.key, c.second.key) for c in again] == [("java", "python")], (
        "dropped pairs are re-picked, never lost"
    )


async def test_one_malformed_verdict_does_not_fail_the_batch(db, monkeypatch):
    from app.services.catalog import skill_relation_learn as learn

    real = learn.suggest_skill_edges
    sizes: list[int] = []

    async def _corrupt_one(session, pairs, **kwargs):
        sizes.append(len(pairs))
        verdict_set = await real(session, pairs, **kwargs)
        if verdict_set is not None and len(sizes) == 1:
            verdict_set.verdicts[0].relation = "kind_of"
            verdict_set.verdicts[0].confidence = 4.2
        return verdict_set

    monkeypatch.setattr(learn, "suggest_skill_edges", _corrupt_one)
    keys = [f"s{i:02d}" for i in range(1, 11)]
    skills = await _seed(db, *(_skill(key) for key in keys))
    await _tagged_postings(db, skills, [("m-1", tuple(keys)), ("m-2", tuple(keys))])

    result = await run_skill_relation_learn(db)

    assert sizes == [40, 5]
    assert result["batches"] == 2
    assert result["judged_batches"] == 2, "the batch succeeds despite the malformed verdict"
    assert result["failed_batches"] == 0
    assert result["edges_proposed"] == 44, "39 of batch 1 plus all 5 of batch 2 land"
    assert result["dropped"] == 1
    assert result["uncovered"] == 1, "the malformed pair stays unfinished and re-picks"


async def test_cancelled_run_holds_the_watermark_and_re_picks_skipped_pairs(db, monkeypatch):
    from app.services.catalog import skill_relation_learn as learn

    await _set_thresholds(db, batch_size=1)
    prior = (_now() - timedelta(hours=1)).isoformat()
    db.add(
        BackgroundJob(
            job_type=BackgroundJobType.SKILL_RELATION_LEARN.value,
            status="succeeded",
            payload={},
            result={"watermark": prior},
        )
    )
    job = BackgroundJob(
        job_type=BackgroundJobType.SKILL_RELATION_LEARN.value,
        status="running",
        payload={},
    )
    db.add(job)
    await db.flush()
    skills = await _seed(db, _skill("java"), _skill("python"), _skill("sql"))
    await _tagged_postings(
        db,
        skills,
        [
            ("c-1", ("java", "python")),
            ("c-2", ("java", "python")),
            ("c-3", ("sql", "python")),
            ("c-4", ("sql", "python")),
        ],
    )

    real = learn.suggest_skill_edges
    calls: list[int] = []

    async def _cancel_mid_run(session, pairs, **kwargs):
        calls.append(len(pairs))
        if len(calls) == 1:
            job.cancel_requested = True
            await session.commit()
        return await real(session, pairs, **kwargs)

    monkeypatch.setattr(learn, "suggest_skill_edges", _cancel_mid_run)

    async def cancelled() -> bool:
        fresh = await db.get(BackgroundJob, job.id)
        return bool(fresh and fresh.cancel_requested)

    result = await run_skill_relation_learn(db, cancelled=cancelled)

    assert calls == [1], "the run stops after the first batch"
    assert result["edges_proposed"] == 1
    assert result["watermark"] == prior, "a cancelled run returns the floor, never collected_at"

    again, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    assert len(again) == 1, "the skipped pair survives the cancel"

    second = await run_skill_relation_learn(db)
    assert second["edges_proposed"] == 1, "the next run re-picks the skipped pair"


async def test_watermark_reads_the_last_succeeded_run_ledger(db):
    skills = await _seed(db, _skill("java"), _skill("python"), _skill("javascript"))
    source = JobSource(
        key=f"learn-{uuid.uuid4().hex[:8]}",
        connector_key="synthetic",
        kind="posting",
        config={},
    )
    db.add(source)
    await db.flush()
    old = _now() - timedelta(hours=3)
    for external_id, keys, stamp in (
        ("w-old-1", ("java", "python"), old),
        ("w-old-2", ("java", "python"), old),
        ("w-new-1", ("java", "javascript"), _now()),
        ("w-new-2", ("java", "javascript"), _now()),
    ):
        posting = JobPosting(
            source_id=source.id,
            external_id=external_id,
            title=external_id,
            org="TestCo",
            content_hash=f"{external_id}-hash",
        )
        db.add(posting)
        await db.flush()
        for key in keys:
            db.add(
                PostingSkill(
                    posting_id=posting.id,
                    skill_id=skills[key].id,
                    required_level=5,
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
    prior = (_now() - timedelta(hours=1)).isoformat()
    db.add(
        BackgroundJob(
            job_type=BackgroundJobType.SKILL_RELATION_LEARN.value,
            status="succeeded",
            payload={},
            result={"watermark": prior, "candidates": 0},
        )
    )
    await db.flush()

    result = await run_skill_relation_learn(db)

    assert result["candidates"] == 1, "the ledger watermark hides stale evidence"
    assert result["edges_proposed"] == 1
    rows = await _relation_rows(db)
    assert len(rows) == 1


async def test_watermark_falls_back_to_the_run_created_at(db):
    skills = await _seed(db, _skill("java"), _skill("python"), _skill("javascript"))
    source = JobSource(
        key=f"learn-{uuid.uuid4().hex[:8]}",
        connector_key="synthetic",
        kind="posting",
        config={},
    )
    db.add(source)
    await db.flush()
    old = _now() - timedelta(hours=3)
    for external_id, keys, stamp in (
        ("w-old-1", ("java", "python"), old),
        ("w-old-2", ("java", "python"), old),
        ("w-new-1", ("java", "javascript"), _now()),
        ("w-new-2", ("java", "javascript"), _now()),
    ):
        posting = JobPosting(
            source_id=source.id,
            external_id=external_id,
            title=external_id,
            org="TestCo",
            content_hash=f"{external_id}-hash",
        )
        db.add(posting)
        await db.flush()
        for key in keys:
            db.add(
                PostingSkill(
                    posting_id=posting.id,
                    skill_id=skills[key].id,
                    required_level=5,
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
    db.add(
        BackgroundJob(
            job_type=BackgroundJobType.SKILL_RELATION_LEARN.value,
            status="succeeded",
            payload={},
            result={"candidates": 0},
            created_at=_now() - timedelta(hours=1),
        )
    )
    await db.flush()

    result = await run_skill_relation_learn(db)

    assert result["candidates"] == 1, "the created_at fallback hides evidence older than the run"
    assert result["edges_proposed"] == 1


async def test_held_watermark_keeps_the_previous_floor(db, monkeypatch):
    await _set_thresholds(db, batch_size=1)
    _spy(monkeypatch, fail_on={1, 2})
    prior = (_now() - timedelta(hours=1)).isoformat()
    db.add(
        BackgroundJob(
            job_type=BackgroundJobType.SKILL_RELATION_LEARN.value,
            status="succeeded",
            payload={},
            result={"watermark": prior},
        )
    )
    await db.flush()
    skills = await _seed(db, _skill("java"), _skill("python"), _skill("sql"))
    await _tagged_postings(
        db,
        skills,
        [
            ("f-1", ("java", "python")),
            ("f-2", ("java", "python")),
            ("f-3", ("sql", "python")),
            ("f-4", ("sql", "python")),
        ],
    )

    result = await run_skill_relation_learn(db)

    assert result["failed_batches"] == 2
    assert result["watermark"] == prior, "the floor moves to the previous watermark, never past it"


# --------------------------------------------------------- scheduler + queue


def test_kind_task_mapping():
    from app.services.scheduler.runner import KIND_TASKS

    assert KIND_TASKS[ScheduleKind.SYSTEM_SKILL_RELATION_LEARN.value] == (
        BackgroundJobType.SKILL_RELATION_LEARN.value
    )


async def test_scheduler_provisions_and_ticks_the_learn_schedule(db):
    from app.services.scheduler.runner import SchedulerService

    service = SchedulerService(db)
    await service.ensure_system_schedules()
    await service.ensure_system_schedules()
    rows = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == ScheduleKind.SYSTEM_SKILL_RELATION_LEARN.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    schedule = rows[0]
    assert schedule.task == BackgroundJobType.SKILL_RELATION_LEARN.value
    assert schedule.trigger == {"type": "daily_at", "params": {"time": "03:30", "timezone": "UTC"}}
    assert schedule.misfire_policy == "skip"

    schedule.next_run_at = _now() - timedelta(minutes=1)
    await db.commit()
    await service.tick()

    jobs = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == BackgroundJobType.SKILL_RELATION_LEARN.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1


async def test_queue_run_reports_on_the_ledger(db):
    from app.services.job_worker import JobWorker, enqueue

    skills = await _seed(db, _skill("java"), _skill("python"))
    await _tagged_postings(
        db,
        skills,
        [("q-1", ("java", "python")), ("q-2", ("java", "python"))],
    )
    job = await enqueue(db, BackgroundJobType.SKILL_RELATION_LEARN.value, {})

    assert await JobWorker(db).run_once() is True

    await db.refresh(job)
    assert job.status == "succeeded"
    result = job.result
    assert result["edges_proposed"] == 1
    assert result["candidates"] == 1
    assert "watermark" in result
    assert "materialized" in result
