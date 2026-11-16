import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ValidationError
from app.models.enums import BackgroundJobType, DocumentKind, DocumentStatus
from app.schemas.university import DocumentOut
from app.services.deps import get_current_user
from app.services.job_worker import enqueue
from app.services.profile.document_service import DocumentService
from app.services.profile.document_storage import chain_first, document_storage
from app.storage.object_storage import (
    ObjectNotFound,
    StorageError,
    safe_download_filename,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_MIME = {
    "application/pdf",
    "text/plain",
    "application/octet-stream",
}

CV_ALLOWED_MIME = {
    "application/pdf",
    "text/plain",
    "image/png",
    "image/jpeg",
}


def _attachment(filename: str) -> dict[str, str]:
    """Download headers: attachment, no-store, nosniff (contract defaults)."""
    safe = safe_download_filename(filename)
    return {
        "Content-Disposition": f'attachment; filename="{safe}"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile,
    kind: DocumentKind = DocumentKind.UNIVERSITY_CATALOG,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a source file; parsing/extraction runs as a background job.

    kind="cv" preserves the original bytes byte-for-byte and
    enqueues the text-layer/OCR pipeline instead of the university parser.
    """
    allowed = CV_ALLOWED_MIME if kind == DocumentKind.CV else ALLOWED_MIME
    if (file.content_type or "") not in allowed:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported file type")
    content = await file.read()
    service = DocumentService(db)
    try:
        document = await service.create_upload(
            user.id, file.filename or "upload", file.content_type or "", content
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if kind == DocumentKind.CV:
        document.kind = DocumentKind.CV.value
        await db.commit()
        job = await enqueue(
            db,
            BackgroundJobType.CV_EXTRACT_TEXT.value,
            {"document_id": str(document.id)},
            user_id=user.id,
        )
    else:
        job = await enqueue(
            db,
            BackgroundJobType.DOCUMENT_PARSE.value,
            {"document_id": str(document.id)},
            user_id=user.id,
        )
    return {
        "document": DocumentOut.model_validate(document, context={"user_id": document.user_id}),
        "job_id": str(job.id),
    }


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    kind: str | None = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentOut]:
    """The caller's uploaded documents (optionally filtered by kind)."""
    rows = await DocumentService(db).list_documents(user.id, kind=kind)
    return [DocumentOut.model_validate(d, context={"user_id": d.user_id}) for d in rows]


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    """Document status + extraction (for review)."""
    document = await DocumentService(db).get_owned(document_id, user.id)
    return DocumentOut.model_validate(document, context={"user_id": document.user_id})


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document, its stored original, and derived page images."""
    document = await DocumentService(db).get_owned(document_id, user.id)
    try:
        await document_storage().adelete(document, db=db)
    except (StorageError, OSError):
        # The row goes either way; a provider/permissions failure leaves an
        # orphan the lifecycle rules / a later purge can collect (never a
        # 500 that keeps the row alive with no working file).
        logger.warning("document %s bytes could not be deleted", document.id, exc_info=True)
    await db.delete(document)
    await db.commit()


@router.get("/{document_id}/file")
async def download_document(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The original upload, byte-exact, streamed through the store."""
    document = await DocumentService(db).get_owned(document_id, user.id)
    storage = document_storage()
    stream = storage.astream(document)
    try:
        # Prefetch one chunk before the response starts so a TOCTOU delete
        # (row present, object gone) is a 404, not a mid-stream 500.
        first = await anext(stream)
    except ObjectNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stored file missing") from exc
    except StopAsyncIteration:
        # A present but zero-byte object is a valid empty download.
        return Response(
            content=b"",
            media_type=document.mime or "application/octet-stream",
            headers=_attachment(document.filename),
        )
    return StreamingResponse(
        chain_first(first, stream),
        media_type=document.mime or "application/octet-stream",
        headers=_attachment(document.filename),
    )


@router.get("/{document_id}/pages/{page_index}/image")
async def get_page_image(
    document_id: uuid.UUID,
    page_index: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """A derived page image (evidence thumbnails,/46)."""
    document = await DocumentService(db).get_owned(document_id, user.id)
    if document.status not in (
        DocumentStatus.READY.value,
        DocumentStatus.PROCESSING.value,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No processed page images")
    raw = await document_storage().aread_page(document, page_index)
    if raw is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page image not found")
    return Response(
        content=raw,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{document_id}/apply")
async def apply_document(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Materialise a parsed extraction into universities/departments/admissions."""
    service = DocumentService(db)
    try:
        created = await service.apply(document_id, user.id)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"applied": created}
