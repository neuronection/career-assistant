"""``POSTING_REMAP`` — cutover invalidation for semantic mapping rows (plan 164 S3.5/S3.6).

Plan 50 §7.2 (blocker 4): ``mapping_features`` stamps the embedding contract's
``space_key``. When a space is retired/cut over, every row whose decision
depends on it — ``mapping_method ∈ {semantic, semantic_rerank}`` — must be
re-decided against the new active space. This module is the named seam and
the single sweep; it never runs a second, ad-hoc invalidation path.

The hook is intentionally not wired into a space-retirement action yet: plan
50 P2b ships the store and the mapping, while the cutover action itself
(build a ``building`` space, activate it, retire the old one) is plan 51's
retrieval-management surface. The exact remaining wire-up is one call in
that action, after the new space is active::

    from app.services.postings.mapping_remap import invalidate_mapping_space
    await invalidate_mapping_space(db, space_key=retired_space.key)

``space_key=None`` (or ``all_postings=True``) is the taxonomy/catalog-wide
variant: re-decide every semantic row regardless of the space it recorded.
The job pages by posting id, excludes ``manual`` (the query only selects
semantic methods) and terminal statuses, and re-runs ``decide_catalog``
without touching ``PostingSkill`` rows.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus, BackgroundJobType, MappingMethod
from app.models.posting_model import JobPosting, PostingSkill

logger = logging.getLogger(__name__)

#: The mapping methods that depend on a semantic space (never ``manual``).
REMAP_METHODS = (MappingMethod.SEMANTIC.value, MappingMethod.SEMANTIC_RERANK.value)
DEFAULT_REMAP_BATCH = 50
TERMINAL_POSTING_STATUSES = ("expired", "hidden")
#: Single-posting payload markers (plan 50 P2c.3): the request path defers the
#: rerank/rescue, and this one job re-decides exactly that posting.
SEMANTIC_REDECISION = "semantic_redecision"
SEMANTIC_POSTING_KEY = "posting_id"

ProgressCb = Callable[[int, str], Awaitable[None]]
CancelledCb = Callable[[], Awaitable[bool]]


def _continuation_key(*, space_key: str | None, all_postings: bool, after_id: str | None) -> str:
    return f"{space_key or '*'}|{'all' if all_postings else 'space'}|{after_id or 'start'}"


def _semantic_continuation_key(posting_id: str) -> str:
    return f"posting|{posting_id}"


async def has_pending_semantic_redecision(db: AsyncSession, posting_id: uuid.UUID | str) -> bool:
    """True when this posting already has a queued/running deferred pass."""
    rows = await db.execute(
        select(BackgroundJob.id).where(
            BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value,
            BackgroundJob.status.in_(
                [BackgroundJobStatus.QUEUED.value, BackgroundJobStatus.RUNNING.value]
            ),
            BackgroundJob.payload[SEMANTIC_POSTING_KEY].as_string() == str(posting_id),
        )
    )
    return rows.scalars().first() is not None


async def enqueue_semantic_redecision(
    db: AsyncSession,
    posting_id: uuid.UUID | str,
    *,
    commit: bool = False,
) -> BackgroundJob | None:
    """Queue one per-posting semantic pass in the caller's transaction.

    Deduplicated against queued/running jobs for the same posting, so a
    repeated write of one posting cannot fan out. ``commit=False`` is the
    request-path contract: the caller's commit makes the row durable.
    """
    if await has_pending_semantic_redecision(db, posting_id):
        return None
    from app.services.job_worker import enqueue

    payload: dict[str, Any] = {
        SEMANTIC_POSTING_KEY: str(posting_id),
        SEMANTIC_REDECISION: True,
        "auto_continue": False,
        "continuation_key": _semantic_continuation_key(str(posting_id)),
    }
    return await enqueue(db, BackgroundJobType.POSTING_REMAP.value, payload, commit=commit)


async def enqueue_refresh_redecision(
    db: AsyncSession, posting_id: uuid.UUID | str
) -> BackgroundJob:
    """Queue a re-decision that also refreshes the live job proposal.

    A queued/running single-posting row has its payload updated in place —
    the per-posting dedupe must not swallow the refresh flag.
    """
    from sqlalchemy.orm.attributes import flag_modified

    rows = await db.execute(
        select(BackgroundJob).where(
            BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value,
            BackgroundJob.status.in_(
                [BackgroundJobStatus.QUEUED.value, BackgroundJobStatus.RUNNING.value]
            ),
            BackgroundJob.payload[SEMANTIC_POSTING_KEY].as_string() == str(posting_id),
        )
    )
    existing = rows.scalars().first()
    if existing is not None:
        updated_payload = {**(existing.payload or {}), "refresh_proposal": True}
        existing.payload = updated_payload
        flag_modified(existing, "payload")
        await db.commit()
        await db.refresh(existing)
        return existing
    from app.services.job_worker import enqueue

    payload: dict[str, Any] = {
        SEMANTIC_POSTING_KEY: str(posting_id),
        SEMANTIC_REDECISION: True,
        "refresh_proposal": True,
        "auto_continue": False,
        "continuation_key": _semantic_continuation_key(str(posting_id)),
    }
    return await enqueue(db, BackgroundJobType.POSTING_REMAP.value, payload)


async def has_pending_remap(db: AsyncSession, continuation_key: str) -> bool:
    """True when this exact cursor already has a queued/running remap job."""
    rows = await db.execute(
        select(BackgroundJob.id).where(
            BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value,
            BackgroundJob.status.in_(
                [BackgroundJobStatus.QUEUED.value, BackgroundJobStatus.RUNNING.value]
            ),
            BackgroundJob.payload["continuation_key"].as_string() == continuation_key,
        )
    )
    return rows.scalars().first() is not None


async def enqueue_posting_remap(
    db: AsyncSession,
    *,
    space_key: str | None = None,
    all_postings: bool = False,
    batch_size: int = DEFAULT_REMAP_BATCH,
    after_id: str | None = None,
    auto_continue: bool = True,
) -> BackgroundJob:
    """Queue one bounded ``POSTING_REMAP`` run (the single invalidation sweep)."""
    from app.services.job_worker import enqueue

    payload: dict[str, Any] = {
        "space_key": space_key,
        "all_postings": bool(all_postings),
        "batch_size": max(int(batch_size), 1),
        "after_id": after_id,
        "auto_continue": bool(auto_continue),
        "continuation_key": _continuation_key(
            space_key=space_key, all_postings=all_postings, after_id=after_id
        ),
    }
    return await enqueue(db, BackgroundJobType.POSTING_REMAP.value, payload)


async def invalidate_mapping_space(
    db: AsyncSession,
    *,
    space_key: str | None,
    batch_size: int = DEFAULT_REMAP_BATCH,
    all_postings: bool = False,
) -> BackgroundJob:
    """The cutover hook: re-decide semantic mappings that depended on a space.

    Call after the new space is active and the old one is retired. A
    ``space_key`` selects rows recorded on that retired key (legacy rows
    without features are re-decided too); rows already on a different key
    are skipped. ``all_postings=True`` ignores the recorded key and
    re-decides every semantic row.
    """
    return await enqueue_posting_remap(
        db,
        space_key=space_key,
        all_postings=all_postings,
        batch_size=batch_size,
    )


async def run_posting_remap(
    db: AsyncSession,
    payload: dict[str, Any],
    *,
    run_id: uuid.UUID | None = None,
    progress: ProgressCb | None = None,
    cancelled: CancelledCb | None = None,
) -> dict[str, Any]:
    """One bounded remap batch; returns the job result and the next cursor.

    With ``posting_id`` in the payload the same vehicle runs the deferred
    single-posting semantic pass (plan 50 P2c.3): one posting, no
    ``REMAP_METHODS`` filter (a deterministic row is being refined), no
    continuation. The cutover batch/cursor mode is unchanged.
    """
    posting_id = _parse_uuid(payload.get(SEMANTIC_POSTING_KEY))
    if posting_id is not None:
        return await _run_single_posting(
            db,
            posting_id,
            run_id=run_id,
            progress=progress,
            refresh_proposal=bool(payload.get("refresh_proposal")),
        )

    from app.services.postings.postings_service import decide_catalog

    space_key = payload.get("space_key")
    all_postings = bool(payload.get("all_postings"))
    batch_size = max(int(payload.get("batch_size") or DEFAULT_REMAP_BATCH), 1)
    after_id = _parse_uuid(payload.get("after_id"))
    auto_continue = bool(payload.get("auto_continue", True))

    statement = (
        select(JobPosting)
        .where(
            JobPosting.mapping_method.in_(REMAP_METHODS),
            JobPosting.status.not_in(TERMINAL_POSTING_STATUSES),
        )
        .order_by(JobPosting.id)
        .limit(batch_size)
    )
    if after_id is not None:
        statement = statement.where(JobPosting.id > after_id)
    postings = list((await db.execute(statement)).scalars().all())

    if progress is not None:
        await progress(10, f"remapping {len(postings)} posting(s)")

    remapped = 0
    failed = 0
    skipped = 0
    last_id: uuid.UUID | None = None
    for posting in postings:
        last_id = posting.id
        if cancelled is not None and await cancelled():
            await db.commit()
            return {
                "remapped": remapped,
                "failed": failed,
                "skipped": skipped,
                "next_after_id": None,
                "space_key": space_key,
                "cancelled": True,
            }
        recorded = (posting.mapping_features or {}).get("space_key")
        if (
            not all_postings
            and space_key is not None
            and recorded is not None
            and recorded != space_key
        ):
            skipped += 1
            continue
        skill_ids = set(
            (
                await db.execute(
                    select(PostingSkill.skill_id).where(PostingSkill.posting_id == posting.id)
                )
            )
            .scalars()
            .all()
        )
        try:
            async with db.begin_nested():
                await decide_catalog(db, posting, skill_ids, run_id=run_id, defer_semantic=False)
            remapped += 1
        except Exception:
            failed += 1
            logger.info("posting remap failed for %s", posting.id, exc_info=True)
    await db.commit()

    next_after_id = str(last_id) if len(postings) >= batch_size and last_id is not None else None
    if next_after_id is not None and auto_continue and (cancelled is None or not await cancelled()):
        continuation = _continuation_key(
            space_key=space_key, all_postings=all_postings, after_id=next_after_id
        )
        if not await has_pending_remap(db, continuation):
            await enqueue_posting_remap(
                db,
                space_key=space_key,
                all_postings=all_postings,
                batch_size=batch_size,
                after_id=next_after_id,
            )
    if progress is not None:
        await progress(100, "remapped")
    return {
        "remapped": remapped,
        "failed": failed,
        "skipped": skipped,
        "next_after_id": next_after_id,
        "space_key": space_key,
        "cancelled": False,
    }


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def redecide_and_propose(
    db: AsyncSession,
    posting: JobPosting,
    *,
    run_id: uuid.UUID | None = None,
    refresh: bool = False,
    proposal_event: str = "stored",
) -> dict[str, Any]:
    """The post-semantic seam: decide, commit, then propose the residue.

    The mapping decision commits BEFORE the provider call (plans 192/194
    SQLite single-writer discipline); the proposal lands in a second short
    transaction. The extract flow never calls this — only the single-posting
    remap job and the backfill do.
    """
    from app.services.postings.postings_service import decide_catalog

    posting_id = posting.id
    skill_ids = set(
        (
            await db.execute(
                select(PostingSkill.skill_id).where(PostingSkill.posting_id == posting.id)
            )
        )
        .scalars()
        .all()
    )
    await decide_catalog(db, posting, skill_ids, run_id=run_id, defer_semantic=False)
    await db.commit()

    result: dict[str, Any] = {
        "mapping_method": posting.mapping_method,
        "proposal": None,
    }
    if posting.mapping_method is not None:
        return result
    from app.services.postings.job_proposal_service import store_job_type_proposal

    try:
        result["proposal"] = await store_job_type_proposal(
            db,
            posting,
            run_id=run_id,
            refresh=refresh,
            actor_ref={"run_id": str(run_id)} if run_id is not None else None,
            event=proposal_event,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("job proposal failed for %s", posting_id, exc_info=True)
        from app.services.postings.job_proposal_service import record_job_proposal_failure

        await record_job_proposal_failure(
            db,
            posting_id,
            reason=type(exc).__name__,
            actor_ref={"run_id": str(run_id)} if run_id is not None else None,
        )
        await db.commit()
        result["proposal"] = {"status": "failed"}
    return result


async def _run_single_posting(
    db: AsyncSession,
    posting_id: uuid.UUID,
    *,
    run_id: uuid.UUID | None = None,
    progress: ProgressCb | None = None,
    refresh_proposal: bool = False,
) -> dict[str, Any]:
    """Re-decide one posting with the semantic stages enabled (P2c.3)."""
    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting_id))).scalars().first()
    )
    result: dict[str, Any] = {
        "remapped": 0,
        "failed": 0,
        "skipped": 0,
        "next_after_id": None,
        "posting_id": str(posting_id),
        "space_key": None,
        "cancelled": False,
        "proposal": None,
    }
    if (
        posting is None
        or posting.mapping_method == MappingMethod.MANUAL.value
        or posting.status in TERMINAL_POSTING_STATUSES
    ):
        result["skipped"] = 1
        if progress is not None:
            await progress(100, "skipped")
        return result
    if progress is not None:
        await progress(10, "re-deciding posting")
    try:
        outcome = await redecide_and_propose(db, posting, run_id=run_id, refresh=refresh_proposal)
        result["proposal"] = outcome.get("proposal")
        result["remapped"] = 1
    except Exception:
        await db.rollback()
        logger.info("semantic re-decision failed for %s", posting.id, exc_info=True)
        raise
    if progress is not None:
        await progress(100, "remapped")
    return result


__all__ = [
    "DEFAULT_REMAP_BATCH",
    "REMAP_METHODS",
    "SEMANTIC_POSTING_KEY",
    "SEMANTIC_REDECISION",
    "TERMINAL_POSTING_STATUSES",
    "enqueue_posting_remap",
    "enqueue_refresh_redecision",
    "enqueue_semantic_redecision",
    "has_pending_remap",
    "has_pending_semantic_redecision",
    "invalidate_mapping_space",
    "redecide_and_propose",
    "run_posting_remap",
]
