"""The mapping quality review service (plan 205 AD9/S6).

One ``mapping_reviews`` row per posting: the human golden set
(``kind='golden'``, with the expected catalog type — ``none`` is a class)
and the sampled audit rows (``kind='sample'``). Metrics run over the
RESOLVED rows against the posting's current ``catalog_job_id``; the gate
is advisory — it never blocks a release and never forces a link.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.models.job_model import Job
from app.models.posting_model import JobPosting, MappingReview

logger = logging.getLogger(__name__)

#: The advisory gate: at least this many RESOLVED golden rows and at least
#: this precision before the console says "pass" (never a release gate).
GATE_MIN_GOLDEN = 30
GATE_PRECISION_FLOOR = 0.9

#: The sampled-audit batch cap (bounded, deterministic, stratified).
SAMPLE_DEFAULT = 20
SAMPLE_MAX = 50

#: Terminal postings are invisible to the funnel — never sampled.
_SAMPLE_EXCLUDED_STATUSES = ("expired", "hidden")


class ReviewKind(StrEnum):
    GOLDEN = "golden"
    SAMPLE = "sample"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


async def add_golden(
    db: AsyncSession,
    *,
    posting_id: uuid.UUID,
    expected_job_id: uuid.UUID | None,
    note: str,
    reviewer_id: uuid.UUID | None,
) -> MappingReview:
    """Add or update the golden row for one posting (unique posting).

    Updating expectation/note resets the row to ``pending`` so the next
    resolve is judged against the new expectation.
    """
    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting_id))).scalars().first()
    )
    if posting is None:
        raise NotFoundError("Posting not found")
    if expected_job_id is not None:
        job = (await db.execute(select(Job).where(Job.id == expected_job_id))).scalars().first()
        if job is None:
            raise NotFoundError("Expected job type not found")
    row = (
        (await db.execute(select(MappingReview).where(MappingReview.posting_id == posting_id)))
        .scalars()
        .first()
    )
    if row is not None and row.kind != ReviewKind.GOLDEN:
        row.kind = ReviewKind.GOLDEN
    elif row is None:
        row = MappingReview(
            posting_id=posting_id,
            kind=ReviewKind.GOLDEN,
            status=ReviewStatus.PENDING,
        )
        db.add(row)
    row.expected_job_id = expected_job_id
    row.note = note
    row.reviewer_id = reviewer_id
    row.status = ReviewStatus.PENDING
    row.reviewed_at = None
    await db.flush()
    return row


async def create_samples(
    db: AsyncSession,
    *,
    count: int = SAMPLE_DEFAULT,
    reviewer_id: uuid.UUID | None = None,
) -> list[MappingReview]:
    """Create pending sample rows (bounded, deterministic, stratified).

    Stratified by source for family coverage; excludes ignored, terminal
    and already-reviewed postings; ordering is ``(created_at, id)`` so the
    sample is reproducible.
    """
    count = max(1, min(int(count), SAMPLE_MAX))
    per_source_cap = max(2, count // 3)
    rows = (
        (
            await db.execute(
                select(JobPosting)
                .where(
                    JobPosting.status.not_in(_SAMPLE_EXCLUDED_STATUSES),
                    JobPosting.mapping_review_state.is_(None),
                    ~JobPosting.id.in_(select(MappingReview.posting_id)),
                )
                .order_by(JobPosting.created_at, JobPosting.id)
            )
        )
        .scalars()
        .all()
    )
    by_source: dict[uuid.UUID, list[JobPosting]] = {}
    for posting in rows:
        by_source.setdefault(posting.source_id, []).append(posting)
    chosen: list[JobPosting] = []
    for cap_pass in (per_source_cap, count):
        changed = True
        while len(chosen) < count and changed:
            changed = False
            for source_id in sorted(by_source, key=str):
                bucket = by_source[source_id]
                taken = sum(1 for row in chosen if row.source_id == source_id)
                if len(bucket) > taken and taken < cap_pass:
                    chosen.append(bucket[taken])
                    changed = True
                    if len(chosen) >= count:
                        break
        if len(chosen) >= count:
            break
    review_rows = [
        MappingReview(
            posting_id=posting.id,
            kind=ReviewKind.SAMPLE,
            status=ReviewStatus.PENDING,
            reviewer_id=reviewer_id,
        )
        for posting in chosen
    ]
    db.add_all(review_rows)
    await db.flush()
    return review_rows


async def resolve(
    db: AsyncSession,
    review_id: uuid.UUID,
    *,
    correct: bool,
    expected_job_id: uuid.UUID | None = None,
    note: str = "",
    reviewer_id: uuid.UUID | None = None,
) -> MappingReview:
    """Resolve one review: correct → approved (expectation defaults to the
    posting's current mapping), wrong → rejected (expectation = what the
    reviewer says it should be, or none)."""
    row = (
        (await db.execute(select(MappingReview).where(MappingReview.id == review_id)))
        .scalars()
        .first()
    )
    if row is None:
        raise NotFoundError("Review not found")
    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == row.posting_id)))
        .scalars()
        .first()
    )
    if posting is None:
        raise NotFoundError("Posting not found")
    if expected_job_id is not None:
        job = (await db.execute(select(Job).where(Job.id == expected_job_id))).scalars().first()
        if job is None:
            raise NotFoundError("Expected job type not found")
    if correct:
        row.status = ReviewStatus.APPROVED
        row.expected_job_id = (
            expected_job_id if expected_job_id is not None else posting.catalog_job_id
        )
    else:
        row.status = ReviewStatus.REJECTED
        row.expected_job_id = expected_job_id
    row.note = note or row.note
    row.reviewer_id = reviewer_id or row.reviewer_id
    row.reviewed_at = datetime.now(UTC)
    await db.flush()
    return row


async def pending_rows(db: AsyncSession, *, kind: str | None = None) -> list[dict[str, Any]]:
    """The pending review rows with their posting summary (bounded 100)."""
    query = (
        select(MappingReview)
        .options(selectinload(MappingReview.posting))
        .where(MappingReview.status == ReviewStatus.PENDING)
        .order_by(MappingReview.created_at)
        .limit(100)
    )
    if kind is not None:
        query = query.where(MappingReview.kind == kind)
    rows = (await db.execute(query)).scalars().unique().all()
    return [
        {
            "id": str(row.id),
            "kind": row.kind,
            "status": row.status,
            "expected_job_id": str(row.expected_job_id) if row.expected_job_id else None,
            "note": row.note,
            "posting": {
                "id": str(row.posting.id),
                "ref": row.posting.ref,
                "title": row.posting.title,
                "state_kind": row.posting.mapping_method,
                "catalog_job_id": str(row.posting.catalog_job_id)
                if row.posting.catalog_job_id
                else None,
            },
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


async def metrics(db: AsyncSession) -> dict[str, Any]:
    """Precision/recall/agreement over the resolved rows (``none`` is a
    class), the confusion pairs and the advisory gate."""
    rows = (
        (
            await db.execute(
                select(MappingReview)
                .options(selectinload(MappingReview.posting))
                .where(MappingReview.status != ReviewStatus.PENDING)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    job_codes: dict[str, str] = {}
    job_ids = {row.expected_job_id for row in rows if row.expected_job_id is not None} | {
        row.posting.catalog_job_id
        for row in rows
        if row.posting is not None and row.posting.catalog_job_id is not None
    }
    if job_ids:
        for job in (await db.execute(select(Job).where(Job.id.in_(job_ids)))).scalars().all():
            job_codes[str(job.id)] = job.code

    resolved = []
    for row in rows:
        predicted = row.posting.catalog_job_id if row.posting is not None else None
        expected = row.expected_job_id
        correct = predicted == expected
        resolved.append((row, predicted, expected, correct))

    def _label(value: uuid.UUID | None) -> str:
        return job_codes.get(str(value), "none") if value is not None else "none"

    golden = [entry for entry in resolved if entry[0].kind == ReviewKind.GOLDEN]
    sample = [entry for entry in resolved if entry[0].kind == ReviewKind.SAMPLE]

    def _prf(entries: list) -> dict[str, Any]:
        predicted_type = [e for e in entries if e[1] is not None]
        expected_type = [e for e in entries if e[2] is not None]
        tp = [e for e in entries if e[3] and e[1] is not None]
        precision = (len(tp) / len(predicted_type)) if predicted_type else None
        recall = (len(tp) / len(expected_type)) if expected_type else None
        agreement = (len([e for e in entries if e[3]]) / len(entries)) if entries else None
        return {
            "resolved": len(entries),
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "agreement": round(agreement, 4) if agreement is not None else None,
        }

    confusion_counter: dict[tuple[str, str], int] = {}
    for _row, predicted, expected, correct in resolved:
        if not correct:
            pair = (_label(predicted), _label(expected))
            confusion_counter[pair] = confusion_counter.get(pair, 0) + 1
    confusion = [
        {"predicted": predicted, "expected": expected, "count": count}
        for (predicted, expected), count in sorted(
            confusion_counter.items(), key=lambda item: (-item[1], item[0])
        )[:8]
    ]

    golden_stats = _prf(golden)
    golden_precision = golden_stats["precision"]
    gate_pass = (
        golden_stats["resolved"] >= GATE_MIN_GOLDEN
        and golden_precision is not None
        and golden_precision >= GATE_PRECISION_FLOOR
    )
    has_golden = (
        golden_stats["resolved"] > 0
        or (
            await db.execute(
                select(func.count())
                .select_from(MappingReview)
                .where(MappingReview.kind == ReviewKind.GOLDEN)
            )
        ).scalar_one()
        > 0
    )
    return {
        "golden": golden_stats,
        "sample": _prf(sample),
        "confusion": confusion,
        "gate": {
            "min_golden": GATE_MIN_GOLDEN,
            "precision_floor": GATE_PRECISION_FLOOR,
            "pass": gate_pass,
            "state": "pass" if gate_pass else ("no-golden" if not has_golden else "fail"),
        },
    }


__all__ = [
    "GATE_MIN_GOLDEN",
    "GATE_PRECISION_FLOOR",
    "SAMPLE_DEFAULT",
    "SAMPLE_MAX",
    "ReviewKind",
    "ReviewStatus",
    "add_golden",
    "create_samples",
    "metrics",
    "pending_rows",
    "resolve",
]
