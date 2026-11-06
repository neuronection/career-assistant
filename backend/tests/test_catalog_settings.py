"""The mapping run controls + the re-decide action (plan 185 S6): the
``job_proposals`` switch is read per decision — flipping it is effective on
the next decision, no restart — and ``POST /admin/postings/{id}/remap``
re-runs the join without paying the extract again, MANUAL-guarded.

The semantic rescue switch is gone with the legacy embeddings store (plan 50
P1d): the long-text matcher returns on the family vector store in P2, and the
deterministic overlap decides alone until then.
"""

from sqlalchemy import select

from app.extensions.sdk import RawPosting
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting, PostingChange
from app.models.taxonomy_model import Skill
from app.services.postings.postings_service import upsert_posting


async def _run_pending_remap(db, posting_id):
    from sqlalchemy import select as sa_select

    from app.models.background_job_model import BackgroundJob
    from app.models.enums import BackgroundJobType
    from app.services.postings.mapping_remap import run_posting_remap

    job = (
        (
            await db.execute(
                sa_select(BackgroundJob)
                .where(
                    BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value,
                    BackgroundJob.payload["posting_id"].as_string() == str(posting_id),
                )
                .order_by(BackgroundJob.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    assert job is not None, "the endpoint queued a re-decision"
    return await run_posting_remap(db, job.payload, run_id=job.id)


async def _skill(db, key: str) -> Skill:
    existing = (await db.execute(select(Skill).where(Skill.key == key))).scalars().first()
    if existing is not None:
        return existing
    row = Skill(key=key, label=key.upper(), category="test")
    db.add(row)
    await db.flush()
    return row


async def _family(db) -> JobFamily:
    family = JobFamily(key="switch-family", label="Switches", path="switch-family")
    db.add(family)
    await db.flush()
    return family


async def _job(db, family: JobFamily, code: str, links) -> Job:
    job = Job(code=code, title=code.title(), family_id=family.id, status="published")
    db.add(job)
    await db.flush()
    for skill, level in links:
        db.add(JobSkill(job_id=job.id, skill_id=skill.id, required_level=level, importance="core"))
    await db.flush()
    return job


async def _posting(db, source, external_id: str, skills: list[str]) -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=external_id,
            title=f"Role {external_id}",
            url=f"https://syn.example/{external_id}",
            skills_raw=skills,
            raw={"description": "We need " + " and ".join(skills) + "."},
        ),
    )
    await db.flush()
    return posting


async def test_job_proposals_switch_off_stops_the_writer(db, client, auth_headers, kinds, source):
    for key in ("sql", "programming", "problem-solving"):
        await _skill(db, key)
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


async def test_semantic_rerank_switch_defaults_off_and_is_independent(db, client, auth_headers):
    """The mapping-settings payload carries the rerank kill switch, default
    OFF. Flipping it never touches the rescue switch, and vice versa."""
    current = await client.get("/api/v1/admin/catalog-mapping/settings", headers=auth_headers)
    assert current.status_code == 200, current.text
    assert current.json()["semantic_rerank"] is False
    assert current.json()["semantic_rescue"] is True

    rescue_off = await client.put(
        "/api/v1/admin/catalog-mapping/settings",
        json={"semantic_rescue": False},
        headers=auth_headers,
    )
    assert rescue_off.json()["semantic_rescue"] is False
    assert rescue_off.json()["semantic_rerank"] is False, "rescue off must not enable rerank"

    rerank_on = await client.put(
        "/api/v1/admin/catalog-mapping/settings",
        json={"semantic_rerank": True},
        headers=auth_headers,
    )
    assert rerank_on.json()["semantic_rerank"] is True
    assert rerank_on.json()["semantic_rescue"] is False, "rerank on must not enable rescue"

    both = await client.put(
        "/api/v1/admin/catalog-mapping/settings",
        json={"semantic_rescue": True, "semantic_rerank": False},
        headers=auth_headers,
    )
    assert both.json() == {
        "job_proposals": True,
        "semantic_rescue": True,
        "semantic_rerank": False,
    }


async def test_remap_upgrades_after_the_catalog_gains_the_skills(
    db, client, auth_headers, seeded_catalog, source
):
    """The re-decide re-runs the overlap: a posting parked in moderation maps
    as soon as a catalog job covers its skills strongly enough."""
    sql = await _skill(db, "sql")
    filler = await _skill(db, "remap-filler")
    family = await _family(db)
    posting = await _posting(db, source, "remap-1", ["sql"])
    assert posting.mapping_method is None

    job = await _job(db, family, "remap-role", [(sql, 8)])
    await db.flush()
    del filler

    remapped = await client.post(f"/api/v1/admin/postings/{posting.id}/remap", headers=auth_headers)
    assert remapped.status_code == 200, remapped.text
    assert remapped.json()["queued"] is True
    await _run_pending_remap(db, posting.id)
    await db.refresh(posting)
    assert posting.mapping_method == "skill_overlap"
    assert posting.status == "mapped"
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
    await _skill(db, "sql")
    posting = await _posting(db, source, "remap-manual", ["sql"])
    posting.mapping_method = "manual"
    posting.status = "mapped"
    await db.commit()

    refused = await client.post(f"/api/v1/admin/postings/{posting.id}/remap", headers=auth_headers)
    assert refused.status_code == 409
    await db.refresh(posting)
    assert posting.mapping_method == "manual"


async def test_remap_mapped_posting_leaves_the_proposal_queue(
    db, client, auth_headers, kinds, source
):
    """A remap that maps the posting takes it OFF the proposal queue —
    applying a stale proposal would fork the catalog and stomp the fresh
    map (implementation-review minor 2)."""
    from app.services.postings.extract_service import extract_posting_now

    for key in ("sql", "programming", "problem-solving"):
        await _skill(db, key)
    family = await _family(db)
    await db.commit()

    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="remap-proposal",
            title="Observability Engineer",
            url="https://syn.example/remap-proposal",
            skills_raw=["sql", "programming", "problem-solving"],
            raw={"description": "We need sql, programming and problem-solving."},
        ),
    )
    await db.commit()
    await extract_posting_now(db, posting)
    await db.refresh(posting)
    from app.services.postings.mapping_remap import redecide_and_propose

    await redecide_and_propose(db, posting)
    await db.refresh(posting)
    assert isinstance((posting.posting_facts or {}).get("job_proposal"), dict)

    queue = await client.get("/api/v1/admin/postings/job-proposals", headers=auth_headers)
    assert any(row["id"] == str(posting.id) for row in queue.json()["items"])

    # The join finds an answer: a published job covering the whole set.
    sql = await _skill(db, "sql")
    prog = await _skill(db, "programming")
    prob = await _skill(db, "problem-solving")
    await _job(db, family, "remap-q-role", [(sql, 8), (prog, 8), (prob, 8)])
    await db.commit()

    remapped = await client.post(f"/api/v1/admin/postings/{posting.id}/remap", headers=auth_headers)
    assert remapped.status_code == 200
    await _run_pending_remap(db, posting.id)
    await db.refresh(posting)
    assert posting.mapping_method == "skill_overlap"

    queue_after = await client.get("/api/v1/admin/postings/job-proposals", headers=auth_headers)
    assert queue_after.json()["items"] == [], "a mapped posting is no longer applicable"
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
    db, client, auth_headers, seeded_catalog, source
):
    """S6.1: the retag row's operation payload IS the observability trace —
    the audit Changes drawer renders `operation` verbatim."""
    sql = await _skill(db, "sql")
    family = await _family(db)
    await _job(db, family, "summary-role", [(sql, 8)])

    posting = await _posting(db, source, "summary-1", ["sql"])
    assert posting.mapping_method == "skill_overlap"

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
    assert operation["method"] == "skill_overlap"
    assert operation["overlap_score"] is not None
    assert operation["semantic_top"] is None, "a cleared overlap never runs the rescue"
    assert operation["mapping_signals"]["semantic"] == {
        "top": None,
        "threshold": None,
        "candidates": [],
        "space_key": None,
        "degraded": None,
    }
