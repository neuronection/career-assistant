import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.models.enums import BackgroundJobType, DocumentKind
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


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile,
    kind: DocumentKind = DocumentKind.UNIVERSITY_CATALOG,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a university-catalog file; parsing runs as a background job."""
    if (file.content_type or "") not in ALLOWED_MIME:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF or text files"
        )
    content = await file.read()
    service = DocumentService(db)
    try:
        document = await service.create_upload(
            user.id, file.filename or "upload", file.content_type or "", content
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
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
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[DocumentOut]:
    """The caller's uploaded documents."""
    rows = await DocumentService(db).list_documents(user.id)
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
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"applied": created}
