"""Admin surface: catalog moderation, user management, AI audit viewer."""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.errors import DomainError, ValidationError
from app.core.security import hash_password
from app.models.enums import BackgroundJobType
from app.models.ai_model import AIGeneration
from app.models.matching_model import MatchInsight
from app.models.user_model import User
from app.schemas.job import JobOut
from app.services.deps import get_current_user, require_admin
from app.services.job_service import JobService
from app.services.taxonomy_service import TaxonomyService

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


class BulkJobActionIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1)
    action: str  # "publish" | "reject"


class UserPatchIn(BaseModel):
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=10, max_length=128)


@router.get("/jobs", response_model=list[JobOut])
async def moderation_queue(
    job_status: str = Query(default="draft", alias="status"),
    source: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[JobOut]:
    """All users' catalog drafts (default), newest last, for moderation."""
    jobs, _ = await JobService(db).list_jobs(
        status=job_status, source=source, page_size=limit
    )
    return [JobOut.from_model(j) for j in jobs]


@router.post("/jobs/bulk")
async def bulk_job_action(
    body: BulkJobActionIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish or reject (delete) catalog drafts in bulk (admin transcends ownership)."""
    if body.action not in ("publish", "reject"):
        raise ValidationError("action must be 'publish' or 'reject'")
    service = JobService(db)
    published, rejected = 0, 0
    for job_id in body.ids:
        job = await service.get_by_code_or_id(job_id)
        if job is None:
            continue
        if body.action == "publish":
            job.status = "published"
            published += 1
            await service._refit_job(job.id)
        else:
            # relations cascade via FK; ownership rules don't bind admins here
            await db.delete(job)
            rejected += 1
    await db.commit()
    return {"published": published, "rejected": rejected}


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_admin: bool
    is_active: bool
    created_at: datetime
    token_version: int
    insight_count: int

    model_config = {"from_attributes": True}


async def _admin_user_out(db: AsyncSession, user: User) -> AdminUserOut:
    insights = (
        await db.execute(
            select(func.count(MatchInsight.id)).where(MatchInsight.user_id == user.id)
        )
    ).scalar() or 0
    return AdminUserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_admin=user.is_admin,
        is_active=user.is_active,
        created_at=user.created_at,
        token_version=user.token_version,
        insight_count=int(insights),
    )


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[AdminUserOut]:
    """All accounts with activity counts."""
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [await _admin_user_out(db, u) for u in users]


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def patch_user(
    user_id: uuid.UUID,
    data: UserPatchIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserOut:
    """Activate/deactivate or promote/demote a user (with guard rails)."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if data.is_admin is not None and data.is_admin != user.is_admin:
        if user.id == admin.id:
            raise ValidationError("You cannot change your own admin role")
        if user.is_admin and not data.is_admin:
            admins = (
                await db.execute(
                    select(func.count(User.id)).where(User.is_admin.is_(True))
                )
            ).scalar() or 0
            if admins <= 1:
                raise ValidationError("Cannot demote the last admin")
        user.is_admin = data.is_admin
        user.token_version += 1  # role changed — outstanding tokens die

    if data.is_active is not None and data.is_active != user.is_active:
        if user.id == admin.id:
            raise ValidationError("You cannot deactivate your own account")
        user.is_active = data.is_active
        user.token_version += 1  # deactivated users lose sessions immediately

    await db.commit()
    await db.refresh(user)
    return await _admin_user_out(db, user)


@router.post("/users/{user_id}/reset-password", response_model=AdminUserOut)
async def reset_password(
    user_id: uuid.UUID,
    data: ResetPasswordIn,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserOut:
    """Set a new password for a user (share it out-of-band) and revoke sessions."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user.password_hash = hash_password(data.new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.token_version += 1
    await db.commit()
    await db.refresh(user)
    return await _admin_user_out(db, user)


@router.post("/users/{user_id}/force-logout", response_model=AdminUserOut)
async def force_logout(
    user_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserOut:
    """Invalidate every outstanding token for a user."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user.token_version += 1
    await db.commit()
    await db.refresh(user)
    return await _admin_user_out(db, user)


class AIGenerationOut(BaseModel):
    id: uuid.UUID
    task_type: str
    provider: str
    model: str
    prompt: str
    output: Optional[dict]
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    latency_ms: Optional[float]
    status: str
    error: str
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/ai/generations")
async def audit_generations(
    task: str | None = Query(default=None),
    model: str | None = Query(default=None),
    generation_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Paginated AI audit trail with filters."""
    conditions = []
    if task:
        conditions.append(AIGeneration.task_type == task)
    if model:
        conditions.append(AIGeneration.model == model)
    if generation_status:
        conditions.append(AIGeneration.status == generation_status)

    base = select(AIGeneration)
    count_query = select(func.count(AIGeneration.id))
    if conditions:
        base = base.where(*conditions)
        count_query = count_query.where(*conditions)
    total = (await db.execute(count_query)).scalar() or 0
    rows = (
        (
            await db.execute(
                base.order_by(AIGeneration.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": total,
        "items": [AIGenerationOut.model_validate(r) for r in rows],
    }


@router.get("/skills/proposals")
async def skill_proposals(
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Proposed skills awaiting promotion (auto-created on unknown keys)."""
    from app.schemas.taxonomy import SkillOut

    rows = await TaxonomyService(db).proposals()
    return [SkillOut.model_validate(r).model_dump(mode="json") for r in rows]


@router.post("/skills/{skill_id}/promote")
async def promote_skill(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """proposed → active; the vocabulary stays clean via admin review."""
    from app.schemas.taxonomy import SkillOut

    try:
        skill = await TaxonomyService(db).promote(skill_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return SkillOut.model_validate(skill).model_dump(mode="json")


@router.post("/skills/{skill_id}/merge")
async def merge_skill(
    skill_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Merge a duplicate into `target_id` (aliases redirect, joins rewritten)."""
    from app.schemas.taxonomy import SkillOut

    target_id = body.get("target_id")
    if not target_id:
        raise ValidationError("target_id is required")
    try:
        skill = await TaxonomyService(db).merge(skill_id, uuid.UUID(str(target_id)))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "target_id must be a UUID"
        ) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return SkillOut.model_validate(skill).model_dump(mode="json")


@router.get("/paths")
async def path_moderation_queue(
    path_status: str = Query(default="draft", alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """All paths by status (default: AI drafts awaiting review)."""
    from app.models.career_path_model import CareerPath
    from app.services.paths_service import PathService

    rows = (
        (
            await db.execute(
                select(CareerPath)
                .options(selectinload(CareerPath.job))
                .where(CareerPath.status == path_status)
                .order_by(CareerPath.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    service = PathService(db)
    out = []
    for path in rows:
        payload = service._path_out(path).model_dump(mode="json")
        payload["job_code"] = path.job.code if path.job else None
        payload["job_title"] = path.job.title if path.job else None
        out.append(payload)
    return out


@router.post("/paths/{path_id}/publish")
async def publish_path(
    path_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish a drafted path."""
    from app.services.paths_service import PathService

    try:
        path = await PathService(db).publish(path_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"id": str(path.id), "status": path.status}


@router.post("/paths/{path_id}/reject")
async def reject_path(
    path_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a draft (published paths are withdrawn to draft instead)."""
    from app.services.paths_service import PathService

    try:
        await PathService(db).reject(path_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"id": str(path_id), "status": "rejected"}


@router.get("/postings/connectors", response_model=list[dict])
async def posting_connectors(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Registered connector engines (built-ins + allowlisted plugins)."""
    from app.connectors.registry import list_connectors

    return list_connectors()


@router.get("/postings/sources", response_model=list[dict])
async def posting_sources(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Enabled posting sources with their sync health."""
    from app.models.posting_model import JobSource

    rows = (
        (await db.execute(select(JobSource).order_by(JobSource.created_at.desc())))
        .scalars()
        .all()
    )
    return [
        {
            "id": str(s.id),
            "key": s.key,
            "connector_key": s.connector_key,
            "config": s.config,
            "enabled": s.enabled,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "sync_state": s.sync_state,
            "error": s.error,
        }
        for s in rows
    ]


@router.post("/postings/sources", status_code=201)
async def create_posting_source(
    payload: dict, db: AsyncSession = Depends(get_db)
) -> dict:
    """Enable a source: connector key + config validated against the engine."""
    from app.connectors.registry import get_connector
    from app.models.posting_model import JobSource

    key = str(payload.get("key") or "").strip()
    connector_key = str(payload.get("connector_key") or "").strip()
    config = payload.get("config") or {}
    try:
        connector = get_connector(connector_key)
        validated = connector.validate_config(config)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    source = JobSource(
        key=key,
        connector_key=connector_key,
        config=validated,
        enabled=bool(payload.get("enabled", True)),
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return {
        "id": str(source.id),
        "key": source.key,
        "connector_key": source.connector_key,
    }


@router.put("/postings/sources/{source_id}")
async def update_posting_source(
    source_id: uuid.UUID, payload: dict, db: AsyncSession = Depends(get_db)
) -> dict:
    """Edit config/enable state (config re-validated against the connector)."""
    from app.connectors.registry import get_connector
    from app.models.posting_model import JobSource

    source = (
        (await db.execute(select(JobSource).where(JobSource.id == source_id)))
        .scalars()
        .first()
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    if "config" in payload and payload["config"] is not None:
        try:
            connector = get_connector(source.connector_key)
            source.config = connector.validate_config(payload["config"])
        except DomainError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if "enabled" in payload and payload["enabled"] is not None:
        source.enabled = bool(payload["enabled"])
    await db.commit()
    return {"id": str(source.id), "enabled": source.enabled}


@router.post("/postings/sources/{source_id}/sync")
async def sync_posting_source(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manual refresh — queued via plan-12 (plan-29 schedules this later)."""
    from app.services.job_worker import enqueue

    job = await enqueue(
        db,
        BackgroundJobType.POSTING_SYNC.value,
        {"source_id": str(source_id)},
        user_id=user.id,
    )
    return {"job_id": str(job.id), "status": job.status}


@router.post("/postings/{posting_id}/map")
async def manual_map_posting(
    posting_id: uuid.UUID, payload: dict, db: AsyncSession = Depends(get_db)
) -> dict:
    """Moderation fallback: human mapping wins (method=manual, never re-mapped)."""
    from app.models.enums import MappingMethod
    from app.models.posting_model import JobPosting

    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting_id)))
        .scalars()
        .first()
    )
    if posting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posting not found")
    job_id = payload.get("catalog_job_id")
    if not job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "catalog_job_id is required")
    try:
        job = await JobService(db).require_job(uuid.UUID(str(job_id)))
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    posting.catalog_job_id = job.id
    posting.mapping_method = MappingMethod.MANUAL.value
    posting.mapping_confidence = 1.0
    posting.mapping_reason = "manually mapped by a moderator"
    posting.status = "mapped"
    await db.commit()
    return {
        "id": str(posting.id),
        "status": posting.status,
        "mapping_method": posting.mapping_method,
        "catalog_job_id": str(job.id),
    }


@router.get("/postings")
async def admin_list_postings(
    needs_review: bool | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Moderation surface (plan 31): review-flagged / unmapped postings."""
    from app.models.enums import PostingStatus
    from app.models.posting_model import JobPosting

    query = select(JobPosting).order_by(JobPosting.created_at.desc()).limit(limit)
    if needs_review is not None:
        query = query.where(JobPosting.needs_review.is_(needs_review))
    if status:
        PostingStatus(status)  # validate against the enum
        query = query.where(JobPosting.status == status)
    rows = (await db.execute(query)).scalars().all()
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "org": p.org,
            "status": p.status,
            "needs_review": p.needs_review,
            "extract_version": p.extract_version,
            "mapping_method": p.mapping_method,
            "mapping_confidence": p.mapping_confidence,
            "mapping_reason": p.mapping_reason,
            "catalog_job_id": str(p.catalog_job_id) if p.catalog_job_id else None,
            "suppressed_fields": (p.extract or {}).get("_suppressed_fields", []),
        }
        for p in rows
    ]


@router.post("/postings/{posting_id}/extract")
async def reextract_posting(
    posting_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """Re-run the deep extraction for one posting now (admin)."""
    from app.models.posting_model import JobPosting
    from app.services.extract_service import extract_posting_now

    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting_id)))
        .scalars()
        .first()
    )
    if posting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posting not found")
    try:
        return await extract_posting_now(db, posting)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/scheduler/schedules", response_model=list[dict])
async def admin_schedules(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """System schedules (owner null): next run, last status, failures."""
    from app.services.scheduler.runner import SchedulerService

    service = SchedulerService(db)
    await service.ensure_system_schedules()
    rows = await service.list_schedules(None)
    return [
        {
            "id": str(s.id),
            "kind": s.kind,
            "task": s.task,
            "trigger": s.trigger,
            "enabled": s.enabled,
            "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "last_status": s.last_status,
            "consecutive_failures": s.consecutive_failures,
            "misfire_policy": s.misfire_policy,
            "error": s.error,
        }
        for s in rows
    ]


@router.put("/scheduler/schedules/{schedule_id}")
async def admin_update_schedule(
    schedule_id: uuid.UUID, payload: dict, db: AsyncSession = Depends(get_db)
) -> dict:
    """Pause/resume a system schedule."""
    from app.services.scheduler.runner import SchedulerService

    enabled = payload.get("enabled")
    if enabled is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "enabled is required")
    schedule = await SchedulerService(db).set_enabled(schedule_id, bool(enabled))
    return {"id": str(schedule.id), "enabled": schedule.enabled}


@router.post("/scheduler/schedules/{schedule_id}/run-now")
async def admin_run_schedule_now(
    schedule_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """Make the schedule due on the next tick."""
    from app.services.scheduler.runner import SchedulerService

    schedule = await SchedulerService(db).run_now(schedule_id)
    return {"id": str(schedule.id), "next_run_at": schedule.next_run_at.isoformat()}
