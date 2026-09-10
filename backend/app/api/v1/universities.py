from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.schemas.university import (
    AdmissionCreate,
    AdmissionOut,
    DepartmentCreate,
    DepartmentOut,
    JobDepartmentLinkCreate,
    JobDepartmentLinkOut,
    UniversityCreate,
    UniversityOut,
)
from app.services.deps import get_current_user
from app.services.university_service import UniversityService

router = APIRouter(prefix="/universities", tags=["universities"])


@router.get("", response_model=list[UniversityOut])
async def list_universities(
    q: str | None = Query(default=None),
    country: str | None = Query(default=None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UniversityOut]:
    """Search universities."""
    rows = await UniversityService(db).list_universities(q=q, country=country)
    return [
        UniversityOut(
            id=u.id,
            name=u.name,
            country=u.country,
            city=u.city,
            university_type=u.university_type,
            website=u.website,
            notes=u.notes,
            source=u.source,
            department_count=len(u.departments) if u.departments else 0,
        )
        for u in rows
    ]


@router.post("", response_model=UniversityOut, status_code=201)
async def create_university(
    data: UniversityCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UniversityOut:
    """Manually add a university."""
    u = await UniversityService(db).create_university(data, user.id)
    return UniversityOut(
        id=u.id,
        name=u.name,
        country=u.country,
        city=u.city,
        university_type=u.university_type,
        website=u.website,
        notes=u.notes,
        source=u.source,
        department_count=0,
    )


@router.get("/{university_id}", response_model=dict)
async def get_university(
    university_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """University detail with departments, admissions and job links."""
    try:
        u = await UniversityService(db).get_university(university_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    departments = []
    for d in u.departments:
        departments.append(
            {
                "id": d.id,
                "university_id": d.university_id,
                "name": d.name,
                "field_key": d.field_key,
                "degree": d.degree,
                "duration_years": d.duration_years,
                "language": d.language,
                "application_deadline": d.application_deadline.isoformat()
                if d.application_deadline
                else None,
                "description": d.description,
                "admissions": [
                    {
                        "id": a.id,
                        "year": a.year,
                        "baseline_score": float(a.baseline_score)
                        if a.baseline_score is not None
                        else None,
                        "top_score": float(a.top_score)
                        if a.top_score is not None
                        else None,
                        "quota": a.quota,
                        "units": a.units,
                        "source": a.source,
                        "confidence": a.confidence,
                    }
                    for a in d.admissions
                ],
                "job_links": [
                    {
                        "id": link.id,
                        "job_id": link.job_id,
                        "department_id": link.department_id,
                        "relevance": link.relevance,
                        "rationale": link.rationale,
                        "required_subjects": link.required_subjects,
                        "typical_position": link.typical_position,
                        "salary_band": link.salary_band,
                        "employment_rate_pct": link.employment_rate_pct,
                        "source": link.source,
                    }
                    for link in d.job_links
                ],
            }
        )
    return {
        "id": u.id,
        "name": u.name,
        "country": u.country,
        "city": u.city,
        "university_type": u.university_type,
        "website": u.website,
        "notes": u.notes,
        "source": u.source,
        "departments": departments,
    }


@router.post(
    "/{university_id}/departments", response_model=DepartmentOut, status_code=201
)
async def add_department(
    university_id: UUID,
    data: DepartmentCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DepartmentOut:
    """Add a department to a university."""
    try:
        d = await UniversityService(db).add_department(university_id, data)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return DepartmentOut(
        id=d.id,
        university_id=d.university_id,
        name=d.name,
        field_key=d.field_key,
        degree=d.degree,
        duration_years=d.duration_years,
        language=d.language,
        application_deadline=d.application_deadline,
        description=d.description,
        admissions=[],
        job_links=[],
    )


@router.post(
    "/departments/{department_id}/admissions",
    response_model=AdmissionOut,
    status_code=201,
)
async def add_admission(
    department_id: UUID,
    data: AdmissionCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdmissionOut:
    """Add/overwrite an admission baseline row for one year."""
    try:
        a = await UniversityService(db).add_admission(
            department_id,
            year=data.year,
            baseline_score=data.baseline_score,
            top_score=data.top_score,
            quota=data.quota,
            units=data.units,
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return AdmissionOut(
        id=a.id,
        year=a.year,
        baseline_score=float(a.baseline_score)
        if a.baseline_score is not None
        else None,
        top_score=float(a.top_score) if a.top_score is not None else None,
        quota=a.quota,
        units=a.units,
        source=a.source,
        confidence=a.confidence,
    )


@router.post("/job-links", response_model=JobDepartmentLinkOut, status_code=201)
async def create_job_link(
    data: JobDepartmentLinkCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobDepartmentLinkOut:
    """Link a job to a department with pathway info."""
    link = await UniversityService(db).link_job_department(
        data.job_id,
        data.department_id,
        relevance=data.relevance,
        rationale=data.rationale,
        required_subjects=data.required_subjects,
        typical_position=data.typical_position,
        employment_rate_pct=data.employment_rate_pct,
    )
    return JobDepartmentLinkOut.model_validate(link)
