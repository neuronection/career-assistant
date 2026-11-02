"""— plan 153 slice 1: the deterministic skill-candidate matcher
(exact index hit, terminal → trigram near-miss → embedding cosine
ranking, lexical fallback) and the skill-embedding recompute surfaces
(service, admin endpoint, scheduler job)."""

from sqlalchemy import select

from app.ai.gateway import embed_texts
from app.core.errors import AINotConfiguredError
from app.models.embedding_model import AIEmbedding
from app.models.enums import BackgroundJobType, ScheduleKind
from app.models.schedule_model import Schedule
from app.models.taxonomy_model import Skill
from app.services.embedding_service import (
    KIND_SKILL,
    EmbeddingService,
    compose_skill_text,
)
from app.services.postings.skill_candidates import candidate_skills


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


async def test_cosine_ranks_semantic_pair_above_lexical_noise(db):
    noise = await _skill(db, "python", "Python")
    semantic = await _skill(db, "deep-learning-framework", "Deep Learning Framework")

    lexical = await candidate_skills(db, "pytorch")
    assert lexical[0].skill_id == noise.id, "without vectors the lexical noise wins"

    query_vector = (await embed_texts(db, ["pytorch"]))[0]
    await EmbeddingService(db).upsert_embedding(
        KIND_SKILL, semantic.id, compose_skill_text(semantic), vector=query_vector
    )

    candidates = await candidate_skills(db, "pytorch")
    assert candidates[0].skill_id == semantic.id
    assert candidates[0].signal == "embedding"
    assert candidates[0].score > 0.99, "the stored query vector ranks first"
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

    text = compose_skill_text(FakeSkill())
    assert text == "pytorch\nPyTorch\npytorch\ntorch nn"


async def test_recompute_skills_embeds_dedupes_and_reembeds_stale(db):
    first = await _skill(db, "kubernetes", "Kubernetes")
    await _skill(db, "docker", "Docker")

    service = EmbeddingService(db)
    result = await service.recompute_skills()
    assert result["embedded"] == 2
    rows = (
        (await db.execute(select(AIEmbedding).where(AIEmbedding.entity_kind == KIND_SKILL)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(row.dim == len(row.vector) for row in rows)

    again = await service.recompute_skills()
    assert again == {"candidates": 0, "embedded": 0}, "content-hash dedupe"

    first.label = "Kubernetes (k8s)"
    stale = await service.recompute_skills()
    assert stale == {"candidates": 1, "embedded": 1}, "changed text re-embeds"


async def test_recompute_skills_degrades_when_provider_unconfigured(db, monkeypatch):
    await _skill(db, "go", "Go")

    async def _unconfigured(db_, texts, user_id=None):
        raise AINotConfiguredError("AI is not configured yet")

    monkeypatch.setattr("app.ai.gateway.embed_texts", _unconfigured)
    result = await EmbeddingService(db).recompute_skills()
    assert result["embedded"] == 0
    assert result["degraded"] == "embed provider unconfigured"
    assert result["candidates"] == 1


async def test_admin_recompute_endpoint_and_status_surface_the_skill_kind(client, auth_headers, db):
    response = await client.get("/api/v1/ai/embeddings/status", headers=auth_headers)
    assert response.status_code == 200
    assert any(
        bucket["entity_kind"] == "skill" and bucket["count"] == 0 for bucket in response.json()
    ), "served kinds surface in status before the first run"

    await _skill(db, "postgres-sql", "PostgreSQL")

    response = await client.post(
        "/api/v1/ai/embeddings/recompute",
        params={"kind": "skill", "limit": 10},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["embedded"] == 1

    response = await client.post(
        "/api/v1/ai/embeddings/recompute",
        params={"kind": "posting", "limit": 10},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    response = await client.post(
        "/api/v1/ai/embeddings/recompute",
        params={"kind": "bogus"},
        headers=auth_headers,
    )
    assert response.status_code == 400

    response = await client.get("/api/v1/ai/embeddings/status", headers=auth_headers)
    assert response.status_code == 200
    skill_buckets = [bucket for bucket in response.json() if bucket["entity_kind"] == "skill"]
    assert sum(bucket["count"] for bucket in skill_buckets) == 1


async def test_scheduler_provisions_and_runs_the_reconcile_job(db):
    from app.services.scheduler.runner import KIND_TASKS, SchedulerService

    assert (
        KIND_TASKS[ScheduleKind.SYSTEM_EMBEDDINGS_RECONCILE.value]
        == BackgroundJobType.EMBEDDINGS_RECONCILE.value
    )

    await SchedulerService(db).ensure_system_schedules()
    schedule = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == ScheduleKind.SYSTEM_EMBEDDINGS_RECONCILE.value
                )
            )
        )
        .scalars()
        .first()
    )
    assert schedule is not None, "the reconcile slot is boot-provisioned"
    assert schedule.task == BackgroundJobType.EMBEDDINGS_RECONCILE.value
    assert schedule.trigger["type"] == "daily_at"

    await _skill(db, "rust-lang", "Rust")
    from app.services.job_worker import JobWorker, enqueue

    job = await enqueue(db, BackgroundJobType.EMBEDDINGS_RECONCILE.value, {"limit": 10})
    assert await JobWorker(db).run_once() is True
    await db.refresh(job)
    assert job.status == "succeeded"
    assert job.result["embedded"] == 1
