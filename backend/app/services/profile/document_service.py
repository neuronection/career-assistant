import io
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import parse_universities
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError, sanitize_error_detail
from app.models.document_model import Document
from app.models.enums import DocumentStatus
from app.models.university_model import Department, University
from app.services.profile.document_storage import DocumentStorage, document_storage
from app.storage.object_storage import ObjectTooLarge, filename_extension

logger = logging.getLogger(__name__)


class DocumentService:
    """Upload → parse (AI) → review → apply pipeline for university PDFs."""

    def __init__(self, db: AsyncSession, storage: DocumentStorage | None = None):
        self.db = db
        self.storage = storage or document_storage()

    async def create_upload(
        self, user_id: uuid.UUID, filename: str, mime: str, content: bytes
    ) -> Document:
        """Persist the file through the store and create the document row."""
        max_bytes = settings.max_upload_mb * 1024 * 1024
        if len(content) > max_bytes:
            raise ValidationError(f"File exceeds {settings.max_upload_mb}MB limit")
        document = Document(
            user_id=user_id,
            filename=filename,
            mime=mime,
            size_bytes=len(content),
            status=DocumentStatus.UPLOADED.value,
        )
        self.db.add(document)
        await self.db.flush()
        try:
            document.object_key = await self.storage.aput_document(document, content)
        except ObjectTooLarge as exc:
            raise ValidationError(f"File exceeds {settings.max_upload_mb}MB limit") from exc
        await self.db.commit()
        await self.db.refresh(document)
        return document

    async def extract_text(self, document: Document) -> tuple[str, int]:
        """Extract raw text from the stored file (pdf via pypdf, else utf-8)."""
        raw = await self.storage.aread(document)
        if raw is None:
            raise NotFoundError("Stored file missing")
        suffix = filename_extension(document.filename)
        if document.mime == "application/pdf" or suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages), len(pages)
        return raw.decode("utf-8", errors="replace"), 1

    async def parse(self, document_id: uuid.UUID, user_id: uuid.UUID) -> Document:
        """Run the parser agent over the document text (background task)."""
        document = await self.get_owned(document_id, user_id)
        document.status = DocumentStatus.PARSING.value
        await self.db.commit()
        try:
            text, pages = await self.extract_text(document)
            document.page_count = pages
            if not text.strip():
                raise ValidationError("No extractable text in document")
            extraction = await parse_universities(self.db, user_id, text)
            document.extraction = extraction.model_dump(mode="json")
            document.status = DocumentStatus.PARSED.value
        except Exception as exc:
            logger.warning("document %s parse failed", document_id, exc_info=True)
            document.status = DocumentStatus.ERROR.value
            document.error = sanitize_error_detail(str(exc), limit=500)
        self.db.add(document)
        await self.db.commit()
        await self.db.refresh(document)
        return document

    async def get_owned(self, document_id: uuid.UUID, user_id: uuid.UUID) -> Document:
        """Fetch a document belonging to the caller."""
        rows = await self.db.execute(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        document = rows.scalars().first()
        if document is None:
            raise NotFoundError("Document not found")
        return document

    async def apply(self, document_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        """Materialise the extraction into universities/departments/admissions."""
        document = await self.get_owned(document_id, user_id)
        if not document.extraction or document.status not in (
            DocumentStatus.PARSED.value,
            DocumentStatus.APPLIED.value,
        ):
            raise ValidationError("Document has no parsed extraction to apply")
        created = {"universities": 0, "departments": 0, "admissions": 0}
        for uni_data in document.extraction.get("universities", []):
            university = await self._upsert_university(uni_data, user_id)
            created["universities"] += 1
            for dept_data in uni_data.get("departments", []):
                department = await self._upsert_department(university.id, dept_data)
                created["departments"] += 1
                for adm in dept_data.get("admissions", []):
                    await self._upsert_admission(department.id, adm, document.id)
                    created["admissions"] += 1
        document.status = DocumentStatus.APPLIED.value
        self.db.add(document)
        await self.db.commit()
        return created

    async def _upsert_university(self, uni_data: dict, user_id: uuid.UUID) -> University:
        """Find-or-create a university by (name, country)."""
        name = uni_data.get("name", "").strip()
        if not name:
            raise ValidationError("Extraction contains a university without a name")
        rows = await self.db.execute(
            select(University).where(
                University.name == name,
                University.country == uni_data.get("country", ""),
            )
        )
        university = rows.scalars().first()
        if university is None:
            university = University(
                name=name,
                country=uni_data.get("country", ""),
                city=uni_data.get("city", ""),
                university_type=uni_data.get("university_type", "public"),
                source="document",
                created_by=user_id,
            )
            self.db.add(university)
            await self.db.flush()
        return university

    async def _upsert_department(self, university_id: uuid.UUID, dept_data: dict) -> Department:
        """Find-or-create a department by (university, name)."""
        import datetime as dt

        name = dept_data.get("name", "").strip()
        if not name:
            raise ValidationError("Extraction contains a department without a name")
        rows = await self.db.execute(
            select(Department).where(
                Department.university_id == university_id, Department.name == name
            )
        )
        department = rows.scalars().first()
        deadline = None
        deadline_raw = dept_data.get("application_deadline")
        if deadline_raw:
            try:
                deadline = dt.date.fromisoformat(str(deadline_raw))
            except (TypeError, ValueError):
                deadline = None
        if department is None:
            department = Department(
                university_id=university_id,
                name=name,
                field_key=dept_data.get("field_key", ""),
                degree=dept_data.get("degree", "bachelor"),
                duration_years=int(dept_data.get("duration_years") or 4),
                language=dept_data.get("language", ""),
                application_deadline=deadline,
            )
            self.db.add(department)
            await self.db.flush()
        elif deadline and department.application_deadline is None:
            department.application_deadline = deadline
        return department

    async def _upsert_admission(
        self, department_id: uuid.UUID, adm: dict, document_id: uuid.UUID
    ) -> None:
        """Find-or-create an admission row per (department, year, source=document)."""
        from app.models.university_model import DepartmentAdmission

        year = int(adm.get("year") or 0)
        if not year:
            return
        rows = await self.db.execute(
            select(DepartmentAdmission).where(
                DepartmentAdmission.department_id == department_id,
                DepartmentAdmission.year == year,
                DepartmentAdmission.source == "document",
            )
        )
        admission = rows.scalars().first()
        if admission is None:
            admission = DepartmentAdmission(
                department_id=department_id, year=year, source="document"
            )
            self.db.add(admission)
        admission.baseline_score = adm.get("baseline_score")
        admission.top_score = adm.get("top_score")
        admission.quota = adm.get("quota")
        admission.units = adm.get("units", "points")
        admission.confidence = float(adm.get("confidence", 0.8))
        admission.document_id = document_id

    async def list_documents(self, user_id: uuid.UUID, kind: str | None = None) -> list[Document]:
        """All documents of a user, newest first (optionally by kind)."""
        stmt = select(Document).where(Document.user_id == user_id)
        if kind is not None:
            stmt = stmt.where(Document.kind == kind)
        stmt = stmt.order_by(Document.created_at.desc())
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())
