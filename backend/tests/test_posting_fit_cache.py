"""Plan 120 — the posting-fit cache writer and its refit sweep.

Cached reads validate `inputs_hash` (and the engine's `FIT_VERSION`);
misses/stale rows recompute and write through; the read paths that see a
full feed bound how many rows they persist; `SYSTEM_REFIT_SWEEP`
backfills and refreshes in budgeted batches.
"""

import uuid as uuid_mod
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.posting_model import PostingFit
from app.services.fit.dimensions import FIT_VERSION
from app.services.posting_fit_service import (
    get_posting_fit,
    get_posting_fits_batch,
    sweep_posting_fits,
)
from tests.conftest import _make_posting, _uid


def _user_id(auth_headers) -> uuid_mod.UUID:
    return uuid_mod.UUID(_uid(auth_headers))


async def _create(db, source, external_id: str, **kw):
    return await _make_posting(db, source, external_id=external_id, **kw)


async def test_single_posting_cache_hits_when_inputs_are_unchanged(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    posting = await _create(db, source, "single-hit", title="Single hit")
    user_id = _user_id(auth_headers)
    first = await get_posting_fit(db, user_id, posting)
    row = (await db.execute(select(PostingFit))).scalars().first()
    stamp = row.computed_at

    second = await get_posting_fit(db, user_id, posting)
    db.expire_all()
    row = (await db.execute(select(PostingFit))).scalars().first()
    assert row.computed_at == stamp
    assert second["inputs_hash"] == first["inputs_hash"]
    assert second["score"] == first["score"]


async def test_single_posting_cache_recomputes_when_constraints_change(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    from app.models.user_model import Profile

    posting = await _create(db, source, "single-constraints", title="Single constraints")
    user_id = _user_id(auth_headers)
    first = await get_posting_fit(db, user_id, posting)

    profile = (await db.execute(select(Profile))).scalars().first()
    profile.constraints = {**(profile.constraints or {}), "hours_available_per_week": 5}
    await db.commit()

    second = await get_posting_fit(db, user_id, posting)
    assert second["inputs_hash"] != first["inputs_hash"]
    db.expire_all()
    row = (await db.execute(select(PostingFit))).scalars().first()
    assert row.inputs_hash == second["inputs_hash"]


async def test_fit_sort_scores_match_the_single_posting_cache(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    posting = await _create(db, source, "fit-score", title="Fit score role")
    posting_id = posting.id
    user_id = _user_id(auth_headers)
    single = await get_posting_fit(db, user_id, posting, refresh=True)
    await client.get(
        "/api/v1/postings/explore",
        params={"sort": "fit"},
        headers=auth_headers,
    )
    db.expire_all()
    cached = (
        (await db.execute(select(PostingFit).where(PostingFit.posting_id == posting_id)))
        .scalars()
        .first()
    )
    assert cached is not None
    assert float(cached.score) == single["score"]
    assert cached.inputs_hash == single["inputs_hash"]


async def test_batch_cache_writes_then_reuses_rows(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    postings = [
        await _create(db, source, f"batch-{index}", title=f"Batch {index}") for index in range(2)
    ]
    user_id = _user_id(auth_headers)
    first = await get_posting_fits_batch(db, user_id, postings)
    rows = (await db.execute(select(PostingFit))).scalars().all()
    assert len(rows) == 2
    stamps = {row.posting_id: row.computed_at for row in rows}

    second = await get_posting_fits_batch(db, user_id, postings)
    refreshed = (await db.execute(select(PostingFit))).scalars().all()
    assert {row.posting_id: row.computed_at for row in refreshed} == stamps
    assert {key: value["score"] for key, value in second.items()} == {
        key: value["score"] for key, value in first.items()
    }


async def test_batch_cache_recomputes_on_inputs_hash_mismatch(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    posting = await _create(db, source, "batch-stale", title="Batch stale")
    posting_id = posting.id
    user_id = _user_id(auth_headers)
    first = await get_posting_fits_batch(db, user_id, [posting])
    original_hash = first[posting_id]["inputs_hash"]
    row = (await db.execute(select(PostingFit))).scalars().first()
    original_stamp = row.computed_at

    posting.extract_version = 9
    await db.commit()

    refreshed = await get_posting_fits_batch(db, user_id, [posting])
    assert refreshed[posting_id]["inputs_hash"] != original_hash
    db.expire_all()
    row = (await db.execute(select(PostingFit))).scalars().first()
    assert row.inputs_hash == refreshed[posting_id]["inputs_hash"]
    assert row.computed_at > original_stamp


async def test_batch_cache_recomputes_on_engine_version_bump(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    posting = await _create(db, source, "batch-version", title="Batch version")
    user_id = _user_id(auth_headers)
    await get_posting_fits_batch(db, user_id, [posting])
    row = (await db.execute(select(PostingFit))).scalars().first()
    original_stamp = row.computed_at
    row.fit_version = FIT_VERSION - 1
    await db.commit()

    await get_posting_fits_batch(db, user_id, [posting])
    db.expire_all()
    row = (await db.execute(select(PostingFit))).scalars().first()
    assert row.fit_version == FIT_VERSION
    assert row.computed_at > original_stamp


async def test_batch_write_budget_bounds_persistence(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    postings = [
        await _create(db, source, f"budget-{index}", title=f"Budget {index}") for index in range(3)
    ]
    user_id = _user_id(auth_headers)
    result = await get_posting_fits_batch(db, user_id, postings, write_budget=1)
    assert len(result) == 3
    rows = (await db.execute(select(PostingFit))).scalars().all()
    assert len(rows) == 1


async def test_sweep_backfills_and_refreshes_in_batches(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    postings = [
        await _create(db, source, f"sweep-{index}", title=f"Sweep {index}") for index in range(3)
    ]
    first = await sweep_posting_fits(db, budget=2)
    assert first["rows"] == 2
    assert len((await db.execute(select(PostingFit))).scalars().all()) == 2

    second = await sweep_posting_fits(db, budget=5)
    assert second["rows"] == 1
    rows = (await db.execute(select(PostingFit))).scalars().all()
    assert len(rows) == 3
    assert {row.posting_id for row in rows} == {posting.id for posting in postings}

    aged = rows[0]
    aged_id = aged.posting_id
    old_stamp = datetime.now(UTC) - timedelta(days=30)
    aged.computed_at = old_stamp
    await db.commit()

    third = await sweep_posting_fits(db, budget=5)
    assert third["rows"] == 1
    db.expire_all()
    refreshed = (
        (await db.execute(select(PostingFit).where(PostingFit.posting_id == aged_id)))
        .scalars()
        .first()
    )
    assert refreshed.computed_at > old_stamp
    assert refreshed.fit_version == FIT_VERSION


async def test_refit_sweep_job_backfills_posting_fits(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    from app.services.job_worker import JobWorker, enqueue

    postings = [
        await _create(db, source, f"job-sweep-{index}", title=f"Job sweep {index}")
        for index in range(2)
    ]
    await enqueue(
        db,
        "fit_refit",
        {"scope": "stale", "posting_fit_budget": 10},
    )
    worker = JobWorker(db)
    while await worker.run_once():
        pass

    rows = (await db.execute(select(PostingFit))).scalars().all()
    assert {row.posting_id for row in rows} == {posting.id for posting in postings}
