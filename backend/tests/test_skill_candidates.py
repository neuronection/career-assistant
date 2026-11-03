"""— plan 153 slice 1: the deterministic skill-candidate matcher
(exact index hit, terminal → trigram near-miss → indexed skill-document
cosine ranking, lexical fallback).

The semantic layer now reads the family vector store (plan 50 P1d): these
tests index skill documents directly so the ranking is exactly controlled,
and assert that a missing space degrades to the lexical order.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import select

from app.models.enums import BackgroundJobType, ScheduleKind
from app.models.schedule_model import Schedule
from app.models.taxonomy_model import Skill
from app.services.postings.skill_candidates import candidate_skills
from tests.vector_harness import Harness, create_native_engine, create_space, drop_space


@pytest.fixture
def harness() -> Iterator[Harness]:
    engine = create_native_engine()
    from app.ai.gateway import MOCK_EMBED_DIM

    space = create_space(engine, name="content", dim=MOCK_EMBED_DIM)
    try:
        yield space
    finally:
        drop_space(space)
        engine.dispose()


async def _index_skill(harness: Harness, skill: Skill, vector: tuple[float, ...]):
    name = f"skill-{skill.key}"
    harness.add_document(name, kind="skill", source_id=str(skill.id), scope_type="global")
    harness.index(name, vector)


async def _skill(db, key: str, label: str, *, status: str = "active", aliases=None) -> Skill:
    row = Skill(
        key=key,
        label=label,
        category="test",
        status=status,
        aliases=list(aliases or []),
    )
    db.add(row)
    await db.flush()
    return row


async def test_exact_hit_is_terminal_and_active_claim_beats_deprecated_key(db):
    deprecated = await _skill(db, "python", "Python", status="deprecated")
    active = await _skill(db, "python-3", "Python 3", aliases=["python"])

    candidates = await candidate_skills(db, "python")

    assert len(candidates) == 1, "an exact hit is terminal — one candidate"
    top = candidates[0]
    assert top.skill_id == active.id
    assert top.status == "active"
    assert top.score == 1.0
    assert top.signal == "exact"
    assert deprecated.id != top.skill_id


async def test_deprecated_rows_answer_unmatched_exact_tokens_only(db):
    legacy = await _skill(db, "legacy-x", "Legacy X", status="deprecated")

    exact = await candidate_skills(db, "legacy-x")
    assert [c.skill_id for c in exact] == [legacy.id]
    assert exact[0].status == "deprecated", "unmatched exact tokens still resolve"

    fuzzy = await candidate_skills(db, "legacy-xx")
    assert fuzzy == [], "deprecated rows never enter the fuzzy pool"


async def test_trigram_near_miss_ranks_related_skill_lexically(db):
    near = await _skill(db, "programming", "Programming", status="proposed")
    far = await _skill(db, "project-management", "Project Management")

    candidates = await candidate_skills(db, "programmer")

    assert [c.skill_id for c in candidates][:2] == [near.id, far.id]
    assert candidates[0].signal == "trigram", "no vectors → lexical signal"
    assert candidates[0].score > 0.5, "programmer/programming is a near-miss"
    assert candidates[0].status == "proposed", "proposed rows are candidates"


async def test_c_and_c_plus_plus_stay_apart(db):
    c = await _skill(db, "c", "C")
    cpp = await _skill(db, "c++", "C++")

    for label, expected in (("c", c), ("C++", cpp)):
        candidates = await candidate_skills(db, label)
        assert [x.skill_id for x in candidates] == [expected.id], (
            "the exact layer is terminal even where trigram is punctuation-blind"
        )


async def test_cosine_ranks_semantic_pair_above_lexical_noise(db, harness):
    noise = await _skill(db, "python", "Python")
    semantic = await _skill(db, "deep-learning-framework", "Deep Learning Framework")
    await db.commit()

    lexical = await candidate_skills(db, "pytorch")
    assert lexical[0].skill_id == noise.id, "without vectors the lexical noise wins"

    from app.ai.gateway import embed_texts

    query_vector = (await embed_texts(db, ["pytorch"]))[0]
    await _index_skill(harness, semantic, tuple(query_vector))

    candidates = await candidate_skills(db, "pytorch")
    assert candidates[0].skill_id == semantic.id
    assert candidates[0].signal == "embedding"
    assert candidates[0].score > 0.99, "the indexed vector ranks first"
    assert candidates[1].skill_id == noise.id
    assert candidates[1].signal == "trigram", "vector-less rows keep lexical order"


async def test_k_bounds_the_candidate_list(db):
    await _skill(db, "programming", "Programming")
    await _skill(db, "programmer", "Programmer")
    await _skill(db, "program-design", "Program Design")

    candidates = await candidate_skills(db, "program", k=2)

    assert len(candidates) == 2


async def test_empty_label_returns_no_candidates(db):
    assert await candidate_skills(db, "   ") == []


def test_compose_skill_text_orders_aliases_deterministically():
    class FakeSkill:
        key = "pytorch"
        label = "PyTorch"
        aliases = ["torch nn", "pytorch"]  # noqa: RUF012 -- test fixture data

    from app.services.vector_composers import compose_skill_text

    text = compose_skill_text(FakeSkill())
    assert text == "pytorch\nPyTorch\npytorch\ntorch nn"


async def test_scheduler_provisions_and_runs_the_reconcile_job(db):
    from app.services.job_worker import JobWorker, enqueue
    from app.services.scheduler.runner import KIND_TASKS, SchedulerService

    assert (
        KIND_TASKS[ScheduleKind.SYSTEM_VECTOR_RECONCILE.value]
        == BackgroundJobType.VECTOR_RECONCILE.value
    )

    await SchedulerService(db).ensure_system_schedules()
    schedule = (
        (
            await db.execute(
                select(Schedule).where(Schedule.kind == ScheduleKind.SYSTEM_VECTOR_RECONCILE.value)
            )
        )
        .scalars()
        .first()
    )
    assert schedule is not None, "the reconcile slot is boot-provisioned"
    assert schedule.task == BackgroundJobType.VECTOR_RECONCILE.value
    assert schedule.trigger["type"] == "daily_at"
    assert schedule.payload["kinds"] == ["posting", "profile", "skill"]

    await _skill(db, "rust-lang", "Rust")
    await db.commit()

    job = await enqueue(
        db, BackgroundJobType.VECTOR_RECONCILE.value, {"kinds": ["skill"], "limit": 10}
    )
    assert await JobWorker(db).run_once() is True
    await db.refresh(job)
    assert job.status == "succeeded", job.error
    assert job.result["embedded"] == 1
    assert job.result["kinds"][0]["kind"] == "skill"
