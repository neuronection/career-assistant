"""The mapping run controls + the re-decide action (plan 185 S6): the two
``app_settings`` switches (semantic rescue, job proposals) are read per
decision — flipping one is effective on the next decision, no restart —
and ``POST /admin/postings/{id}/remap`` re-runs the join without paying
the extract again, MANUAL-guarded."""

import pytest
from sqlalchemy import select

from app.extensions.sdk import RawPosting
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting, PostingChange
from app.models.settings_model import AppSetting
from app.models.taxonomy_model import Skill
from app.services.postings.postings_service import upsert_posting

COSINE = [0.95, 0.3122498999199199]  # ≈ cos 0.95 against the [1, 0] fixture


async def _seed(db) -> tuple[Skill, JobFamily]:
    from sqlalchemy import select as sa_select

    existing = (await db.execute(sa_select(Skill).where(Skill.key == "sql"))).scalars().first()
    if existing is None:
        skill = Skill(key="sql", label="SQL", category="test")
        db.add(skill)
    else:
        skill = existing
    family = JobFamily(key="switch-family", label="Switches", path="switch-family")
    db.add(family)
    await db.commit()
    return skill, family


@pytest.fixture
def posting_vector(monkeypatch):
    async def fake_embed_texts(_db, texts, **_kw):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr("app.ai.gateway.embed_texts", fake_embed_texts)


async def _weak_posting(db, source, external_id: str) -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=external_id,
            title=f"Role {external_id}",
            url=f"https://syn.example/{external_id}",
            skills_raw=["sql"],
            raw={},
        ),
    )
    await db.commit()
    return posting


async def test_semantic_switch_off_stops_the_rescue(
    db, client, auth_headers, seeded_catalog, source, posting_vector
):
    skill, family = await _seed(db)
    filler = Skill(key="switch-filler", label="Switch Filler", category="test")
    db.add(filler)
    await db.flush()
    job = Job(
        code="switch-role",
        title="Switch Role",
        family_id=family.id,
        status="published",
    )
    db.add(job)
    await db.flush()
    db.add(JobSkill(job_id=job.id, skill_id=skill.id, required_level=1, importance="core"))
    db.add(JobSkill(job_id=job.id, skill_id=filler.id, required_level=10, importance="core"))
    await db.commit()
    from app.services.embedding_service import KIND_JOB, EmbeddingService

    await EmbeddingService(db).upsert_embedding(
        KIND_JOB, job.id, "vector fixture", vector=COSINE, commit=False
    )

    posting = await _weak_posting(db, source, "switch-on")
    assert posting.mapping_method == "semantic", "default is ON"

    off = await client.put(
        "/api/v1/admin/catalog-mapping/settings",
        json={"semantic_rescue": False},
        headers=auth_headers,
    )
    assert off.status_code == 200
    assert off.json()["semantic_rescue"] is False

    posting2 = await _weak_posting(db, source, "switch-off")
    assert posting2.mapping_method is None, "the switch is read per decision"
    signals = posting2.posting_facts["mapping_signals"]
    assert signals["semantic"]["top"] is None
    assert signals["semantic"]["candidates"] == []
    assert posting2.mapping_reason == "best overlap 0.09 below 0.34 — moderation", (
        "rescue off degrades to the exact pre-plan decision"
    )

    on = await client.put(
        "/api/v1/admin/catalog-mapping/settings",
        json={"semantic_rescue": True},
        headers=auth_headers,
    )
    assert on.json()["semantic_rescue"] is True
    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == "catalog.semantic_rescue")))
        .scalars()
        .first()
    )
    assert row is not None and row.value == {"enabled": True}, "state lives in app_settings"


async def test_job_proposals_switch_off_stops_the_writer(db, client, auth_headers, kinds, source):
    from sqlalchemy import select as sa_select

    for key in ("sql", "programming", "problem-solving"):
        existing = (await db.execute(sa_select(Skill).where(Skill.key == key))).scalars().first()
        if existing is None:
            db.add(Skill(key=key, label=key.upper(), category="test"))
    await db.commit()

    off = await client.put(
        "/api/v1/admin/catalog-mapping/settings",
        json={"job_proposals": False},
        headers=auth_headers,
    )
    assert off.json()["job_proposals"] is False

    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="switch-proposal",
            title="Observability Engineer",
            url="https://syn.example/switch-proposal",
            skills_raw=["sql"],
            raw={"description": "We need sql, programming and problem-solving."},
        ),
    )
    await db.commit()
    from app.services.postings.extract_service import extract_posting_now

    await extract_posting_now(db, posting)
    await db.refresh(posting)
    assert posting.mapping_method is None
    assert not isinstance((posting.posting_facts or {}).get("job_proposal"), dict), (
        "the switch is off — no proposal"
    )

    on = await client.put(
        "/api/v1/admin/catalog-mapping/settings",
        json={"job_proposals": True},
        headers=auth_headers,
    )
    assert on.json()["job_proposals"] is True


async def test_remap_upgrades_after_a_job_publishes(
    db, client, auth_headers, seeded_catalog, source, posting_vector
):
    skill, family = await _seed(db)
    posting = await _weak_posting(db, source, "remap-1")
    assert posting.mapping_method is None

    filler = Skill(key="remap-filler", label="Remap Filler", category="test")
    db.add(filler)
    await db.flush()
    job = Job(
        code="remap-role",
        title="Remap Role",
        family_id=family.id,
        status="published",
    )
    db.add(job)
    await db.flush()
    db.add(JobSkill(job_id=job.id, skill_id=skill.id, required_level=1, importance="core"))
    db.add(JobSkill(job_id=job.id, skill_id=filler.id, required_level=10, importance="core"))
    await db.commit()
    from app.services.embedding_service import KIND_JOB, EmbeddingService

    await EmbeddingService(db).upsert_embedding(
        KIND_JOB, job.id, "vector fixture", vector=COSINE, commit=False
    )

    remapped = await client.post(f"/api/v1/admin/postings/{posting.id}/remap", headers=auth_headers)
    assert remapped.status_code == 200, remapped.text
    body = remapped.json()
    assert body["mapping_method"] == "semantic"
    assert body["status"] == "mapped"
    assert body["catalog_job_id"] == str(job.id)
    await db.refresh(posting)
    assert posting.catalog_job_id == job.id

    rows = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == posting.id,
                    PostingChange.actor_kind == "retag",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows, "the re-decision journals"


async def test_remap_refuses_manual(db, client, auth_headers, seeded_catalog, source):
    await _seed(db)
    posting = await _weak_posting(db, source, "remap-manual")
    posting.mapping_method = "manual"
    posting.status = "mapped"
    await db.commit()

    refused = await client.post(f"/api/v1/admin/postings/{posting.id}/remap", headers=auth_headers)
    assert refused.status_code == 409
    await db.refresh(posting)
    assert posting.mapping_method == "manual"


async def test_remap_mapped_posting_leaves_the_proposal_queue(
    db, client, auth_headers, kinds, source, posting_vector
):
    """A remap that maps the posting takes it OFF the proposal queue —
    applying a stale proposal would fork the catalog and stomp the fresh
    map (implementation-review minor 2)."""
    from sqlalchemy import select as sa_select

    from app.services.embedding_service import KIND_JOB, EmbeddingService
    from app.services.postings.extract_service import extract_posting_now

    _skill, family = await _seed(db)
    for key in ("programming", "problem-solving"):
        existing = (await db.execute(sa_select(Skill).where(Skill.key == key))).scalars().first()
        if existing is None:
            db.add(Skill(key=key, label=key.upper(), category="test"))
    await db.commit()

    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="remap-proposal",
            title="Observability Engineer",
            url="https://syn.example/remap-proposal",
            skills_raw=["sql"],
            raw={"description": "We need sql, programming and problem-solving."},
        ),
    )
    await db.commit()
    await extract_posting_now(db, posting)
    await db.refresh(posting)
    assert isinstance((posting.posting_facts or {}).get("job_proposal"), dict)

    queue = await client.get("/api/v1/admin/postings/job-proposals", headers=auth_headers)
    assert any(row["id"] == str(posting.id) for row in queue.json())

    # The join finds an answer: a published, embedded job covering the set.
    sql_row = (await db.execute(sa_select(Skill).where(Skill.key == "sql"))).scalars().first()
    filler = Skill(key="remap-q-filler", label="Remap Q Filler", category="test")
    db.add(filler)
    await db.flush()
    job = Job(code="remap-q-role", title="Remap Q Role", family_id=family.id, status="published")
    db.add(job)
    await db.flush()
    db.add(JobSkill(job_id=job.id, skill_id=sql_row.id, required_level=1, importance="core"))
    db.add(JobSkill(job_id=job.id, skill_id=filler.id, required_level=10, importance="core"))
    await db.commit()
    await EmbeddingService(db).upsert_embedding(
        KIND_JOB, job.id, "vector fixture", vector=COSINE, commit=False
    )

    remapped = await client.post(f"/api/v1/admin/postings/{posting.id}/remap", headers=auth_headers)
    assert remapped.status_code == 200
    assert remapped.json()["mapping_method"] == "semantic"

    queue_after = await client.get("/api/v1/admin/postings/job-proposals", headers=auth_headers)
    assert queue_after.json() == [], "a mapped posting is no longer applicable"
    stale = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": "switch-family"},
        headers=auth_headers,
    )
    assert stale.status_code == 404, "applying a stale proposal refuses"


async def test_remap_unknown_posting_404(db, client, auth_headers, seeded_catalog):
    missing = await client.post(
        "/api/v1/admin/postings/00000000-0000-0000-0000-000000000000/remap",
        headers=auth_headers,
    )
    assert missing.status_code == 404


async def test_retag_operation_carries_the_join_summary(
    db, client, auth_headers, seeded_catalog, source, posting_vector
):
    """S6.1: the retag row's operation payload IS the observability trace —
    the audit Changes drawer renders `operation` verbatim."""
    skill, family = await _seed(db)
    filler = Skill(key="summary-filler", label="Summary Filler", category="test")
    db.add(filler)
    await db.flush()
    job = Job(code="summary-role", title="Summary Role", family_id=family.id, status="published")
    db.add(job)
    await db.flush()
    db.add(JobSkill(job_id=job.id, skill_id=skill.id, required_level=1, importance="core"))
    db.add(JobSkill(job_id=job.id, skill_id=filler.id, required_level=10, importance="core"))
    await db.commit()
    from app.services.embedding_service import KIND_JOB, EmbeddingService

    await EmbeddingService(db).upsert_embedding(
        KIND_JOB, job.id, "vector fixture", vector=COSINE, commit=False
    )

    posting = await _weak_posting(db, source, "summary-1")
    assert posting.mapping_method == "semantic"

    rows = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == posting.id,
                    PostingChange.actor_kind == "retag",
                )
            )
        )
        .scalars()
        .all()
    )
    [decision] = [row for row in rows if "method" in (row.operation or {})]
    operation = decision.operation
    assert operation["method"] == "semantic"
    assert operation["overlap_score"] is not None
    assert operation["semantic_top"] == 0.95
    assert operation["mapping_signals"]["semantic"]["candidates"][0]["code"] == "summary-role"
