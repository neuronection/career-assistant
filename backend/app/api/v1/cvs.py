import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.cv_model import CvVersion
from app.models.enums import BackgroundJobType, CvVersionCreator
from app.schemas.cv import (
    CvCompileOut,
    CvContextItemRef,
    CvContextSelection,
    CvContextSourceOut,
    CvContextSourcesOut,
    CvContextStatusOut,
    CvDocumentCreate,
    CvDocumentOut,
    CvDocumentUpdate,
    CvPreviewOut,
    CvResolutionOut,
    CvVersionOut,
)
from app.schemas.cv_export import CvExportRequest
from app.schemas.cv_generate import (
    CvGenerateAccepted,
    CvGenerateRequest,
    CvGenerateResultOut,
    CvGenerateStatusOut,
)
from app.schemas.cv_suggest import CvActionRequest, CvSuggestionOut
from app.schemas.cover_letter import (
    CoverLetterActionRequest,
    CoverLetterBriefOut,
    CoverLetterCreate,
    CoverLetterSuggestionOut,
)
from app.services.cv_builder_service import CvBuilderService
from app.services.cv_context_service import CV_CONTEXT_SOURCES, resolve_sources
from app.services.cv_export_service import CvExportService
from app.services.cv_generate_service import enqueue_generation
from app.services.cv_pdf_service import PDFEngineUnavailable
from app.services.cv_service import CvService
from app.services.cover_letter_service import CoverLetterService
from app.services.cv_suggestion_service import CvSuggestionService
from app.services.deps import get_current_user

router = APIRouter(prefix="/cv", tags=["cv"])


async def _out(db: AsyncSession, service: CvService, cv) -> CvDocumentOut:
    """Serialise a CV with its latest version number (None if never saved)."""
    payload = CvDocumentOut.model_validate(cv)
    payload.latest_version = await service.latest_version(cv.id)
    return payload


async def _owned_builder(cv_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession):
    service = CvService(db)
    cv = await service.get_owned(cv_id, user_id)
    return cv, CvBuilderService(db)


@router.get("/context/sources", response_model=CvContextSourcesOut)
async def context_sources(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CvContextSourcesOut:
    """The context-source registry with the caller's resolvable items."""
    resolved = await resolve_sources(db, user.id)
    return CvContextSourcesOut(
        sources=[
            CvContextSourceOut(
                key=key,
                label=definition.label,
                description=definition.description,
                items=[
                    {
                        "item_id": item.item_id,
                        "label": item.label,
                        "detail": item.detail,
                    }
                    for item in resolved.get(key) or []
                ],
            )
            for key, definition in CV_CONTEXT_SOURCES.items()
        ]
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_cv(
    payload: CvDocumentCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvDocumentOut:
    """Create a CV record."""
    try:
        cv = await CvService(db).create(user.id, payload)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _out(db, CvService(db), cv)


@router.post("/cover-letters", status_code=status.HTTP_201_CREATED)
async def create_cover_letter(
    payload: CoverLetterCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvDocumentOut:
    """Create a cover-letter document targeted at one posting.

    Seeds the letter blocks (sender header + letter body); versions,
    preview and exports ride the same CV Studio paths as resumes.
    """
    try:
        cv = await CoverLetterService(db).create(user.id, payload)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _out(db, CvService(db), cv)


@router.get("/cover-letters/brief", response_model=CoverLetterBriefOut)
async def cover_letter_brief(
    posting_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CoverLetterBriefOut:
    """Deterministic grounding pack: extract must-haves, fit, coverage, goal."""
    return await CoverLetterService(db).brief(user.id, posting_id)


@router.post(
    "/generate",
    response_model=CvGenerateAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_cv(
    payload: CvGenerateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvGenerateAccepted:
    """One-shot CV generation.

    The modal is the review gate: target, voice, format, section toggles,
    context selection and emphasis notes are all captured by the request —
    nothing runs until it is submitted. Answers 503 when no AI provider is
    configured (never a fake draft) and 422 on a sparse profile.
    """
    try:
        job = await enqueue_generation(db, user.id, payload)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return CvGenerateAccepted(job_id=job.id, status=job.status)


@router.get("/generate/{job_id}", response_model=CvGenerateStatusOut)
async def generate_status(
    job_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvGenerateStatusOut:
    """Progress + result of one generate run (the queue's job record)."""
    rows = await db.execute(
        select(BackgroundJob).where(
            BackgroundJob.id == job_id, BackgroundJob.user_id == user.id
        )
    )
    job = rows.scalars().first()
    if job is None or job.job_type != BackgroundJobType.CV_GENERATE.value:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generate job not found")
    result = job.result or None
    return CvGenerateStatusOut(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        error=job.error,
        result=CvGenerateResultOut.model_validate(result) if result else None,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


@router.get("", response_model=list[CvDocumentOut])
async def list_cvs(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[CvDocumentOut]:
    """The caller's CVs, most recently touched first."""
    service = CvService(db)
    return [await _out(db, service, cv) for cv in await service.list_cvs(user.id)]


@router.get("/{cv_id}", response_model=CvDocumentOut)
async def get_cv(
    cv_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvDocumentOut:
    """One CV (working content + metadata)."""
    service = CvService(db)
    return await _out(db, service, await service.get_owned(cv_id, user.id))


@router.patch("/{cv_id}", response_model=CvDocumentOut)
async def update_cv(
    cv_id: uuid.UUID,
    payload: CvDocumentUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvDocumentOut:
    """Autosave working content / metadata (versions stay immutable)."""
    try:
        cv = await CvService(db).update(cv_id, user.id, payload)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _out(db, CvService(db), cv)


@router.delete("/{cv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cv(
    cv_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a CV; its versions cascade."""
    await CvService(db).delete(cv_id, user.id)


@router.get("/{cv_id}/versions", response_model=list[CvVersionOut])
async def list_versions(
    cv_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CvVersionOut]:
    """Immutable snapshots, newest first."""
    versions = await CvService(db).list_versions(cv_id, user.id)
    return [CvVersionOut.model_validate(v) for v in versions]


@router.post("/{cv_id}/versions", response_model=CvVersionOut, status_code=201)
async def save_version(
    cv_id: uuid.UUID,
    payload: dict,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvVersionOut:
    """Append the next immutable version snapshot."""
    try:
        version = await CvService(db).create_version(
            cv_id, user.id, payload, CvVersionCreator.USER_SAVE
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CvVersionOut.model_validate(version)


@router.get("/{cv_id}/context", response_model=CvResolutionOut)
async def get_context(
    cv_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvResolutionOut:
    """Resolve the CV's selection: snapshot + per-item trace (no render)."""
    cv, builder = await _owned_builder(cv_id, user.id, db)
    resolution = await builder.resolution(cv)
    return CvResolutionOut(
        snapshot=resolution.snapshot,
        snapshot_index=resolution.snapshot_index,
        items=[
            CvContextItemRef(
                source_key=ref["source_key"],
                item_id=ref["item_id"],
                label=ref["label"],
                updated_at=ref["updated_at"],
            )
            for ref in resolution.item_refs()
        ],
        resolved_at=resolution.resolved_at,
    )


@router.get("/{cv_id}/context/status", response_model=CvContextStatusOut)
async def context_status(
    cv_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvContextStatusOut:
    """Staleness: current resolution vs the latest compiled baseline."""
    cv, builder = await _owned_builder(cv_id, user.id, db)
    report = await builder.context_status(cv)

    def _refs(values: list[dict]) -> list[CvContextItemRef]:
        return [CvContextItemRef(**value) for value in values]

    return CvContextStatusOut(
        has_baseline=report["has_baseline"],
        stale=report["stale"],
        changed=_refs(report["changed"]),
        added=_refs(report["added"]),
        removed=_refs(report["removed"]),
    )


@router.post("/{cv_id}/preview", response_model=CvPreviewOut)
async def preview_cv(
    cv_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvPreviewOut:
    """Render the current state (live preview; no version is created)."""
    cv, builder = await _owned_builder(cv_id, user.id, db)
    try:
        html, metrics, resolution, blocks = await builder.preview(cv)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CvPreviewOut(
        html=html,
        metrics=metrics,
        blocks=blocks,
        resolution=CvResolutionOut(
            snapshot=resolution.snapshot,
            snapshot_index=resolution.snapshot_index,
            items=[CvContextItemRef(**ref) for ref in resolution.item_refs()],
            resolved_at=resolution.resolved_at,
        ),
    )


@router.post("/{cv_id}/compile", response_model=CvCompileOut, status_code=201)
async def compile_cv(
    cv_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvCompileOut:
    """Compile the current state into the next immutable version."""
    cv, builder = await _owned_builder(cv_id, user.id, db)
    try:
        version, html, metrics = await builder.compile(cv)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CvCompileOut(
        version=CvVersionOut.model_validate(version), html=html, metrics=metrics
    )


@router.get("/{cv_id}/versions/{version}/preview", response_class=HTMLResponse)
async def preview_version(
    cv_id: uuid.UUID,
    version: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Render an immutable version snapshot exactly as it was compiled."""
    cv, builder = await _owned_builder(cv_id, user.id, db)
    rows = await db.execute(
        select(CvVersion).where(
            CvVersion.cv_document_id == cv.id, CvVersion.version == version
        )
    )
    target = rows.scalars().first()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    return HTMLResponse(await builder.render_version(cv, target))


@router.post("/{cv_id}/versions/{version}/restore", response_model=CvDocumentOut)
async def restore_version(
    cv_id: uuid.UUID,
    version: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvDocumentOut:
    """Copy-forward a version's blocks into the working state."""
    service = CvService(db)
    cv, builder = await _owned_builder(cv_id, user.id, db)
    rows = await db.execute(
        select(CvVersion).where(
            CvVersion.cv_document_id == cv.id, CvVersion.version == version
        )
    )
    target = rows.scalars().first()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    try:
        updated = await builder.restore(cv, target)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _out(db, service, updated)


@router.post("/{cv_id}/duplicate", response_model=CvDocumentOut, status_code=201)
async def duplicate_cv(
    cv_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvDocumentOut:
    """Copy the CV (metadata + working state); versions stay behind."""
    cv, builder = await _owned_builder(cv_id, user.id, db)
    copy = await builder.duplicate(cv)
    return await _out(db, CvService(db), copy)


@router.put("/{cv_id}/context", response_model=CvDocumentOut)
async def set_context(
    cv_id: uuid.UUID,
    payload: CvContextSelection,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvDocumentOut:
    """Replace the per-CV context selection (all-minus / none-plus / custom)."""
    service = CvService(db)
    updated = await service.update(cv_id, user.id, CvDocumentUpdate(context=payload))
    return await _out(db, service, updated)


@router.post("/{cv_id}/export")
async def export_cv(
    cv_id: uuid.UUID,
    payload: CvExportRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export the CV (compiles an auto-version, `created_by=export`).

    `pdf` renders a real PDF via server-side Chromium; when the engine is
    unavailable the endpoint answers 503 and the client falls back to the
    print-ready HTML view. The other formats download directly.
    """
    cv, _builder = await _owned_builder(cv_id, user.id, db)
    try:
        artifact = await CvExportService(db).export(cv, payload.format)
    except PDFEngineUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    disposition = "inline" if artifact.inline else "attachment"
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{artifact.filename}"'
        },
    )


@router.get("/{cv_id}/lint")
async def lint_cv(
    cv_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deterministic ATS lint over the current state (no version created)."""
    cv, _builder = await _owned_builder(cv_id, user.id, db)
    return await CvExportService(db).lint_report(cv)


@router.post("/{cv_id}/ai/cover_letter", response_model=CoverLetterSuggestionOut)
async def ai_cover_letter(
    cv_id: uuid.UUID,
    payload: CoverLetterActionRequest = Body(default_factory=CoverLetterActionRequest),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CoverLetterSuggestionOut:
    """Grounded cover-letter draft.

    Paragraphs carry a `verified` flag: false means the paragraph cites
    refs outside the CV's evidence allowlist (or cites nothing) — shown
    flagged in the reviewer, never auto-applied.
    """
    cv, _builder = await _owned_builder(cv_id, user.id, db)
    try:
        service = CvSuggestionService(db)
        return await CoverLetterService(db).draft(
            cv, payload, await service.template_prompts(cv)
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{cv_id}/ai/{action}", response_model=CvSuggestionOut)
async def ai_suggest(
    cv_id: uuid.UUID,
    action: str,
    payload: CvActionRequest = Body(default_factory=CvActionRequest),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvSuggestionOut:
    """Draft-then-approve writing proposals.

    `gaps` is deterministic (no AI call). Proposals carry a `verified`
    flag: false means the proposal cites refs outside the CV's evidence
    allowlist — shown flagged in the reviewer, never auto-applied.
    """
    cv, _builder = await _owned_builder(cv_id, user.id, db)
    try:
        return await CvSuggestionService(db).run(cv, action, payload)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
