"""CV record service: living documents + immutable versions.

`cv_documents` holds the autosaved editor state; every compiled snapshot
becomes an immutable `cv_versions` row (unique per version, canonical
content hash per). Restore/duplicate always copy-forward.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.cv_model import CvDocument, CvVersion
from app.models.enums import CvVersionCreator
from app.schemas.cv import CvContextSelection, CvDocumentCreate, CvDocumentUpdate
from app.services.engagement_service import canonical_hash


class CvService:
    """CRUD for the caller's CV records and their version snapshots."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_id: uuid.UUID, payload: CvDocumentCreate) -> CvDocument:
        """Create a CV record (no version yet — versions compile on save)."""
        if payload.source_document_id is not None:
            await self._require_owned_document(user_id, payload.source_document_id)
        if payload.template_id is not None:
            from app.services.cv_template_service import CvTemplateService

            await CvTemplateService(self.db).get_readable(payload.template_id, user_id)
        if payload.photo_document_id is not None:
            await self._require_owned_photo(user_id, payload.photo_document_id)
        cv = CvDocument(
            user_id=user_id,
            title=payload.title,
            kind=payload.kind.value,
            target_posting_id=payload.target_posting_id,
            template_id=payload.template_id,
            photo_document_id=payload.photo_document_id,
            language=payload.language,
            page_size=payload.page_size.value,
            max_pages=payload.max_pages,
            working_content={},
            context=payload.context.model_dump(mode="json"),
            source_document_id=payload.source_document_id,
        )
        self.db.add(cv)
        await self.db.commit()
        await self.db.refresh(cv)
        return cv

    async def list_cvs(self, user_id: uuid.UUID) -> list[CvDocument]:
        """The caller's CVs, most recently touched first."""
        rows = await self.db.execute(
            select(CvDocument)
            .where(CvDocument.user_id == user_id)
            .order_by(CvDocument.updated_at.desc())
        )
        return list(rows.scalars().all())

    async def get_owned(self, cv_id: uuid.UUID, user_id: uuid.UUID) -> CvDocument:
        """Fetch a CV belonging to the caller."""
        rows = await self.db.execute(
            select(CvDocument).where(
                CvDocument.id == cv_id, CvDocument.user_id == user_id
            )
        )
        cv = rows.scalars().first()
        if cv is None:
            raise NotFoundError("CV not found")
        return cv

    async def update(
        self, cv_id: uuid.UUID, user_id: uuid.UUID, payload: CvDocumentUpdate
    ) -> CvDocument:
        """Autosave working content / metadata (never versions)."""
        cv = await self.get_owned(cv_id, user_id)
        data = payload.model_dump(exclude_unset=True, mode="json")
        for field in ("title", "status", "language", "page_size", "max_pages"):
            if data.get(field) is not None:
                setattr(cv, field, data[field])
        if "target_posting_id" in data:
            cv.target_posting_id = data["target_posting_id"]
        if "template_id" in data:
            cv.template_id = data["template_id"]
        if "photo_document_id" in data:
            if data["photo_document_id"] is not None:
                await self._require_owned_photo(user_id, data["photo_document_id"])
            cv.photo_document_id = data["photo_document_id"]
        if data.get("working_content") is not None:
            cv.working_content = data["working_content"]
        if data.get("context") is not None:
            CvContextSelection.model_validate(data["context"])
            cv.context = data["context"]
        await self.db.commit()
        await self.db.refresh(cv)
        return cv

    async def delete(self, cv_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Delete the CV; versions cascade, nothing else is touched."""
        cv = await self.get_owned(cv_id, user_id)
        await self.db.delete(cv)
        await self.db.commit()

    async def latest_version(self, cv_id: uuid.UUID) -> int | None:
        """Highest version number for a CV (None when never saved)."""
        rows = await self.db.execute(
            select(func.max(CvVersion.version)).where(CvVersion.cv_document_id == cv_id)
        )
        return rows.scalar_one_or_none()

    async def create_version(
        self,
        cv_id: uuid.UUID,
        user_id: uuid.UUID,
        content: dict,
        created_by: CvVersionCreator,
        context_resolution: dict | None = None,
    ) -> CvVersion:
        """Append the next immutable version snapshot."""
        cv = await self.get_owned(cv_id, user_id)
        if not content:
            raise ValidationError("Cannot save an empty CV version")
        latest = await self.latest_version(cv.id)
        version = CvVersion(
            cv_document_id=cv.id,
            version=(latest or 0) + 1,
            content=content,
            context_resolution=context_resolution or {},
            content_hash=canonical_hash(content),
            created_by=created_by.value,
        )
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def list_versions(
        self, cv_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[CvVersion]:
        """All snapshots of a CV, newest first."""
        cv = await self.get_owned(cv_id, user_id)
        rows = await self.db.execute(
            select(CvVersion)
            .where(CvVersion.cv_document_id == cv.id)
            .order_by(CvVersion.version.desc())
        )
        return list(rows.scalars().all())

    async def _require_owned_photo(
        self, user_id: uuid.UUID, document_id: uuid.UUID
    ) -> None:
        from sqlalchemy import select

        from app.models.document_model import Document

        rows = await self.db.execute(
            select(Document.id).where(
                Document.id == document_id,
                Document.user_id == user_id,
                Document.kind == "photo",
            )
        )
        if rows.scalars().first() is None:
            raise NotFoundError("Photo not found")

    async def _require_owned_document(
        self, user_id: uuid.UUID, document_id: uuid.UUID
    ) -> None:
        from sqlalchemy import select

        from app.models.document_model import Document

        rows = await self.db.execute(
            select(Document.id).where(
                Document.id == document_id, Document.user_id == user_id
            )
        )
        if rows.scalars().first() is None:
            raise NotFoundError("Document not found")
