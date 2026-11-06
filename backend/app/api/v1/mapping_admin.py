"""Admin mapping-coverage console reads and actions (plan 205 AD5/S2).

The ``retrieval_admin`` pattern: one admin-only ``/admin/mappings``
namespace over one service seam, bounded queries, no second ledger — the
console's actions journal through ``PostingChangeJournal``/``ai_generations``
like every other mapping writer. Phase 1 ships the overview read model and
the backfill action; the triage queue/trace/actions are S3, the
breakdowns S4, quality/policy phase 2, snapshots phase 3.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user_model import User
from app.services.deps import require_admin
from app.services.postings import mapping_console_service as console

router = APIRouter(
    prefix="/admin/mappings", tags=["mapping-admin"], dependencies=[Depends(require_admin)]
)


class MappingBackfillIn(BaseModel):
    limit: int = Field(default=200, ge=1, le=500)
    posting_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)


class MappingIdsIn(BaseModel):
    posting_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class MappingIgnoreIn(MappingIdsIn):
    reason: str = Field(pattern="^(no_good_type|multi_role|not_a_job|duplicate|other)$")
    note: str = Field(default="", max_length=500)


class MappingReviewIn(MappingIdsIn):
    note: str = Field(default="", max_length=500)


class MappingGoldenIn(BaseModel):
    posting_id: uuid.UUID
    expected_job_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=500)


class MappingSampleIn(BaseModel):
    count: int = Field(default=20, ge=1, le=50)


class MappingResolveIn(BaseModel):
    correct: bool
    expected_job_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=500)


class MappingPolicyIn(BaseModel):
    tau_job: float | None = Field(default=None, ge=0, le=1)
    delta: float | None = Field(default=None, ge=0, le=1)
    semantic_threshold: float | None = Field(default=None, ge=0, le=1)
    semantic_min_shared_skills: int | None = Field(default=None, ge=1)


class MappingPolicyDryRunIn(MappingPolicyIn):
    posting_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


def _audit(db: AsyncSession, user: User, action: str, detail: str, **fields: Any):
    from app.services.postings.mapping_audit import record_mapping_audit

    return record_mapping_audit(
        db,
        actor=str(user.id),
        action=action,
        resource=detail,
        fields=fields,
    )


@router.get("/unmapped")
async def mappings_unmapped(
    state: str | None = Query(default=None),
    source: uuid.UUID | None = Query(default=None),
    needs_review: bool | None = Query(default=None),
    detail_state: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The bounded triage queue: filterable rows with the per-state counts
    and an opaque keyset cursor (no offset skips)."""
    return await console.unmapped_list(
        db,
        state=state,
        source_id=source,
        needs_review=needs_review,
        detail_state=detail_state,
        q=q,
        cursor=cursor,
        limit=limit,
    )


@router.get("/sources")
async def mappings_sources(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The per-source funnel: total/described/extracted/mapped/accounted,
    the unmapped reasons and the source's detail mode."""
    return {"items": await console.sources_breakdown(db)}


@router.get("/job-types")
async def mappings_job_types(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The per-job-type table: mapped postings, open roles, the
    zero-posting flag and the capped proposed-type clusters."""
    return await console.job_types_breakdown(db)


@router.get("/policy")
async def mappings_policy_get(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The effective mapping policy (AD8): the four editable thresholds,
    the fixed blend/k (read-only) and the effective policy hash."""
    from app.services.postings import mapping_policy

    policy = await mapping_policy.load_mapping_policy(db)
    return {
        "tau_job": policy.tau_job,
        "delta": policy.delta,
        "semantic_threshold": policy.semantic_threshold,
        "semantic_min_shared_skills": policy.semantic_min_shared_skills,
        "blend_deterministic": mapping_policy.BLEND_DETERMINISTIC,
        "blend_semantic": mapping_policy.BLEND_SEMANTIC,
        "k": mapping_policy.CANDIDATE_K,
        "policy_hash": policy.hash,
    }


@router.put("/policy")
async def mappings_policy_put(
    payload: MappingPolicyIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Save the mapping policy (validated; effective on the next decision)
    and write one audit event. Defaults are bit-identical when unset."""
    from app.services.postings import mapping_policy

    policy = await mapping_policy.save_mapping_policy(
        db,
        payload.model_dump(exclude_none=True),
    )
    _audit(db, user, "admin.mapping.policy", f"mappings:policy:{policy.hash}")
    await db.commit()
    return {
        "tau_job": policy.tau_job,
        "delta": policy.delta,
        "semantic_threshold": policy.semantic_threshold,
        "semantic_min_shared_skills": policy.semantic_min_shared_skills,
        "policy_hash": policy.hash,
    }


@router.post("/policy/dry-run")
async def mappings_policy_dry_run(
    payload: MappingPolicyDryRunIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Dry-run the candidate policy over ≤50 postings (AD8): savepoint +
    rollback, no index/embed/spend, no deferred enqueue; reports the
    per-posting before/after and a semantic-degrade flag."""
    from app.services.postings import mapping_policy

    del user
    return await mapping_policy.dry_run_policy(
        db, payload.posting_ids, payload.model_dump(exclude_none=True, exclude={"posting_ids"})
    )


class MappingAlertsIn(BaseModel):
    coverage_floor: float = Field(ge=0, le=1)


@router.get("/alerts")
async def mappings_alerts_get(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The alert settings (AD10): the accounted-for floor."""
    from app.services.postings import mapping_ops

    return {"coverage_floor": await mapping_ops.load_coverage_floor(db)}


@router.put("/alerts")
async def mappings_alerts_put(
    payload: MappingAlertsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Save the accounted-for floor; effective on the next alert sweep."""
    from app.services.postings import mapping_ops

    floor = await mapping_ops.save_coverage_floor(db, payload.coverage_floor)
    _audit(db, user, "admin.mapping.alerts", f"mappings:alerts:floor={floor}")
    await db.commit()
    return {"coverage_floor": floor}


@router.get("/trend")
async def mappings_trend(
    limit: int = Query(default=30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The coverage snapshots, oldest first (the trend/sparkline data)."""
    from app.services.postings import mapping_ops

    return {"items": await mapping_ops.trend(db, limit=limit)}


@router.post("/snapshot")
async def mappings_snapshot(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Capture one coverage snapshot now (the manual basis)."""
    from app.services.postings import mapping_ops

    del user
    row = await mapping_ops.capture_snapshot(db, basis="manual")
    await db.commit()
    return {
        "snapshot_id": str(row.id),
        "captured_at": row.captured_at.isoformat() if row.captured_at else None,
        "total": row.total,
        "accounted": row.accounted,
    }


@router.get("/quality")
async def mappings_quality(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The quality read model (AD9): precision/recall/agreement over the
    resolved reviews (none is a class), the confusion pairs, the pending
    rows and the ADVISORY gate (no-golden until a golden set exists)."""
    from app.services.postings import mapping_quality

    payload = await mapping_quality.metrics(db)
    payload["pending"] = await mapping_quality.pending_rows(db)
    return payload


@router.post("/quality/golden")
async def mappings_quality_golden(
    payload: MappingGoldenIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Add or update the golden row for one posting (resets to pending)."""
    from app.services.postings import mapping_quality

    row = await mapping_quality.add_golden(
        db,
        posting_id=payload.posting_id,
        expected_job_id=payload.expected_job_id,
        note=payload.note,
        reviewer_id=user.id,
    )
    await db.commit()
    return {"id": str(row.id), "kind": row.kind, "status": row.status}


@router.post("/quality/sample")
async def mappings_quality_sample(
    payload: MappingSampleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Create a bounded, deterministic, source-stratified sample batch."""
    from app.services.postings import mapping_quality

    rows = await mapping_quality.create_samples(db, count=payload.count, reviewer_id=user.id)
    await db.commit()
    return {"created": len(rows), "ids": [str(row.id) for row in rows]}


@router.post("/quality/reviews/{review_id}/resolve")
async def mappings_quality_resolve(
    review_id: uuid.UUID,
    payload: MappingResolveIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Resolve one review: correct (approved; expectation defaults to the
    current mapping) or wrong (rejected; expectation = the reviewer's)."""
    from app.services.postings import mapping_quality

    row = await mapping_quality.resolve(
        db,
        review_id,
        correct=payload.correct,
        expected_job_id=payload.expected_job_id,
        note=payload.note,
        reviewer_id=user.id,
    )
    _audit(db, user, "admin.mapping.review", f"mappings:quality:{row.status}")
    await db.commit()
    return {"id": str(row.id), "status": row.status, "reviewed_at": str(row.reviewed_at)}


class MappingMapIn(BaseModel):
    posting_id: uuid.UUID
    job_id: uuid.UUID


@router.post("/map", response_model=None)
async def mappings_map(
    payload: MappingMapIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any] | JSONResponse:
    """Map one posting onto an existing PUBLISHED catalog type (AD6).

    The published/retired guard lives in ``JobProposalService.manual_map``
    (shared with the posting-endpoint moderation path); one posting at a
    time — bulk manual map is deliberately not offered. One audit event,
    journaled by the map seam.
    """
    from sqlalchemy import select

    from app.core.errors import DomainError, NotFoundError
    from app.models.posting_model import JobPosting
    from app.services.postings.job_proposal_service import JobProposalError, JobProposalService

    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == payload.posting_id)))
        .scalars()
        .first()
    )
    if posting is None:
        raise NotFoundError("Posting not found")
    try:
        job = await JobProposalService(db).manual_map(
            posting, job_id=payload.job_id, user=user, commit=False
        )
    except DomainError as exc:
        raise NotFoundError(str(exc)) from exc
    except JobProposalError as exc:
        from app.api.v1.admin import _job_proposal_error

        return _job_proposal_error(exc)
    _audit(db, user, "admin.mapping.map", f"mappings:{posting.id}")
    await db.commit()
    return {
        "id": str(posting.id),
        "status": posting.status,
        "mapping_method": posting.mapping_method,
        "catalog_job_id": str(job.id),
    }


@router.get("/postings/{posting_id}/trace")
async def mappings_trace(
    posting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The admin decision trace (AD7): outcome, signals, candidates,
    proposal state and the bounded journal/AI-generation ids."""
    return await console.trace(db, posting_id)


@router.post("/ignore")
async def mappings_ignore(
    payload: MappingIgnoreIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Write the human ignore overlay (only while unmapped; a mapped
    posting answers 409 'unmap first'). One audit event, per-posting
    journal rows."""
    result = await console.ignore_postings(
        db, payload.posting_ids, reason=payload.reason, note=payload.note, actor=user
    )
    _audit(
        db,
        user,
        "admin.mapping.ignore",
        f"mappings:{len(result['ignored'])}",
        reason=payload.reason,
    )
    await db.commit()
    return result


@router.post("/unignore")
async def mappings_unignore(
    payload: MappingIdsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    result = await console.unignore_postings(db, payload.posting_ids, actor=user)
    _audit(db, user, "admin.mapping.unignore", f"mappings:unignore:{result['affected']}")
    await db.commit()
    return result


@router.post("/unmap")
async def mappings_unmap(
    payload: MappingIdsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """The inverse of map: clear the link, write ``unmapped_by_admin``,
    clear the overlay, return the posting to triage."""
    result = await console.unmap_postings(db, payload.posting_ids, actor=user)
    _audit(db, user, "admin.mapping.unmap", f"mappings:{result['affected']}")
    await db.commit()
    return result


@router.post("/review")
async def mappings_review(
    payload: MappingReviewIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Clear ``needs_review`` with a note (not an ignore)."""
    result = await console.resolve_review(db, payload.posting_ids, note=payload.note, actor=user)
    _audit(db, user, "admin.mapping.review", f"mappings:{result['affected']}")
    await db.commit()
    return result


@router.post("/extract")
async def mappings_extract(
    payload: MappingIdsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Queue extraction for the selected postings (description-only;
    queued skipped; unknown reported)."""
    result = await console.queue_extract(db, payload.posting_ids)
    _audit(
        db,
        user,
        "admin.mapping.extract",
        f"mappings:{result['queued']}",
        skipped=result["skipped"],
    )
    await db.commit()
    return result


@router.post("/redecide")
async def mappings_redecide(
    payload: MappingIdsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Enqueue the existing single-posting re-decision (deduped) for the
    selected postings."""
    result = await console.queue_redecide(db, payload.posting_ids)
    _audit(
        db,
        user,
        "admin.mapping.redecide",
        f"mappings:{result['queued']}",
        skipped=result["skipped"],
    )
    await db.commit()
    return result


@router.get("/overview")
async def mappings_overview(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The funnel: active/described/extracted/mapped/accounted, gate,
    methods, reasons, pending proposals, last remap, retrieval health and
    the legacy (not yet derived) outcome count."""
    return await console.overview(db)


@router.post("/backfill")
async def enqueue_outcome_backfill(
    payload: MappingBackfillIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Enqueue the bounded, idempotent outcome backfill (one queued/running run)."""
    from app.services.postings.mapping_outcome_backfill import enqueue_mapping_outcome_backfill

    del user
    job, created = await enqueue_mapping_outcome_backfill(
        db, limit=payload.limit, posting_ids=payload.posting_ids
    )
    return {"queued": True, "job_id": str(job.id), "created": created}
