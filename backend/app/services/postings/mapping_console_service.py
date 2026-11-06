"""The mapping-coverage console read model (plan 205 AD5).

One bounded composition over ``job_postings`` per view: the funnel is a
single grouped aggregate folded in Python by the AD2 precedence (the typed
outcome covers the matcher decision; ``raw.description``/
``detail_fetched_at``/``extract_version``/``needs_review`` and the latest
failed extract job overlay the pre-extract buckets). Only mapped,
human-reviewed (ignored) and machine-terminal rows count as accounted for
(AD1); every actionable bucket — ``no_description``,
``detail_not_fetched``, ``extract_failed``, ``not_extracted``,
``needs_review``, ``semantic_unavailable``, ``semantic_pending``,
``unmapped_by_admin``, ``unknown`` — never does.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import sync_engine
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus, BackgroundJobType
from app.models.posting_model import JobPosting, JobSource
from app.models.settings_model import AppSetting
from app.services.postings.detail_service import MAX_ATTEMPTS as DETAIL_MAX_ATTEMPTS

ACTIVE_POSTING_STATUSES = ("new", "mapped")

#: The accounted-for floor (AD1) — read-only in phase 1, editable with the
#: policy in phase 2.
COVERAGE_FLOOR_KEY = "mapping.coverage_floor"
COVERAGE_FLOOR_DEFAULT = 0.95

MACHINE_TERMINAL_REASONS = ("no_skills", "below_threshold", "no_candidate")
ACTIONABLE_REASONS = (
    "semantic_unavailable",
    "semantic_pending",
    "unmapped_by_admin",
)


def _is_postgres(db: AsyncSession) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def _description_expr(db: AsyncSession):
    if _is_postgres(db):
        return func.coalesce(JobPosting.raw.op("->>")("description"), "")
    return func.coalesce(func.json_extract(JobPosting.raw, "$.description"), "")


def _failed_extract_exists(db: AsyncSession):
    """EXISTS: a failed ``posting_extract`` job for this posting.

    The job payload stores ``str(uuid)``; SQLite stores UUIDs as 32-hex, so
    both sides are dash-normalized there.
    """
    from typing import Any as _Any

    from sqlalchemy import Text, cast

    payload_id: _Any
    posting_id: _Any
    if _is_postgres(db):
        payload_id = BackgroundJob.payload.op("->>")("posting_id")
        posting_id = cast(JobPosting.id, Text())
    else:
        payload_id = func.replace(func.json_extract(BackgroundJob.payload, "$.posting_id"), "-", "")
        posting_id = func.replace(cast(JobPosting.id, Text()), "-", "")
    return (
        select(1)
        .where(
            BackgroundJob.job_type == BackgroundJobType.POSTING_EXTRACT.value,
            BackgroundJob.status == BackgroundJobStatus.FAILED.value,
            payload_id == posting_id,
        )
        .exists()
    )


def fold_funnel_row(row: Any) -> str:
    """Fold one grouped (state-relevant columns) combo into its funnel state.

    The precedence IS the contract (plan 205 AD2) — shared with the tests
    and the triage filter.
    """
    (
        is_mapped,
        review_state,
        no_description,
        no_detail,
        extract_failed,
        no_extract,
        needs_review,
        outcome_reason,
    ) = row
    if is_mapped:
        return "mapped"
    if review_state == "ignored":
        return "ignored"
    if no_description:
        return "no_description"
    if no_detail:
        return "detail_not_fetched"
    if extract_failed:
        return "extract_failed"
    if no_extract:
        return "not_extracted"
    if needs_review:
        return "needs_review"
    if outcome_reason in ("semantic_unavailable", "semantic_pending"):
        return str(outcome_reason)
    if outcome_reason in MACHINE_TERMINAL_REASONS:
        return str(outcome_reason)
    if outcome_reason == "unmapped_by_admin":
        return "unmapped_by_admin"
    return "unknown"


async def _coverage_floor(db: AsyncSession) -> float:
    row = await db.execute(select(AppSetting).where(AppSetting.key == COVERAGE_FLOOR_KEY))
    setting = row.scalars().first()
    if setting is None:
        return COVERAGE_FLOOR_DEFAULT
    try:
        value = float((setting.value or {}).get("floor", COVERAGE_FLOOR_DEFAULT))
    except (TypeError, ValueError):
        return COVERAGE_FLOOR_DEFAULT
    return min(1.0, max(0.0, value))


async def funnel(db: AsyncSession) -> dict[str, Any]:
    """Active-posting funnel counts (one grouped aggregate, AD5)."""
    no_description = func.coalesce(_description_expr(db), "") == ""
    no_detail = JobPosting.detail_fetched_at.is_(None)
    no_extract = JobPosting.extract_version.is_(None)
    extract_failed = _failed_extract_exists(db) | (
        JobPosting.detail_attempts >= DETAIL_MAX_ATTEMPTS
    )
    columns = (
        JobPosting.catalog_job_id.is_(None).label("is_unmapped"),
        JobPosting.mapping_review_state,
        no_description.label("no_description"),
        no_detail.label("no_detail"),
        extract_failed.label("extract_failed"),
        no_extract.label("no_extract"),
        JobPosting.needs_review,
        JobPosting.mapping_outcome_reason,
    )
    rows = await db.execute(
        select(*columns, func.count().label("n"))
        .where(JobPosting.status.in_(ACTIVE_POSTING_STATUSES))
        .group_by(*columns)
    )
    states: dict[str, int] = {}
    total = 0
    for row in rows.all():
        count = int(row.n)
        total += count
        state = fold_funnel_row(
            (
                not row.is_unmapped,
                row.mapping_review_state,
                bool(row.no_description),
                bool(row.no_detail),
                bool(row.extract_failed),
                bool(row.no_extract),
                bool(row.needs_review),
                row.mapping_outcome_reason,
            )
        )
        states[state] = states.get(state, 0) + count
    return {"total": total, "states": states}


def _accounted(states: dict[str, int]) -> dict[str, int]:
    mapped = states.get("mapped", 0)
    machine = sum(states.get(reason, 0) for reason in MACHINE_TERMINAL_REASONS)
    human = states.get("ignored", 0)
    return {
        "mapped": mapped,
        "machine_terminal": machine,
        "human_terminal": human,
        "total": mapped + machine + human,
    }


async def _methods(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(
        select(JobPosting.mapping_method, func.count())
        .where(
            JobPosting.status.in_(ACTIVE_POSTING_STATUSES),
            JobPosting.catalog_job_id.isnot(None),
        )
        .group_by(JobPosting.mapping_method)
    )
    return {str(method or "unknown"): int(count) for method, count in rows.all()}


async def _reasons(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(
        select(JobPosting.mapping_outcome_reason, func.count())
        .where(
            JobPosting.status.in_(ACTIVE_POSTING_STATUSES),
            JobPosting.mapping_outcome_state == "unmapped",
        )
        .group_by(JobPosting.mapping_outcome_reason)
    )
    return {str(reason or "unknown"): int(count) for reason, count in rows.all()}


async def _proposals_pending(db: AsyncSession) -> int:
    from app.services.postings.job_proposal_service import pending_predicate

    rows = await db.execute(
        select(func.count())
        .select_from(JobPosting)
        .where(
            JobPosting.status.in_(ACTIVE_POSTING_STATUSES),
            pending_predicate(db.get_bind().dialect.name),
        )
    )
    return int(rows.scalar_one())


async def _last_remap(db: AsyncSession) -> dict[str, Any] | None:
    row = (
        (
            await db.execute(
                select(BackgroundJob)
                .where(BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value)
                .order_by(BackgroundJob.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        return None
    result = row.result if isinstance(row.result, dict) else {}
    return {
        "job_id": str(row.id),
        "status": str(row.status),
        "created_at": row.created_at.isoformat() if row.created_at is not None else None,
        "error": result.get("error"),
    }


def _retrieval_health() -> dict[str, Any]:
    from app.services.vector_status import read_health
    from app.storage.vector_store import VectorStoreService

    with Session(sync_engine) as session:
        return read_health(session, store=VectorStoreService(sync_engine))


async def overview(db: AsyncSession) -> dict[str, Any]:
    """The Tools → Mappings overview read model (AD5)."""
    from app.services.postings.catalog_settings import (
        job_proposals_enabled,
        semantic_rerank_enabled,
        semantic_rescue_enabled,
    )
    from app.services.postings.mapping_outcome_backfill import legacy_outcome_count

    funnel_counts = await funnel(db)
    states = funnel_counts["states"]
    active = funnel_counts["total"]
    accounted = _accounted(states)
    floor = await _coverage_floor(db)
    rate = (accounted["total"] / active) if active else 1.0
    return {
        "active": active,
        "described": active - states.get("no_description", 0),
        "extracted": active
        - states.get("not_extracted", 0)
        - states.get("no_description", 0)
        - states.get("detail_not_fetched", 0)
        - states.get("extract_failed", 0),
        "mapped": accounted["mapped"],
        "accounted": accounted,
        "states": states,
        "gate": {
            "floor": floor,
            "rate": round(rate, 4),
            "pass": rate >= floor,
        },
        "methods": await _methods(db),
        "reasons": await _reasons(db),
        "proposals_pending": await _proposals_pending(db),
        "switches": {
            "job_proposals": await job_proposals_enabled(db),
            "semantic_rescue": await semantic_rescue_enabled(db),
            "semantic_rerank": await semantic_rerank_enabled(db),
        },
        "last_remap": await _last_remap(db),
        "health": _retrieval_health(),
        "legacy_outcome_count": await legacy_outcome_count(db),
    }


# ------------------------------------------------- breakdowns (S4): sources / job types


async def sources_breakdown(db: AsyncSession) -> list[dict[str, Any]]:
    """The per-source funnel (AD5): one grouped aggregate over the active
    postings folded by the shared precedence, joined onto the source row
    for the display fields and the detail mode."""
    from app.services.postings.detail_service import detail_mode

    expr = _state_expression(db)
    rows = (
        await db.execute(
            select(JobPosting.source_id, expr.label("funnel_state"), func.count())
            .where(JobPosting.status.in_(ACTIVE_POSTING_STATUSES))
            .group_by(JobPosting.source_id, expr)
        )
    ).all()
    per_source: dict[str, dict[str, int]] = {}
    for source_id, funnel_state, count in rows:
        bucket = per_source.setdefault(str(source_id), {})
        bucket[funnel_state] = bucket.get(funnel_state, 0) + int(count)

    source_rows = (await db.execute(select(JobSource))).scalars().all()
    known = {row.id for row in source_rows}
    for orphan in set(per_source) - {str(value) for value in known}:
        per_source.setdefault(orphan, {})

    reason_rows = (
        await db.execute(
            select(JobPosting.source_id, JobPosting.mapping_outcome_reason, func.count())
            .where(
                JobPosting.status.in_(ACTIVE_POSTING_STATUSES),
                JobPosting.mapping_outcome_state == "unmapped",
            )
            .group_by(JobPosting.source_id, JobPosting.mapping_outcome_reason)
        )
    ).all()
    reasons_by_source: dict[str, dict[str, int]] = {}
    for source_id, reason, count in reason_rows:
        bucket = reasons_by_source.setdefault(str(source_id), {})
        bucket[str(reason or "unknown")] = int(count)

    result = []
    for row in sorted(source_rows, key=lambda value: value.title or value.key):
        states = per_source.get(str(row.id), {})
        active = sum(states.values())
        accounted = _accounted(states)
        result.append(
            {
                "source_id": str(row.id),
                "key": row.key,
                "title": row.title or row.key,
                "kind": row.kind,
                "detail_mode": detail_mode(row),
                "paused": row.paused_at is not None,
                "active": active,
                "described": active - states.get("no_description", 0),
                "extracted": active
                - states.get("not_extracted", 0)
                - states.get("no_description", 0)
                - states.get("detail_not_fetched", 0)
                - states.get("extract_failed", 0),
                "mapped": states.get("mapped", 0),
                "accounted": accounted["total"],
                "states": states,
                "reasons": reasons_by_source.get(str(row.id), {}),
                "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
            }
        )
    for source_id, states in sorted(per_source.items()):
        if source_id in {entry["source_id"] for entry in result}:
            continue
        active = sum(states.values())
        result.append(
            {
                "source_id": source_id,
                "key": source_id,
                "title": source_id,
                "kind": "deleted",
                "detail_mode": "unknown",
                "paused": False,
                "active": active,
                "described": active - states.get("no_description", 0),
                "extracted": active
                - states.get("not_extracted", 0)
                - states.get("no_description", 0)
                - states.get("detail_not_fetched", 0)
                - states.get("extract_failed", 0),
                "mapped": states.get("mapped", 0),
                "accounted": _accounted(states)["total"],
                "states": states,
                "reasons": reasons_by_source.get(source_id, {}),
                "last_run_at": None,
            }
        )
    return result


#: The job-type breakdown's proposal-cluster cap (AD5: bounded).
PROPOSAL_CLUSTER_CAP = 12


async def job_types_breakdown(db: AsyncSession) -> dict[str, Any]:
    """The per-job-type table (S4): published types with their family,
    mapped postings, open roles and the zero-posting flag, plus the
    proposed-type clusters from the v2 proposals (capped)."""
    from app.models.job_model import Job, JobFamily
    from app.services.catalog.job_service import JobService

    mapped_rows = (
        await db.execute(
            select(JobPosting.catalog_job_id, func.count())
            .where(
                JobPosting.status.in_(ACTIVE_POSTING_STATUSES),
                JobPosting.catalog_job_id.isnot(None),
            )
            .group_by(JobPosting.catalog_job_id)
        )
    ).all()
    mapped_counts = {job_id: int(count) for job_id, count in mapped_rows}

    jobs = (await db.execute(select(Job).where(Job.status == "published"))).scalars().all()
    families = (await db.execute(select(JobFamily))).scalars().all()
    family_labels = {family.id: family.label for family in families}
    job_ids = [job.id for job in jobs]
    open_counts = await JobService(db).open_role_counts(job_ids)

    items = []
    for job in sorted(jobs, key=lambda value: value.code):
        mapped = mapped_counts.get(job.id, 0)
        items.append(
            {
                "job_id": str(job.id),
                "code": job.code,
                "title": job.title,
                "family": family_labels.get(job.family_id),
                "mapped_postings": mapped,
                "open_roles": int(open_counts.get(job.id, 0)),
                "zero_postings": mapped == 0,
            }
        )

    from typing import Any as _Any

    dialect = db.get_bind().dialect.name
    cluster_key: _Any
    if dialect == "postgresql":
        cluster_key = JobPosting.posting_facts.op("->")("job_proposal").op("->>")("job_type")
    else:
        cluster_key = func.json_extract(JobPosting.posting_facts, "$.job_proposal.job_type")
    from app.services.postings.job_proposal_service import pending_predicate

    cluster_rows = (
        await db.execute(
            select(cluster_key, func.count())
            .where(
                JobPosting.status.in_(ACTIVE_POSTING_STATUSES),
                pending_predicate(dialect),
            )
            .group_by(cluster_key)
            .order_by(func.count().desc())
            .limit(PROPOSAL_CLUSTER_CAP)
        )
    ).all()
    clusters = [
        {"job_type": str(key or "unknown"), "postings": int(count)} for key, count in cluster_rows
    ]
    return {"items": items, "proposal_clusters": clusters}


# --------------------------------------------------------------- triage list (S3)


def _state_expression(db: AsyncSession):
    """The AD2 funnel precedence as one SQL CASE (the list filter source).

    Mirrors :func:`fold_funnel_row` — the tests pin the fold on both and
    the two must never drift.
    """
    from sqlalchemy import case

    no_description = func.coalesce(_description_expr(db), "") == ""
    no_detail = JobPosting.detail_fetched_at.is_(None)
    no_extract = JobPosting.extract_version.is_(None)
    extract_failed = _failed_extract_exists(db) | (
        JobPosting.detail_attempts >= DETAIL_MAX_ATTEMPTS
    )
    whens = [
        (JobPosting.catalog_job_id.isnot(None), "mapped"),
        (JobPosting.mapping_review_state == "ignored", "ignored"),
        (no_description, "no_description"),
        (no_detail, "detail_not_fetched"),
        (extract_failed, "extract_failed"),
        (no_extract, "not_extracted"),
        (JobPosting.needs_review.is_(True), "needs_review"),
        (
            JobPosting.mapping_outcome_reason.in_(ACTIONABLE_REASONS),
            JobPosting.mapping_outcome_reason,
        ),
        (
            JobPosting.mapping_outcome_reason.in_(MACHINE_TERMINAL_REASONS),
            JobPosting.mapping_outcome_reason,
        ),
        (JobPosting.mapping_outcome_reason == "unmapped_by_admin", "unmapped_by_admin"),
    ]
    return case(*whens, else_="unknown")


async def unmapped_list(
    db: AsyncSession,
    *,
    state: str | None = None,
    source_id: uuid.UUID | None = None,
    needs_review: bool | None = None,
    detail_state: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """The bounded triage queue (AD5): keyset-paginated, no offset skips.

    Ordered by ``(created_at, id)`` — columns the decisions do not
    rewrite, so a cursor can never skip or repeat rows. ``states`` is the
    full-funnel count map (the filter chips' truth).
    """
    from app.core.errors import ValidationError

    if detail_state not in (None, "missing", "fetched"):
        raise ValidationError("detail_state must be 'missing' or 'fetched'")
    from sqlalchemy.sql.elements import ColumnElement

    from app.core.keyset import decode_cursor, encode_cursor

    after = decode_cursor(cursor, types=(datetime, uuid.UUID)) if cursor else None
    expr = _state_expression(db)
    conditions: list[ColumnElement[bool]] = [JobPosting.status.in_(ACTIVE_POSTING_STATUSES)]
    if state is not None:
        conditions.append(expr == state)
    if source_id is not None:
        conditions.append(JobPosting.source_id == source_id)
    if needs_review is not None:
        conditions.append(JobPosting.needs_review.is_(needs_review))
    if detail_state == "missing":
        conditions.append(JobPosting.detail_fetched_at.is_(None))
    elif detail_state == "fetched":
        conditions.append(JobPosting.detail_fetched_at.isnot(None))
    if q:
        conditions.append(JobPosting.title.ilike(f"%{q}%"))
    query = select(JobPosting, expr.label("funnel_state")).where(*conditions)
    if after is not None:
        from sqlalchemy import and_, or_

        query = query.where(
            or_(
                JobPosting.created_at > after[0],
                and_(JobPosting.created_at == after[0], JobPosting.id > after[1]),
            )
        )
    query = query.order_by(JobPosting.created_at, JobPosting.id).limit(limit + 1)
    rows = (await db.execute(query)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    total_rows = await db.execute(select(func.count()).select_from(JobPosting).where(*conditions))
    total = int(total_rows.scalar_one())

    items = []
    for posting, funnel_state in rows:
        features = posting.mapping_features if isinstance(posting.mapping_features, dict) else {}
        candidates = features.get("candidates") or []
        top = candidates[0] if candidates and isinstance(candidates[0], dict) else None
        facts = posting.posting_facts if isinstance(posting.posting_facts, dict) else {}
        review = facts.get("mapping_review")
        review = review if isinstance(review, dict) else None
        proposal = facts.get("job_proposal")
        proposal_state = proposal.get("status") if isinstance(proposal, dict) else None
        items.append(
            {
                "id": str(posting.id),
                "ref": posting.ref,
                "title": posting.title,
                "org": posting.org,
                "source_id": str(posting.source_id),
                "state": funnel_state,
                "outcome_reason": posting.mapping_outcome_reason,
                "needs_review": posting.needs_review,
                "detail_fetched": posting.detail_fetched_at is not None,
                "extract_version": posting.extract_version,
                "mapped": posting.catalog_job_id is not None,
                "catalog_job_id": str(posting.catalog_job_id) if posting.catalog_job_id else None,
                "top_candidate": top,
                "proposal_state": proposal_state,
                "review": {
                    "state": posting.mapping_review_state,
                    "reason": posting.mapping_review_reason,
                    "note": (review or {}).get("note"),
                }
                if posting.mapping_review_state
                else None,
                "created_at": posting.created_at.isoformat()
                if posting.created_at is not None
                else None,
            }
        )

    counts = (await funnel(db))["states"]
    response: dict[str, Any] = {"items": items, "total": total, "states": counts}
    if has_more and items:
        last = rows[-1][0]
        response["next_cursor"] = encode_cursor((last.created_at, last.id))
    return response


# ------------------------------------------------------------------- trace (AD7)


def _bounded(value: Any, cap: int = 2000) -> Any:
    if isinstance(value, str) and len(value) > cap:
        return value[:cap] + "\u2026"
    return value


async def trace(db: AsyncSession, posting_id: uuid.UUID) -> dict[str, Any]:
    """The admin decision trace (AD7): outcome/signals/candidates plus the
    bounded journal + AI-generation ids. Never prompt/response text;
    candidate payloads come pre-capped from ``mapping_features``."""
    from app.core.errors import NotFoundError
    from app.models.posting_model import PostingChange

    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting_id))).scalars().first()
    )
    if posting is None:
        raise NotFoundError("Posting not found")
    facts = posting.posting_facts if isinstance(posting.posting_facts, dict) else {}
    features = posting.mapping_features if isinstance(posting.mapping_features, dict) else {}
    signals = facts.get("mapping_signals")
    signals = signals if isinstance(signals, dict) else {}
    proposal = facts.get("job_proposal")
    proposal = proposal if isinstance(proposal, dict) else None
    review = facts.get("mapping_review")
    review = review if isinstance(review, dict) else None

    from app.models.posting_model import MappingReview

    review_row = (
        (await db.execute(select(MappingReview).where(MappingReview.posting_id == posting.id)))
        .scalars()
        .first()
    )
    journal_rows = (
        (
            await db.execute(
                select(PostingChange)
                .where(PostingChange.posting_id == posting.id)
                .order_by(PostingChange.occurred_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    failed_extract = (
        bool(await db.scalar(select(_failed_extract_exists(db)).where(JobPosting.id == posting.id)))
        or posting.detail_attempts >= DETAIL_MAX_ATTEMPTS
    )
    generation_ids = [
        str(ref["ai_generation_id"])
        for row in journal_rows
        for ref in [row.actor_ref if isinstance(row.actor_ref, dict) else {}]
        if ref.get("ai_generation_id")
    ]
    return {
        "posting": {
            "id": str(posting.id),
            "ref": posting.ref,
            "title": _bounded(posting.title, 300),
            "org": posting.org,
            "status": posting.status,
            "catalog_job_id": str(posting.catalog_job_id) if posting.catalog_job_id else None,
            "state": fold_funnel_row(
                (
                    posting.catalog_job_id is not None,
                    posting.mapping_review_state,
                    not str((posting.raw or {}).get("description") or "").strip(),
                    posting.detail_fetched_at is None,
                    failed_extract,
                    posting.extract_version is None,
                    posting.needs_review,
                    posting.mapping_outcome_reason,
                )
            ),
            "created_at": posting.created_at.isoformat()
            if posting.created_at is not None
            else None,
        },
        "outcome": {
            "state": posting.mapping_outcome_state,
            "reason": posting.mapping_outcome_reason,
            "method": posting.mapping_method,
            "confidence": posting.mapping_confidence,
            "reason_prose": _bounded(posting.mapping_reason, 500),
        },
        "signals": signals,
        "features": {
            "mapping_version": features.get("mapping_version"),
            "space_key": features.get("space_key"),
            "degraded": features.get("degraded"),
            "policy": features.get("policy"),
            "candidates": features.get("candidates") or [],
        },
        "proposal": {
            "status": (proposal or {}).get("status"),
            "action": (proposal or {}).get("action"),
            "existing_job_code": (proposal or {}).get("existing_job_code"),
            "proposal_version": (proposal or {}).get("proposal_version"),
        }
        if proposal
        else None,
        "review": {
            "state": posting.mapping_review_state,
            "reason": posting.mapping_review_reason,
            "note": _bounded((review or {}).get("note"), 500),
            "actor": (review or {}).get("actor"),
            "at": (review or {}).get("at"),
        }
        if posting.mapping_review_state
        else None,
        "review_row": {
            "id": str(review_row.id),
            "kind": review_row.kind,
            "status": review_row.status,
        }
        if review_row is not None
        else None,
        "extract_version": posting.extract_version,
        "needs_review": posting.needs_review,
        "detail_fetched_at": posting.detail_fetched_at.isoformat()
        if posting.detail_fetched_at is not None
        else None,
        "journal": [
            {
                "id": str(row.id),
                "actor_kind": row.actor_kind,
                "operation": row.operation if isinstance(row.operation, dict) else None,
                "created_at": row.occurred_at.isoformat() if row.occurred_at is not None else None,
            }
            for row in journal_rows
        ],
        "ai_generation_ids": generation_ids,
    }


# ----------------------------------------------------------------- actions (AD6)


def _actor_ref(actor: Any) -> dict[str, str] | None:
    actor_id = getattr(actor, "id", None)
    return {"user_id": str(actor_id)} if actor_id is not None else None


async def _load_active_postings(db: AsyncSession, ids: list[uuid.UUID]) -> list[JobPosting]:
    if not ids:
        return []
    rows = (
        (
            await db.execute(
                select(JobPosting).where(
                    JobPosting.id.in_(ids), JobPosting.status.in_(ACTIVE_POSTING_STATUSES)
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {row.id: row for row in rows}
    return [by_id[value] for value in ids if value in by_id]


async def ignore_postings(
    db: AsyncSession,
    posting_ids: list[uuid.UUID],
    *,
    reason: str,
    note: str,
    actor: Any,
) -> dict[str, Any]:
    """The human ignore overlay (only while unmapped; mapped -> 409)."""
    from fastapi import HTTPException
    from starlette import status as http_status

    from app.services.postings.change_journal import (
        RETAG_FIELDS,
        PostingChangeJournal,
        snapshot,
    )
    from app.services.postings.mapping_outcome import (
        MappingReviewReason,
        write_mapping_review,
    )

    review_reason = MappingReviewReason(reason)
    rows = await _load_active_postings(db, posting_ids)
    ignored: list[str] = []
    rejected: dict[str, str] = {}
    for posting in rows:
        if posting.catalog_job_id is not None:
            rejected[str(posting.id)] = "unmap first"
            continue
        write_mapping_review(
            posting, reason=review_reason, note=note, actor_id=getattr(actor, "id", None)
        )
        PostingChangeJournal.record(
            db,
            posting.id,
            "manual",
            actor_ref=_actor_ref(actor),
            operation={"mapping_review": "ignored", "reason": review_reason.value},
            before=snapshot(posting, RETAG_FIELDS),
            after=snapshot(posting, RETAG_FIELDS),
        )
        ignored.append(str(posting.id))
    missing = [str(value) for value in posting_ids if value not in {row.id for row in rows}]
    if rejected:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            {"message": "a mapped posting cannot be ignored (unmap first)", "rejected": rejected},
        )
    return {"affected": len(ignored), "ignored": ignored, "missing": missing, "rejected": rejected}


async def unignore_postings(
    db: AsyncSession, posting_ids: list[uuid.UUID], *, actor: Any
) -> dict[str, Any]:
    from app.services.postings.change_journal import (
        RETAG_FIELDS,
        PostingChangeJournal,
        snapshot,
    )
    from app.services.postings.mapping_outcome import clear_mapping_review

    rows = await _load_active_postings(db, posting_ids)
    affected = []
    for posting in rows:
        if posting.mapping_review_state is None:
            continue
        before = snapshot(posting, RETAG_FIELDS)
        clear_mapping_review(posting)
        PostingChangeJournal.record(
            db,
            posting.id,
            "manual",
            actor_ref=_actor_ref(actor),
            operation={"mapping_review": "cleared"},
            before=before,
            after=snapshot(posting, RETAG_FIELDS),
        )
        affected.append(str(posting.id))
    return {
        "affected": len(affected),
        "unignored": affected,
        "missing": [str(v) for v in posting_ids if v not in {r.id for r in rows}],
    }


async def unmap_postings(
    db: AsyncSession, posting_ids: list[uuid.UUID], *, actor: Any
) -> dict[str, Any]:
    """The inverse of map (AD6): clear the link, write
    ``unmapped_by_admin``, clear the overlay so a stale ignore cannot
    resurrect, journal, return the posting to triage."""
    from fastapi import HTTPException
    from starlette import status as http_status

    from app.services.postings.change_journal import (
        RETAG_FIELDS,
        PostingChangeJournal,
        snapshot,
    )
    from app.services.postings.mapping_outcome import (
        MappingOutcomeReason,
        MappingOutcomeState,
        clear_mapping_review,
        write_mapping_outcome,
    )

    rows = await _load_active_postings(db, posting_ids)
    unmapped: list[str] = []
    rejected: dict[str, str] = {}
    for posting in rows:
        if posting.catalog_job_id is None:
            rejected[str(posting.id)] = "not mapped"
            continue
        before = snapshot(posting, RETAG_FIELDS)
        posting.catalog_job_id = None
        posting.mapping_method = None
        posting.mapping_confidence = None
        posting.status = "new"
        write_mapping_outcome(
            posting,
            state=MappingOutcomeState.UNMAPPED,
            reason=MappingOutcomeReason.UNMAPPED_BY_ADMIN,
        )
        clear_mapping_review(posting)
        PostingChangeJournal.record(
            db,
            posting.id,
            "manual",
            actor_ref=_actor_ref(actor),
            operation={"unmap": True},
            before=before,
            after=snapshot(posting, RETAG_FIELDS),
        )
        unmapped.append(str(posting.id))
    if rejected:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            {"message": "only a mapped posting can be unmapped", "rejected": rejected},
        )
    return {
        "affected": len(unmapped),
        "unmapped": unmapped,
        "missing": [str(v) for v in posting_ids if v not in {r.id for r in rows}],
    }


async def resolve_review(
    db: AsyncSession, posting_ids: list[uuid.UUID], *, note: str, actor: Any
) -> dict[str, Any]:
    """Clear ``needs_review`` with a note (not an ignore; AD6)."""
    from app.services.postings.change_journal import (
        RETAG_FIELDS,
        PostingChangeJournal,
        snapshot,
    )

    rows = await _load_active_postings(db, posting_ids)
    affected = []
    for posting in rows:
        if not posting.needs_review:
            continue
        before = snapshot(posting, RETAG_FIELDS)
        posting.needs_review = False
        facts = {**(posting.posting_facts or {})}
        facts["review_resolved"] = {
            "note": note,
            "actor": str(actor.id) if actor is not None and getattr(actor, "id", None) else None,
            "at": datetime.now(UTC).isoformat(),
        }
        posting.posting_facts = facts
        flag_modified(posting, "posting_facts")
        PostingChangeJournal.record(
            db,
            posting.id,
            "manual",
            actor_ref=_actor_ref(actor),
            operation={"review": "cleared", "note": note[:200]},
            before=before,
            after=snapshot(posting, RETAG_FIELDS),
        )
        affected.append(str(posting.id))
    return {
        "affected": len(affected),
        "reviewed": affected,
        "missing": [str(v) for v in posting_ids if v not in {r.id for r in rows}],
    }


async def queue_extract(db: AsyncSession, posting_ids: list[uuid.UUID]) -> dict[str, Any]:
    """The extract action (AD6): the ``POST /admin/postings/reextract``
    semantics — only postings with a description, queued skipped, 200 cap."""
    from app.services.postings.extract_service import queue_posting_extract

    rows = await _load_active_postings(db, posting_ids)
    by_id = {row.id: row for row in rows}
    queued = skipped = 0
    for value in posting_ids:
        posting = by_id.get(value)
        if posting is None:
            continue
        if not str((posting.raw or {}).get("description") or "").strip():
            skipped += 1
            continue
        if await queue_posting_extract(db, posting):
            queued += 1
        else:
            skipped += 1
    return {
        "queued": queued,
        "skipped": skipped,
        "missing": [str(v) for v in posting_ids if v not in by_id],
        "requested": len(posting_ids),
    }


async def queue_redecide(db: AsyncSession, posting_ids: list[uuid.UUID]) -> dict[str, Any]:
    """The re-decide action (AD6): the existing single-posting
    ``posting_remap`` (deduped), 200 cap."""
    from app.services.postings.mapping_remap import (
        enqueue_semantic_redecision,
        has_pending_semantic_redecision,
    )

    rows = await _load_active_postings(db, posting_ids)
    by_id = {row.id: row for row in rows}
    queued = skipped = 0
    for value in posting_ids:
        if value not in by_id:
            continue
        if await has_pending_semantic_redecision(db, value):
            skipped += 1
            continue
        await enqueue_semantic_redecision(db, value)
        queued += 1
    return {
        "queued": queued,
        "skipped": skipped,
        "missing": [str(v) for v in posting_ids if v not in by_id],
        "requested": len(posting_ids),
    }


__all__ = [
    "ACTIVE_POSTING_STATUSES",
    "COVERAGE_FLOOR_DEFAULT",
    "COVERAGE_FLOOR_KEY",
    "PROPOSAL_CLUSTER_CAP",
    "fold_funnel_row",
    "funnel",
    "ignore_postings",
    "job_types_breakdown",
    "overview",
    "queue_extract",
    "queue_redecide",
    "resolve_review",
    "sources_breakdown",
    "trace",
    "unignore_postings",
    "unmap_postings",
    "unmapped_list",
]
