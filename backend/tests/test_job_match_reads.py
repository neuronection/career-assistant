"""The job-detail match reads (plan 50 §7.3, P2a).

``/jobs/{ref}/similar`` and ``/jobs/{ref}/postings`` answer from the family
vector store's bounded document match and degrade to the deterministic skill
list with a structured reason. The eligibility filters (published jobs, the
live feed's ``mapped``/``new`` + hidden) are applied at hydration and can only
remove rows: a degraded response still returns the same filters' list, and a
hidden/draft row is never returned by either path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.extensions.sdk import RawPosting
from app.models.job_model import Job
from app.models.posting_model import JobPosting, PostingInteraction
from app.services.postings.postings_service import upsert_posting
from app.services.vector_index_service import VectorIndexService


async def _index(db, kind: str, source_id) -> None:
    outcome = await VectorIndexService(db).index_document(kind=kind, source_id=str(source_id))
    assert outcome.degraded is None, outcome.degraded


async def _job_by_code(db, code: str) -> Job:
    return (await db.execute(select(Job).where(Job.code == code))).scalars().one()


async def _mapped_posting(db, source, external_id: str, job: Job) -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=external_id,
            title=f"Live {external_id}",
            url=f"https://syn.example/{external_id}",
            skills_raw=[],
            raw={"description": "A live opening."},
        ),
    )
    posting.catalog_job_id = job.id
    posting.mapping_method = "manual"
    posting.mapping_reason = "test fixture"
    posting.status = "mapped"
    posting.posted_at = datetime.now(UTC) - timedelta(days=1)
    await db.flush()
    return posting


# -------------------------------------------------------------- similar jobs


async def test_similar_jobs_degrade_to_the_skill_overlap_list(
    client, auth_headers, db, seeded_catalog
):
    """No indexed job document → the deterministic skill list, with the
    structured reason — never an error, never an empty fake."""
    response = await client.get(
        "/api/v1/jobs/software-developer/similar?limit=5", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "skill_overlap"
    assert body["degraded"] == "index_missing"
    assert body["items"], "the fallback lists jobs sharing this job's skills"
    assert all(item["source"] == "skill_overlap" for item in body["items"])
    assert all(item["code"] != "software-developer" for item in body["items"])
    assert all(item["score"] > 0 for item in body["items"])


async def test_similar_jobs_uses_the_match_when_the_job_is_indexed(
    client, auth_headers, db, seeded_catalog
):
    job = await _job_by_code(db, "software-developer")
    await _index(db, "job", job.id)
    peer = (
        (
            await db.execute(
                select(Job).where(Job.code != "software-developer", Job.status == "published")
            )
        )
        .scalars()
        .first()
    )
    assert peer is not None
    await _index(db, "job", peer.id)

    response = await client.get(
        "/api/v1/jobs/software-developer/similar?limit=5", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "semantic"
    assert body["degraded"] is None
    assert body["space_key"]
    codes = [item["code"] for item in body["items"]]
    assert "software-developer" not in codes, "the query job excludes itself"
    assert all(item["source"] == "semantic" for item in body["items"])
    assert all(item["per_view"] for item in body["items"]), "per-view explainability"
    # Only published rows survive the hydration filter.
    published = {
        code
        for (code,) in (await db.execute(select(Job.code).where(Job.status == "published"))).all()
    }
    assert set(codes) <= published


async def test_similar_jobs_never_returns_a_draft(client, auth_headers, db, seeded_catalog):
    job = await _job_by_code(db, "software-developer")
    draft = await _job_by_code(db, "nurse")
    draft.status = "draft"
    await db.flush()
    await _index(db, "job", job.id)
    await _index(db, "job", draft.id)

    body = (
        await client.get("/api/v1/jobs/software-developer/similar?limit=50", headers=auth_headers)
    ).json()
    assert "nurse" not in [item["code"] for item in body["items"]]


async def test_similar_jobs_pages_stably(client, auth_headers, db, seeded_catalog):
    job = await _job_by_code(db, "software-developer")
    await _index(db, "job", job.id)
    first = (
        await client.get("/api/v1/jobs/software-developer/similar?limit=2", headers=auth_headers)
    ).json()
    again = (
        await client.get("/api/v1/jobs/software-developer/similar?limit=2", headers=auth_headers)
    ).json()
    second_page = (
        await client.get(
            "/api/v1/jobs/software-developer/similar?limit=2&offset=2", headers=auth_headers
        )
    ).json()
    assert [item["code"] for item in first["items"]] == [item["code"] for item in again["items"]]
    assert not (
        {item["code"] for item in first["items"]} & {item["code"] for item in second_page["items"]}
    ), "the offset walks a stable order"


async def test_unknown_job_is_a_404(client, auth_headers, seeded_catalog):
    for suffix in ("similar", "postings"):
        response = await client.get(f"/api/v1/jobs/nope-role/{suffix}", headers=auth_headers)
        assert response.status_code == 404


async def test_similar_jobs_uses_the_job_text_when_the_document_is_missing(
    client, auth_headers, db, seeded_catalog
):
    """The job the index has not reached still answers: its composed text is
    embedded once as the query (plan 50 §7.3's documented allowance)."""
    peer = (
        (
            await db.execute(
                select(Job).where(Job.code != "software-developer", Job.status == "published")
            )
        )
        .scalars()
        .first()
    )
    assert peer is not None
    await _index(db, "job", peer.id)  # the space exists; the query job does not

    body = (
        await client.get("/api/v1/jobs/software-developer/similar?limit=5", headers=auth_headers)
    ).json()
    assert body["source"] == "semantic"
    assert body["degraded"] is None
    assert [item["code"] for item in body["items"]] == [peer.code]
    assert body["items"][0]["per_view"]


# ----------------------------------------------------------- live postings


async def test_live_postings_degrade_to_the_catalog_map(
    client, auth_headers, db, seeded_catalog, source
):
    job = await _job_by_code(db, "software-developer")
    posting = await _mapped_posting(db, source, "live-degrade", job)

    body = (
        await client.get("/api/v1/jobs/software-developer/postings", headers=auth_headers)
    ).json()
    assert body["source"] == "catalog"
    assert body["degraded"] == "index_missing"
    assert [item["id"] for item in body["items"]] == [str(posting.id)]
    assert body["items"][0]["source"] == "catalog"


async def test_live_postings_uses_the_match_and_keeps_visibility(
    client, auth_headers, db, seeded_catalog, source
):
    job = await _job_by_code(db, "software-developer")
    visible = await _mapped_posting(db, source, "live-visible", job)
    hidden = await _mapped_posting(db, source, "live-hidden", job)
    expired = await _mapped_posting(db, source, "live-expired", job)
    expired.status = "expired"
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().one()
    db.add(
        PostingInteraction(
            posting_id=hidden.id,
            user_id=user.id,
            hidden_at=datetime.now(UTC),
        )
    )
    await db.flush()
    await _index(db, "job", job.id)
    for posting in (visible, hidden, expired):
        await _index(db, "posting", posting.id)

    body = (
        await client.get("/api/v1/jobs/software-developer/postings?limit=10", headers=auth_headers)
    ).json()
    assert body["source"] == "semantic"
    assert body["degraded"] is None
    ids = [item["id"] for item in body["items"]]
    assert str(visible.id) in ids
    assert str(hidden.id) not in ids, "a hidden posting is never returned"
    assert str(expired.id) not in ids, "an expired posting is not a live opening"
    assert all(item["source"] == "semantic" for item in body["items"])


async def test_live_postings_without_any_candidate_is_an_empty_page(
    client, auth_headers, db, seeded_catalog
):
    job = await _job_by_code(db, "software-developer")
    await _index(db, "job", job.id)

    body = (
        await client.get("/api/v1/jobs/software-developer/postings", headers=auth_headers)
    ).json()
    assert body["items"] == []
    assert body["degraded"] is None, (
        "an indexed job with no posting documents is empty, not degraded"
    )
