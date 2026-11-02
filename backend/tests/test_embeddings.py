"""— embeddings store: deterministic mock vectors, hash
dedupe, cosine retrieval, recompute + status surfaces."""

from uuid import UUID

from sqlalchemy import select

from app.models.embedding_model import AIEmbedding
from app.services.embedding_service import (
    EmbeddingService,
    compose_posting_text,
    cosine,
)
from tests.conftest import _make_posting, _uid


def test_cosine_math():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([], []) == 0.0
    assert abs(cosine([1.0, 2.0], [1.0, 2.0]) - 1.0) < 1e-9
    assert cosine([1.0], [1.0, 2.0]) == 0.0, "dim mismatch never crashes"


async def test_mock_vectors_are_deterministic_and_unit_length(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.ai.gateway import embed_texts

    vectors = await embed_texts(
        db, ["backend engineer role", "backend engineer role"], UUID(_uid(auth_headers))
    )
    assert len(vectors) == 2
    assert vectors[0] == vectors[1], "same text → same vector"
    assert abs(sum(v * v for v in vectors[0]) - 1.0) < 0.01, "unit length"
    other = await embed_texts(db, ["chef position"], UUID(_uid(auth_headers)))
    assert other[0] != vectors[0]


async def test_upsert_dedupes_on_content_hash(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    service = EmbeddingService(db)
    entity_id = UUID(int=1)
    _row1, did1 = await service.upsert_embedding(
        "posting", entity_id, "A data engineering role in Athens", vector=[0.1, 0.2]
    )
    assert did1 is True
    _row2, did2 = await service.upsert_embedding(
        "posting", entity_id, "A data engineering role in Athens", vector=[0.1, 0.2]
    )
    assert did2 is False, "same text skips the gateway entirely"
    _row3, did3 = await service.upsert_embedding(
        "posting", entity_id, "A different role entirely", vector=[0.3, 0.4]
    )
    assert did3 is True, "changed text re-embeds"
    rows = (await db.execute(select(AIEmbedding))).scalars().all()
    assert len(rows) == 1, "one row per entity — latest text wins"


async def test_recompute_and_search_similar(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await _make_posting(db, source, external_id="emb-1")
    await _make_posting(db, source, external_id="emb-2")
    service = EmbeddingService(db)

    result = await service.recompute_postings(limit=10)
    assert result["embedded"] >= 1

    hits = await service.search_similar("anything at all", limit=5)
    assert hits, "stored embeddings rank against the query"
    assert all(set(h) >= {"entity_kind", "entity_id", "score"} for h in hits)
    top = hits[0]["score"]
    assert all(h["score"] <= top for h in hits), "descending by cosine"

    status = await service.status()
    assert any(s["entity_kind"] == "posting" for s in status)


async def test_compose_posting_text_covers_extract():
    class FakePosting:
        title = "Backend Engineer"
        org = "ACME"
        raw = {"description": "Build services."}  # noqa: RUF012 -- test fixture data
        extract = {  # noqa: RUF012 -- test fixture data
            "skills": [{"raw_label": "sql", "priority": "must_have", "required_level": 6}],
            "responsibilities": [{"text": "Ship payments", "time_pct": 40}],
        }

    text = compose_posting_text(FakePosting())
    assert "Backend Engineer" in text and "ACME" in text
    assert "sql" in text and "must_have" in text and "6" in text
    assert "Ship payments (40%)" in text


class _FakeJobSkill:
    def __init__(self, label: str, importance: str, level: int):
        self.skill = type("S", (), {"label": label})()
        self.importance = importance
        self.required_level = level


class _FakeJob:
    title = "Data Engineer"
    short_description = "Moves data reliably."


def test_compose_job_text_orders_must_have_first():
    from app.services.embedding_service import compose_job_text

    links = [
        _FakeJobSkill("Spreadsheets", "bonus", 2),
        _FakeJobSkill("SQL", "core", 8),
        _FakeJobSkill("Airflow", "core", 6),
        _FakeJobSkill("Python", "important", 7),
    ]
    text = compose_job_text(_FakeJob(), links)
    lines = text.splitlines()
    assert lines[0] == "Data Engineer"
    assert lines[1] == "Moves data reliably."
    skill_lines = [line for line in lines if line.startswith("skill: ")]
    assert skill_lines == [
        "skill: SQL core 8",
        "skill: Airflow core 6",
        "skill: Python important 7",
        "skill: Spreadsheets bonus 2",
    ], "core (must-have) links order first, ties by label"


async def test_recompute_jobs_published_only_limit_and_dedupe(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from sqlalchemy import select

    from app.models.job_model import Job, JobFamily, JobSkill
    from app.models.taxonomy_model import Skill
    from app.services.embedding_service import KIND_JOB, EmbeddingService

    family = JobFamily(key="emb-jobs", label="Embedding Jobs", path="emb-jobs")
    db.add(family)
    await db.flush()
    sql = (await db.execute(select(Skill).where(Skill.key == "data-analysis"))).scalars().first()
    python = (await db.execute(select(Skill).where(Skill.key == "programming"))).scalars().first()
    assert sql is not None and python is not None, "seeded skills present"
    published = Job(code="emb-published", title="Embed Me", family_id=family.id)
    draft = Job(code="emb-draft", title="Draft Never Embeds", family_id=family.id, status="draft")
    db.add_all([published, draft])
    await db.flush()
    db.add(JobSkill(job_id=published.id, skill_id=sql.id, required_level=8, importance="core"))
    db.add(JobSkill(job_id=published.id, skill_id=python.id, required_level=6, importance="bonus"))
    db.add(JobSkill(job_id=draft.id, skill_id=sql.id, required_level=5, importance="core"))
    await db.commit()

    service = EmbeddingService(db)
    limited = await service.recompute_jobs(limit=2)
    assert limited["candidates"] == 2, "the limit bounds the candidate scan"

    result = await service.recompute_jobs(limit=50)
    assert result["candidates"] >= 1, "every un-embedded published job is a candidate"
    assert result["embedded"] >= 1

    text_row = (
        (
            await db.execute(
                select(AIEmbedding).where(
                    AIEmbedding.entity_kind == KIND_JOB, AIEmbedding.entity_id == published.id
                )
            )
        )
        .scalars()
        .first()
    )
    assert text_row is not None
    draft_row = (
        (
            await db.execute(
                select(AIEmbedding).where(
                    AIEmbedding.entity_kind == KIND_JOB, AIEmbedding.entity_id == draft.id
                )
            )
        )
        .scalars()
        .first()
    )
    assert draft_row is None, "draft jobs never embed"

    again = await service.recompute_jobs(limit=50)
    assert again["candidates"] == 0, "the hash-deduped rows are not second candidates"

    status = await service.status()
    job_bucket = next(b for b in status if b["entity_kind"] == "job")
    assert job_bucket["count"] == limited["embedded"] + result["embedded"]


async def test_recompute_endpoint_kind_param(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from sqlalchemy import select

    from app.models.embedding_model import AIEmbedding
    from app.models.job_model import Job

    listed = (await db.execute(select(Job).where(Job.status == "published"))).scalars().all()
    assert listed, "seeded catalog carries published jobs"

    response = await client.post(
        "/api/v1/ai/embeddings/recompute", params={"kind": "job"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "job"
    assert body["embedded"] >= 1
    rows = (
        (await db.execute(select(AIEmbedding).where(AIEmbedding.entity_kind == "job")))
        .scalars()
        .all()
    )
    assert len(rows) >= 1

    unknown = await client.post(
        "/api/v1/ai/embeddings/recompute", params={"kind": "family"}, headers=auth_headers
    )
    assert unknown.status_code == 400

    default = await client.post("/api/v1/ai/embeddings/recompute", headers=auth_headers)
    assert default.status_code == 200
    assert default.json()["kind"] == "posting"
