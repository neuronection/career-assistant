"""Profile photo: upload, unset, and the header image pipeline.

The photo lives as a `documents` row (kind=photo, max 2 MB, image mime);
`profiles.photo_document_id` is the typed FK (42.A — no JSONB refs). The
context engine embeds it as a self-contained data URI so the renderer
stays asset-free for print/PDF.
"""

import base64
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.document_model import Document
from app.models.enums import DocumentKind, DocumentStatus
from app.models.user_model import Profile
from app.services.cv_source_service import source_file_path
from app.services.deps import get_current_user

router = APIRouter(prefix="/me/photo", tags=["profile"])

PHOTO_MIME = {"image/png", "image/jpeg", "image/webp"}
PHOTO_MAX_BYTES = 2 * 1024 * 1024


async def _profile(db: AsyncSession, user_id: uuid.UUID) -> Profile:
    rows = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = rows.scalars().first()
    if profile is None:
        raise NotFoundError("Profile not found")
    return profile


@router.get("")
async def photo_state(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Whether the caller has a profile photo (and its document id)."""
    profile = await _profile(db, user.id)
    return {
        "photo_document_id": (
            str(profile.photo_document_id) if profile.photo_document_id else None
        )
    }


@router.put("", status_code=200)
async def upload_photo(
    file: UploadFile,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set (or replace) the caller's profile photo."""
    content = await file.read()
    if file.content_type not in PHOTO_MIME:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Photo must be PNG, JPEG or WebP"
        )
    if len(content) > PHOTO_MAX_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Photo must be 2 MB or smaller"
        )
    profile = await _profile(db, user.id)
    from app.services.document_service import DocumentService

    document = await DocumentService(db).create_upload(
        user.id, file.filename or "photo.png", file.content_type, content
    )
    document.kind = DocumentKind.PHOTO.value
    document.status = DocumentStatus.READY.value
    profile.photo_document_id = document.id
    db.add(profile)
    await db.commit()
    return {"document_id": str(document.id)}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_photo(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Unset the profile photo (the document row is kept for audit)."""
    profile = await _profile(db, user.id)
    profile.photo_document_id = None
    db.add(profile)
    await db.commit()


@router.get("/gallery")
async def list_photos(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Every photo the user uploaded (the gallery), default first."""
    profile = await _profile(db, user.id)
    rows = (
        (
            await db.execute(
                select(Document)
                .where(
                    Document.user_id == user.id,
                    Document.kind == DocumentKind.PHOTO.value,
                )
                .order_by(Document.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    photos = [
        {
            "document_id": str(document.id),
            "filename": document.filename,
            "created_at": document.created_at.isoformat(),
            "is_default": document.id == profile.photo_document_id,
        }
        for document in rows
    ]
    photos.sort(key=lambda item: not item["is_default"])
    return photos


@router.post("/gallery", status_code=201)
async def upload_gallery_photo(
    file: UploadFile,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a photo to the gallery without changing the profile default."""
    content = await file.read()
    if file.content_type not in PHOTO_MIME:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Photo must be PNG, JPEG or WebP"
        )
    if len(content) > PHOTO_MAX_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Photo must be 2 MB or smaller"
        )
    await _profile(db, user.id)
    from app.services.document_service import DocumentService

    document = await DocumentService(db).create_upload(
        user.id, file.filename or "photo.png", file.content_type, content
    )
    document.kind = DocumentKind.PHOTO.value
    document.status = DocumentStatus.READY.value
    db.add(document)
    await db.commit()
    return {
        "document_id": str(document.id),
        "filename": document.filename,
        "created_at": document.created_at.isoformat(),
        "is_default": False,
    }


@router.put("/gallery/{document_id}/default", status_code=200)
async def set_default_photo(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Make an already-uploaded photo the profile default."""
    rows = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == user.id,
            Document.kind == DocumentKind.PHOTO.value,
        )
    )
    if rows.scalars().first() is None:
        raise NotFoundError("Photo not found")
    profile = await _profile(db, user.id)
    profile.photo_document_id = document_id
    db.add(profile)
    await db.commit()
    return {"photo_document_id": str(document_id)}


@router.delete("/gallery/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gallery_photo(
    document_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete one gallery photo; profile/CV references SET NULL."""
    rows = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == user.id,
            Document.kind == DocumentKind.PHOTO.value,
        )
    )
    document = rows.scalars().first()
    if document is None:
        raise NotFoundError("Photo not found")
    from app.services.cv_source_service import source_file_path

    path = source_file_path(document)
    await db.delete(document)
    await db.commit()
    if path.exists():
        path.unlink()


def photo_data_uri(document: Document) -> str:
    """Self-contained data URI for the renderer (asset-free HTML)."""
    path = source_file_path(document)
    if not path.exists():
        return ""
    raw = path.read_bytes()
    if len(raw) > PHOTO_MAX_BYTES:
        return ""
    return f"data:{document.mime};base64,{base64.b64encode(raw).decode()}"
