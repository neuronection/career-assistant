"""The ``POSTING_REMAP`` cutover invalidation seam (plan 50 P2b, plan 164 S3.5).

The hook is the single sweep: it enqueues one bounded job, the handler
re-decides only ``semantic``/``semantic_rerank`` rows whose recorded
``space_key`` is stale (or every semantic row when ``all_postings``), and
``manual``/terminal rows are never selected.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions.sdk import RawPosting
from app.models.background_job_model import BackgroundJob
from app.models.enums import MappingMethod
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting
from app.models.taxonomy_model import Skill
from app.services.postings.catalog_settings import SEMANTIC_RERANK_KEY, set_switch
from app.services.postings.mapping_remap import (
    REMAP_METHODS,
    invalidate_mapping_space,
    run_posting_remap,
)
from app.services.postings.postings_service import upsert_posting


@pytest.fixture(autouse=True)
async def _reset_rerank_switch(db):
    """The switch test commits rows; reset the shipped default afterwards."""
    yield
    await set_switch(db, SEMANTIC_RERANK_KEY, False)


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


async def test_stale_scope_selects_old_versions_but_not_manual_or_terminal(db, source):
    stale_skill = await _posting(db, source, "scope-stale-skill")
    stale_skill.mapping_method = MappingMethod.SKILL_OVERLAP.value
    stale_skill.mapping_version = 2
    stale_semantic = await _posting(db, source, "scope-stale-semantic")
    _semantic(stale_semantic, "old-space")
    stale_semantic.mapping_version = 2
    current = await _posting(db, source, "scope-current")
    current.mapping_method = MappingMethod.SKILL_OVERLAP.value
    current.mapping_version = 3
    manual = await _posting(db, source, "scope-manual")
    manual.mapping_method = MappingMethod.MANUAL.value
    manual.mapping_version = 2
    terminal = await _posting(db, source, "scope-terminal", status="expired")
    terminal.mapping_method = MappingMethod.SKILL_OVERLAP.value
    terminal.mapping_version = 2
    await db.flush()

    result = await run_posting_remap(
        db,
        {"batch_size": 50, "redecide_scope": "stale"},
    )

    assert result["redecide_scope"] == "stale"
    assert result["remapped"] == 2, "the two stale non-manual active rows"
    assert stale_skill.mapping_method is None
    assert stale_semantic.mapping_method is None
    assert current.mapping_method == MappingMethod.SKILL_OVERLAP.value
    assert manual.mapping_method == MappingMethod.MANUAL.value
    assert terminal.mapping_method == MappingMethod.SKILL_OVERLAP.value


async def test_stale_scope_re_decides_an_old_skill_overlap_mapping(db, source):
    sql = Skill(key="scope-sql", label="SQL", category="test")
    python = Skill(key="scope-python", label="Python", category="test")
    db.add_all([sql, python])
    family = JobFamily(key="scope-family", label="Scope", path="scope-family")
    db.add(family)
    await db.flush()
    right = Job(code="scope-right", title="Right", family_id=family.id, status="published")
    wrong = Job(code="scope-wrong", title="Wrong", family_id=family.id, status="published")
    db.add_all([right, wrong])
    await db.flush()
    db.add(JobSkill(job_id=right.id, skill_id=sql.id, required_level=10, importance="core"))
    db.add(JobSkill(job_id=wrong.id, skill_id=python.id, required_level=10, importance="core"))
    await db.flush()

    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="scope-redo",
            title="Scope Redo",
            url="https://syn.example/scope-redo",
            skills_raw=["scope-sql"],
            raw={},
        ),
    )
    posting.catalog_job_id = wrong.id
    posting.mapping_method = MappingMethod.SKILL_OVERLAP.value
    posting.mapping_version = 2
    posting.status = "mapped"
    await db.flush()

    result = await run_posting_remap(db, {"batch_size": 50, "redecide_scope": "stale"})

    assert result["remapped"] == 1
    assert posting.catalog_job_id == right.id, "the old score/decision was recomputed"
    assert posting.mapping_version == 3
    assert posting.mapping_method == MappingMethod.SKILL_OVERLAP.value


async def test_all_scope_selects_current_and_stale_but_not_manual_or_terminal(db, source):
    stale = await _posting(db, source, "scope-all-stale")
    stale.mapping_method = MappingMethod.SKILL_OVERLAP.value
    stale.mapping_version = 2
    current = await _posting(db, source, "scope-all-current")
    current.mapping_method = MappingMethod.SKILL_OVERLAP.value
    current.mapping_version = 3
    manual = await _posting(db, source, "scope-all-manual")
    manual.mapping_method = MappingMethod.MANUAL.value
    manual.mapping_version = 2
    terminal = await _posting(db, source, "scope-all-terminal", status="hidden")
    terminal.mapping_method = MappingMethod.SKILL_OVERLAP.value
    terminal.mapping_version = 2
    await db.flush()

    result = await run_posting_remap(db, {"batch_size": 50, "redecide_scope": "all"})

    assert result["redecide_scope"] == "all"
    assert result["remapped"] == 2
    assert stale.mapping_method is None
    assert current.mapping_method is None
    assert manual.mapping_method == MappingMethod.MANUAL.value
    assert terminal.mapping_method == MappingMethod.SKILL_OVERLAP.value


async def test_the_scope_cursor_is_distinct_from_the_legacy_cursor(db, source):
    from app.services.postings.mapping_remap import enqueue_posting_remap

    stale_job = await enqueue_posting_remap(db, redecide_scope="stale")
    all_job = await enqueue_posting_remap(db, redecide_scope="all")
    legacy_job = await enqueue_posting_remap(db, space_key="retired")

    assert stale_job.payload["redecide_scope"] == "stale"
    assert stale_job.payload["continuation_key"].startswith("redecide|stale|")
    assert all_job.payload["continuation_key"].startswith("redecide|all|")
    assert legacy_job.payload["continuation_key"].startswith("retired|space|")
    assert (
        len(
            {
                stale_job.payload["continuation_key"],
                all_job.payload["continuation_key"],
                legacy_job.payload["continuation_key"],
            }
        )
        == 3
    )


async def test_a_scoped_partial_batch_continues_with_the_same_scope(db, source):
    for index in range(3):
        posting = await _posting(db, source, f"scope-page-{index}")
        posting.mapping_method = MappingMethod.SKILL_OVERLAP.value
        posting.mapping_version = 2
    await db.flush()

    result = await run_posting_remap(
        db,
        {"batch_size": 2, "redecide_scope": "stale"},
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
    continuation = next(
        row for row in rows if row.payload.get("after_id") == result["next_after_id"]
    )
    assert continuation.payload["redecide_scope"] == "stale"
    assert continuation.payload["continuation_key"].startswith("redecide|stale|")


async def test_legacy_mode_keeps_the_semantic_cutover_selection(db, source):
    skill = await _posting(db, source, "scope-legacy-skill")
    skill.mapping_method = MappingMethod.SKILL_OVERLAP.value
    skill.mapping_version = 2
    semantic = await _posting(db, source, "scope-legacy-semantic")
    _semantic(semantic, "retired-space")
    semantic.mapping_version = 2
    await db.flush()

    result = await run_posting_remap(
        db,
        {"space_key": "retired-space", "batch_size": 50, "all_postings": False},
    )

    assert result["redecide_scope"] is None
    assert result["remapped"] == 1
    assert skill.mapping_method == MappingMethod.SKILL_OVERLAP.value
    assert semantic.mapping_method is None


async def test_remap_methods_are_exactly_the_semantic_methods():
    assert (
        MappingMethod.SEMANTIC.value,
        MappingMethod.SEMANTIC_RERANK.value,
    ) == REMAP_METHODS
    assert MappingMethod.MANUAL.value not in REMAP_METHODS
