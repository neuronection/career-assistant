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
    body = remapped.json()
    assert body["mapping_method"] == "skill_overlap"
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
    assert isinstance((posting.posting_facts or {}).get("job_proposal"), dict)

    queue = await client.get("/api/v1/admin/postings/job-proposals", headers=auth_headers)
    assert any(row["id"] == str(posting.id) for row in queue.json())

    # The join finds an answer: a published job covering the whole set.
    sql = await _skill(db, "sql")
    prog = await _skill(db, "programming")
    prob = await _skill(db, "problem-solving")
    await _job(db, family, "remap-q-role", [(sql, 8), (prog, 8), (prob, 8)])
    await db.commit()

    remapped = await client.post(f"/api/v1/admin/postings/{posting.id}/remap", headers=auth_headers)
    assert remapped.status_code == 200
    assert remapped.json()["mapping_method"] == "skill_overlap"

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
    assert operation["semantic_top"] is None, "no semantic path runs in this slice"
    assert operation["mapping_signals"]["semantic"] == {
        "top": None,
        "threshold": None,
        "candidates": [],
    }
