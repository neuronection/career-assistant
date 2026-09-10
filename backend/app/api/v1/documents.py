import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ValidationError
from app.models.enums import BackgroundJobType, DocumentKind, DocumentStatus
from app.schemas.university import DocumentOut
from app.services.deps import get_current_user
from app.services.document_service import DocumentService
from app.services.job_worker import enqueue

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
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported file type"
        )
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
        "document": DocumentOut.model_validate(document),
        "job_id": str(job.id),
    }


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    kind: Optional[str] = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentOut]:
    """The caller's uploaded documents (optionally filtered by kind)."""
    rows = await DocumentService(db).list_documents(user.id, kind=kind)
    return [DocumentOut.model_validate(d) for d in rows]


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    """Document status + extraction (for review)."""
    document = await DocumentService(db).get_owned(document_id, user.id)
    return DocumentOut.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document, its stored original, and derived page images."""
    import shutil

    from app.services.cv_source_service import derived_dir, source_file_path

    document = await DocumentService(db).get_owned(document_id, user.id)
    original = source_file_path(document)
    if original.exists():
        original.unlink()
    derived = derived_dir(document.id)
    if derived.exists():
        shutil.rmtree(derived, ignore_errors=True)
    await db.delete(document)
    await db.commit()


@router.get("/{document_id}/file")
async def download_document(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """The original upload, byte-exact."""
    from app.services.cv_source_service import source_file_path

    document = await DocumentService(db).get_owned(document_id, user.id)
    path = source_file_path(document)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stored file missing")
    return FileResponse(path, filename=document.filename, media_type=document.mime)


@router.get("/{document_id}/pages/{page_index}/image")
async def get_page_image(
    document_id: uuid.UUID,
    page_index: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """A derived page image (evidence thumbnails,/46)."""
    from app.services.cv_source_service import page_image_path

    document = await DocumentService(db).get_owned(document_id, user.id)
    if document.status not in (
        DocumentStatus.READY.value,
        DocumentStatus.PROCESSING.value,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No processed page images")
    path = page_image_path(document.id, page_index)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page image not found")
    return FileResponse(path, media_type="image/png")


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
