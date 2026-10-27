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

    stats = await apply_verdicts(
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
    assert row.evidence["prompt_version"] == "v1"
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

    stats = await apply_verdicts(
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

    stats = await apply_verdicts(
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
    rows = await _relation_rows(db)
    assert len(rows) == 1
    assert rows[0].relation == SkillRelationType.RELATED_TO.value
    assert rows[0].status == SkillRelationStatus.REJECTED.value

    again, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    assert again == []


async def test_none_below_the_confidence_bar_lands_nothing(db):
    skills = await _seed(db, _skill("c-sharp", label="C#"), _skill("java"))
    await _tagged_postings(
        db,
        skills,
        [("p-1", ("c-sharp", "java")), ("p-2", ("c-sharp", "java"))],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())

    stats = await apply_verdicts(
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
    assert await _relation_rows(db) == []
    again, _ = await collect_candidates(db, since=None, thresholds=Thresholds())
    assert len(again) == 1, "an uncertain pair stays a candidate"


async def test_invalid_verdicts_are_dropped_never_trusted(db):
    skills = await _seed(db, _skill("java"), _skill("python"))
    await _tagged_postings(
        db,
        skills,
        [("v-1", ("java", "python")), ("v-2", ("java", "python"))],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())

    stats = await apply_verdicts(
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
    assert await _relation_rows(db) == []


async def test_duplicate_pair_ref_verdicts_are_deduped(db):
    skills = await _seed(db, _skill("java"), _skill("python"))
    await _tagged_postings(
        db,
        skills,
        [("d-1", ("java", "python")), ("d-2", ("java", "python"))],
    )
    candidates, _ = await collect_candidates(db, since=None, thresholds=Thresholds())

    stats = await apply_verdicts(
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
    assert len(await _relation_rows(db)) == 1


# ----------------------------------------------------------------- run loop


async def test_unconfigured_ai_falls_back_to_derived_rows(db, monkeypatch):
    from app.ai.providers import resolution

    async def _no_ai(*_args, **_kwargs):
        return None

    monkeypatch.setattr(resolution, "resolve_task_model", _no_ai)
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

    assert result["judged_batches"] == 0
    assert result["failed_batches"] == 0
    assert result["derived"] == 2
    rows = await _relation_rows(db)
    assert len(rows) == 2
    assert {row.source for row in rows} == {SkillRelationSource.DERIVED.value}
    assert {row.status for row in rows} == {SkillRelationStatus.PROPOSED.value}
    assert all(row.confidence is None for row in rows)
    assert all("cooccurrence" in row.evidence["signals"] for row in rows)


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
