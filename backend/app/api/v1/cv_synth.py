"""CV synth endpoints: the synthesized-variant library (plan 62).

Registered before the `/cv` router so `/cv/synth` is not captured by
`/cv/{cv_id}`. Library CRUD on rows (manual creation, edits, status
transitions, delete) plus computed read state (staleness/orphan).
Generation runs ≤5 refs inline (CV_SYNTH, audited in `ai_generations`);
bulk requests and Regenerate-all ride the CV_SYNTH background job (62.2
contract: `202 {job_id}`)."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.cv import CvContextRef, CvContextSelection
from app.schemas.cv_synth import (
    CvSynthGenerateOut,
    CvSynthItemCreate,
    CvSynthItemGenerate,
    CvSynthItemOut,
    CvSynthItemUpdate,
    CvSynthPreviewIn,
    CvSynthPreviewItemOut,
    CvSynthPreviewOut,
)
from app.services.cv_context_service import resolve
from app.services.cv_synth_service import (
    SYNC_LIMIT,
    CvSynthService,
    _context_index,
)
from app.services.deps import get_current_user
from app.services.job_worker import enqueue

router = APIRouter(prefix="/cv/synth", tags=["cv"])


def _out(row, state: dict) -> CvSynthItemOut:
    return CvSynthItemOut(
        id=row.id,
        scope=row.scope,
        variant_key=row.variant_key,
        target_posting_id=row.target_posting_id,
        source_refs=[CvContextRef.model_validate(ref) for ref in row.source_refs],
        source_state=list(row.source_state),
        payload=row.payload,
        voice=row.voice,
        status=row.status,
        source=row.source,
        verified=row.verified,
        stale=state["stale"],
        orphaned=state["orphaned"],
        last_used_at=row.last_used_at.isoformat() if row.last_used_at else None,
        created_at=row.created_at.isoformat(),
    )


def _out_plain(row) -> CvSynthItemOut:
    return CvSynthItemOut(
        id=row.id,
        scope=row.scope,
        variant_key=row.variant_key,
        target_posting_id=row.target_posting_id,
        source_refs=[CvContextRef.model_validate(ref) for ref in row.source_refs],
        source_state=list(row.source_state),
        payload=row.payload,
        voice=row.voice,
        status=row.status,
        source=row.source,
        verified=row.verified,
        stale=False,
        orphaned=False,
        last_used_at=row.last_used_at.isoformat() if row.last_used_at else None,
        created_at=row.created_at.isoformat(),
    )


def _row_state(service: CvSynthService, row, context: dict) -> dict:
    return service._state_of(row, context)


@router.get("", response_model=list[CvSynthItemOut])
async def list_synth_items(
    cv_status: str | None = Query(default=None, alias="status"),
    source_key: str | None = Query(default=None),
    posting_id: uuid.UUID | None = Query(default=None),
    language: str | None = Query(default=None),
    stale: bool | None = Query(default=None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CvSynthItemOut]:
    """The caller's variant library, newest first."""
    rows = await CvSynthService(db).list_rows(
        user.id,
        status=cv_status,
        source_key=source_key,
        posting_id=posting_id,
        language=language,
        stale=stale,
    )
    return [
        _out(entry["row"], {"stale": entry["stale"], "orphaned": entry["orphaned"]})
        for entry in rows
    ]


@router.post("", response_model=CvSynthItemOut, status_code=status.HTTP_201_CREATED)
async def create_synth_item(
    payload: CvSynthItemCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvSynthItemOut:
    """Create a manual variant (user-written text, active immediately)."""
    service = CvSynthService(db)
    row = await service.create_manual(user.id, payload)
    return _out(row, {"stale": False, "orphaned": False})


@router.post("/preview", response_model=CvSynthPreviewOut)
async def preview_synth_matches(
    payload: CvSynthPreviewIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvSynthPreviewOut:
    """Which of the caller's active variants would apply (plan 69.3).

    Read-only, deterministic, no AI: the generate modal uses it for the
    "N matching variants will be used" hint. Precedence mirrors the
    resolver: active → language → posting-scoped beats generic."""
    service = CvSynthService(db)
    if payload.refs:
        ref_pairs = [(ref.source_key, ref.item_id) for ref in payload.refs]
    else:
        selection = payload.context or CvContextSelection()
        resolution = await resolve(db, user.id, selection)
        ref_pairs = [
            (key, item_id)
            for key, ids in resolution.snapshot_index.items()
            for item_id in ids
        ]
    matches = await service.match_for_user(
        user.id,
        payload.language,
        payload.target_posting_id,
        refs=ref_pairs,
        pins=(payload.context.synth_pins if payload.context else None),
    )
    if not matches:
        return CvSynthPreviewOut(items=[], total=0)
    context = await _context_index(db, user.id)
    items = []
    for (source_key, item_id), row in matches.items():
        state = service._state_of(row, context)
        items.append(
            CvSynthPreviewItemOut(
                source_key=source_key,
                item_id=item_id,
                synth_id=row.id,
                variant_key=row.variant_key,
                stale=state["stale"],
            )
        )
    items.sort(key=lambda item: (item.source_key, item.item_id))
    return CvSynthPreviewOut(items=items, total=len(items))


@router.post("/generate", response_model=CvSynthGenerateOut)
async def generate_synth_items(
    payload: CvSynthItemGenerate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvSynthGenerateOut:
    """Draft synthesized variants (≤5 refs inline; more → queued bulk)."""
    if len(payload.refs) > SYNC_LIMIT:
        job = await enqueue(
            db,
            "cv_synth",
            {"request": payload.model_dump(mode="json")},
            user_id=user.id,
        )
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=CvSynthGenerateOut(job_id=job.id, items=[]).model_dump(mode="json"),
        )
    service = CvSynthService(db)
    rows = await service.generate(user.id, payload)
    return CvSynthGenerateOut(items=[_out_plain(row) for row in rows])


@router.post(
    "/{item_id}/regenerate", response_model=CvSynthGenerateOut, status_code=201
)
async def regenerate_synth_item(
    item_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvSynthGenerateOut:
    """Re-run a stored AI variant's exact params → a fresh draft."""
    rows = await CvSynthService(db).regenerate(user.id, item_id)
    return CvSynthGenerateOut(items=[_out_plain(row) for row in rows])


@router.get("/{item_id}", response_model=CvSynthItemOut)
async def get_synth_item(
    item_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvSynthItemOut:
    """One variant with computed state."""
    service = CvSynthService(db)
    row = await service.get_owned(item_id, user.id)
    context = await _context_index(db, user.id)
    return _out(row, _row_state(service, row, context))


@router.patch("/{item_id}", response_model=CvSynthItemOut)
async def update_synth_item(
    item_id: uuid.UUID,
    payload: CvSynthItemUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvSynthItemOut:
    """Edit text / transition status (activate supersedes slot siblings)."""
    service = CvSynthService(db)
    row = await service.update(item_id, user.id, payload)
    context = await _context_index(db, user.id)
    return _out(row, _row_state(service, row, context))


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_synth_item(
    item_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete the variant (the source profile item is untouched)."""
    await CvSynthService(db).delete(item_id, user.id)
