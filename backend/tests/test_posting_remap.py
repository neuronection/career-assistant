"""The ``POSTING_REMAP`` cutover invalidation seam (plan 50 P2b, plan 164 S3.5).

The hook is the single sweep: it enqueues one bounded job, the handler
re-decides only ``semantic``/``semantic_rerank`` rows whose recorded
``space_key`` is stale (or every semantic row when ``all_postings``), and
``manual``/terminal rows are never selected.
"""

from __future__ import annotations

from sqlalchemy import select

from app.extensions.sdk import RawPosting
from app.models.background_job_model import BackgroundJob
from app.models.enums import MappingMethod
from app.models.posting_model import JobPosting
from app.services.postings.catalog_settings import SEMANTIC_RERANK_KEY, set_switch
from app.services.postings.mapping_remap import (
    REMAP_METHODS,
    invalidate_mapping_space,
    run_posting_remap,
)
from app.services.postings.postings_service import upsert_posting


async def _posting(db, source, external_id: str, *, status: str = "new") -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=external_id,
            title=f"Role {external_id}",
            url=f"https://syn.example/{external_id}",
            skills_raw=[],
            raw={},
        ),
    )
    assert posting is not None
    posting.status = status
    await db.flush()
    return posting


def _semantic(posting: JobPosting, space_key: str | None) -> None:
    posting.mapping_method = MappingMethod.SEMANTIC.value
    posting.mapping_features = (
        {"schema_version": 1, "space_key": space_key} if space_key is not None else None
    )


async def test_invalidate_mapping_space_enqueues_one_bounded_sweep(db):
    job = await invalidate_mapping_space(db, space_key="retired-space", batch_size=25)

    assert job.job_type == "posting_remap"
    assert job.payload["space_key"] == "retired-space"
    assert job.payload["all_postings"] is False
    assert job.payload["batch_size"] == 25
    assert job.payload["continuation_key"].startswith("retired-space|space|start")


async def test_only_stale_semantic_rows_are_redecided(db, source):
    stale = await _posting(db, source, "remap-stale")
    _semantic(stale, "old-space")
    current = await _posting(db, source, "remap-current")
    _semantic(current, "new-space")
    legacy = await _posting(db, source, "remap-legacy")
    _semantic(legacy, None)
    manual = await _posting(db, source, "remap-manual")
    manual.mapping_method = MappingMethod.MANUAL.value
    manual.mapping_features = {"schema_version": 1, "space_key": "old-space"}
    overlap = await _posting(db, source, "remap-overlap")
    overlap.mapping_method = MappingMethod.SKILL_OVERLAP.value
    expired = await _posting(db, source, "remap-expired", status="expired")
    _semantic(expired, "old-space")
    await db.flush()

    result = await run_posting_remap(
        db,
        {"space_key": "old-space", "batch_size": 50, "all_postings": False},
    )

    assert result["remapped"] == 2, "the retired-space and legacy semantic rows"
    assert result["skipped"] == 1, "the row already recorded the new space"
    assert result["failed"] == 0
    assert stale.mapping_method is None
    assert current.mapping_method == MappingMethod.SEMANTIC.value
    assert current.mapping_features["space_key"] == "new-space"
    assert legacy.mapping_method is None
    assert manual.mapping_method == MappingMethod.MANUAL.value
    assert manual.mapping_features["space_key"] == "old-space"
    assert overlap.mapping_method == MappingMethod.SKILL_OVERLAP.value
    assert expired.mapping_method == MappingMethod.SEMANTIC.value
    assert expired.mapping_features["space_key"] == "old-space"


async def test_terminal_rows_are_untouched_in_both_rerank_switch_states(db, source):
    """The rerank kill switch never widens the remap domain: manual and
    terminal rows stay outside it with the switch off or on."""
    manual = await _posting(db, source, "remap-switch-manual")
    manual.mapping_method = MappingMethod.MANUAL.value
    manual.mapping_features = {"schema_version": 1, "space_key": "old-space"}
    expired = await _posting(db, source, "remap-switch-expired", status="expired")
    _semantic(expired, "old-space")
    hidden = await _posting(db, source, "remap-switch-hidden", status="hidden")
    _semantic(hidden, "old-space")
    await db.flush()

    for enabled in (False, True):
        await set_switch(db, SEMANTIC_RERANK_KEY, enabled)
        result = await run_posting_remap(
            db,
            {"space_key": "old-space", "batch_size": 50, "all_postings": False},
        )
        assert result["remapped"] == 0
        assert manual.mapping_method == MappingMethod.MANUAL.value
        assert expired.mapping_method == MappingMethod.SEMANTIC.value
        assert hidden.mapping_method == MappingMethod.SEMANTIC.value


async def test_all_postings_ignores_the_recorded_space_key(db, source):
    stale = await _posting(db, source, "remap-all-stale")
    _semantic(stale, "old-space")
    current = await _posting(db, source, "remap-all-current")
    _semantic(current, "new-space")
    await db.flush()

    result = await run_posting_remap(
        db,
        {"space_key": "old-space", "batch_size": 50, "all_postings": True},
    )

    assert result["remapped"] == 2
    assert result["skipped"] == 0
    assert stale.mapping_method is None
    assert current.mapping_method is None


async def test_a_partial_batch_enqueues_one_continuation_cursor(db, source):
    for index in range(3):
        posting = await _posting(db, source, f"remap-page-{index}")
        _semantic(posting, "old-space")
    await db.flush()

    result = await run_posting_remap(
        db,
        {"space_key": "old-space", "batch_size": 2, "all_postings": False},
    )

    assert result["remapped"] == 2
    assert result["next_after_id"] is not None
    rows = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == "posting_remap",
                    BackgroundJob.status == "queued",
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(row.payload.get("after_id") == result["next_after_id"] for row in rows)


async def test_remap_methods_are_exactly_the_semantic_methods():
    assert (
        MappingMethod.SEMANTIC.value,
        MappingMethod.SEMANTIC_RERANK.value,
    ) == REMAP_METHODS
    assert MappingMethod.MANUAL.value not in REMAP_METHODS
