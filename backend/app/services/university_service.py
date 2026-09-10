from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.models.university_model import (
    Department,
    DepartmentAdmission,
    JobDepartmentLink,
    University,
)
from app.schemas.university import DepartmentCreate, UniversityCreate


class UniversityService:
    """Universities, departments, admission baselines and job links."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_universities(
        self, q: str | None = None, country: str | None = None
    ) -> list[University]:
        """List universities with optional search."""
        query = (
            select(University)
            .options(selectinload(University.departments))
            .order_by(University.name)
        )
        if q:
            query = query.where(University.name.ilike(f"%{q.strip()}%"))
        if country:
            query = query.where(University.country == country)
        return list((await self.db.execute(query)).scalars().all())

    async def get_university(self, university_id: UUID) -> University:
        """Fetch a university with departments + admissions, or 404."""
        rows = await self.db.execute(
            select(University)
            .options(
                selectinload(University.departments).selectinload(
                    Department.admissions
                ),
                selectinload(University.departments).selectinload(Department.job_links),
            )
            .where(University.id == university_id)
        )
        university = rows.scalars().first()
        if university is None:
            raise NotFoundError("University not found")
        return university

    async def create_university(
        self, data: UniversityCreate, user_id: UUID | None = None
    ) -> University:
        """Create a university (manual entry)."""
        university = University(
            name=data.name,
            country=data.country,
            city=data.city,
            university_type=data.university_type.value,
            website=data.website,
            notes=data.notes,
            source="manual",
            created_by=user_id,
        )
        self.db.add(university)
        await self.db.commit()
        await self.db.refresh(university)
        return university

    async def add_department(
        self, university_id: UUID, data: DepartmentCreate
    ) -> Department:
        """Add a department to a university."""
        await self.get_university(university_id)
        department = Department(
            university_id=university_id,
            name=data.name,
            field_key=data.field_key,
            degree=data.degree.value,
            duration_years=data.duration_years,
            language=data.language,
            application_deadline=data.application_deadline,
            description=data.description,
        )
        self.db.add(department)
        await self.db.commit()
        await self.db.refresh(department)
        return department

    async def get_department(self, department_id: UUID) -> Department:
        """Fetch a department or 404."""
        rows = await self.db.execute(
            select(Department)
            .options(selectinload(Department.admissions))
            .where(Department.id == department_id)
        )
        department = rows.scalars().first()
        if department is None:
            raise NotFoundError("Department not found")
        return department

    async def add_admission(
        self,
        department_id: UUID,
        *,
        year: int,
        baseline_score=None,
        top_score=None,
        quota=None,
        units: str = "points",
        source: str = "manual",
        confidence: float = 1.0,
        document_id=None,
    ) -> DepartmentAdmission:
        """Upsert one admission baseline row per (department, year, source)."""
        await self.get_department(department_id)
        rows = await self.db.execute(
            select(DepartmentAdmission).where(
                DepartmentAdmission.department_id == department_id,
                DepartmentAdmission.year == year,
                DepartmentAdmission.source == source,
            )
        )
        admission = rows.scalars().first()
        if admission is None:
            admission = DepartmentAdmission(
                department_id=department_id, year=year, source=source
            )
            self.db.add(admission)
        admission.baseline_score = baseline_score
        admission.top_score = top_score
        admission.quota = quota
        admission.units = units
        admission.confidence = confidence
        admission.document_id = document_id
        await self.db.commit()
        await self.db.refresh(admission)
        return admission

    async def link_job_department(
        self,
        job_id: UUID,
        department_id: UUID,
        *,
        relevance: float = 5.0,
        rationale: str = "",
        required_subjects: Optional[list] = None,
        typical_position: str = "",
        employment_rate_pct: Optional[float] = None,
        source: str = "manual",
    ) -> JobDepartmentLink:
        """Create or update the rich job↔department relation."""
        link = JobDepartmentLink(
            job_id=job_id,
            department_id=department_id,
            relevance=relevance,
            rationale=rationale,
            required_subjects=required_subjects or [],
            typical_position=typical_position,
            employment_rate_pct=employment_rate_pct,
            source=source,
        )
        existing = await self.db.execute(
            select(JobDepartmentLink).where(
                JobDepartmentLink.job_id == job_id,
                JobDepartmentLink.department_id == department_id,
            )
        )
        found = existing.scalars().first()
        if found:
            link = found
            link.relevance = relevance
            link.rationale = rationale
            link.required_subjects = required_subjects or []
            link.typical_position = typical_position
            link.employment_rate_pct = employment_rate_pct
            link.source = source
        else:
            self.db.add(link)
        await self.db.commit()
        await self.db.refresh(link)
        return link

    async def job_links(self, job_id: UUID) -> list[JobDepartmentLink]:
        """All department links for a job, with department + university."""
        rows = await self.db.execute(
            select(JobDepartmentLink)
            .options(
                selectinload(JobDepartmentLink.department).selectinload(
                    Department.university
                ),
                selectinload(JobDepartmentLink.department).selectinload(
                    Department.admissions
                ),
            )
            .where(JobDepartmentLink.job_id == job_id)
        )
        return list(rows.scalars().all())
