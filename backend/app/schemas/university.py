from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import DegreeLevel, DocumentKind, DocumentStatus, UniversityType


class AdmissionOut(BaseModel):
    id: UUID
    year: int
    baseline_score: Optional[float] = None
    top_score: Optional[float] = None
    quota: Optional[int] = None
    units: str
    source: str
    confidence: float

    model_config = {"from_attributes": True}


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    field_key: str = Field(default="", max_length=80)
    degree: DegreeLevel = DegreeLevel.BACHELOR
    duration_years: int = Field(default=4, ge=1, le=10)
    language: str = Field(default="", max_length=30)
    application_deadline: Optional[date] = None
    description: str = Field(default="", max_length=2000)


class DepartmentOut(BaseModel):
    id: UUID
    university_id: UUID
    name: str
    field_key: str
    degree: DegreeLevel
    duration_years: int
    language: str
    application_deadline: Optional[date] = None
    description: str
    admissions: list[AdmissionOut] = Field(default_factory=list)
    job_links: list["JobDepartmentLinkOut"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class UniversityCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    country: str = Field(default="", max_length=80)
    city: str = Field(default="", max_length=80)
    university_type: UniversityType = UniversityType.PUBLIC
    website: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=2000)


class UniversityOut(BaseModel):
    id: UUID
    name: str
    country: str
    city: str
    university_type: UniversityType
    website: str
    notes: str
    source: str
    department_count: int = 0

    model_config = {"from_attributes": True}


class JobDepartmentLinkOut(BaseModel):
    id: UUID
    job_id: UUID
    department_id: UUID
    relevance: float
    rationale: str
    required_subjects: list[str] = Field(default_factory=list)
    typical_position: str
    salary_band: Optional[dict] = None
    employment_rate_pct: Optional[float] = None
    source: str

    model_config = {"from_attributes": True}


class JobDepartmentLinkCreate(BaseModel):
    job_id: UUID
    department_id: UUID
    relevance: float = Field(default=5.0, ge=0, le=10)
    rationale: str = ""
    required_subjects: list[str] = Field(default_factory=list, max_length=12)
    typical_position: str = Field(default="", max_length=200)
    employment_rate_pct: Optional[float] = Field(default=None, ge=0, le=100)


class AdmissionCreate(BaseModel):
    year: int = Field(ge=1990, le=2100)
    baseline_score: Optional[float] = Field(default=None, ge=0, le=1000)
    top_score: Optional[float] = Field(default=None, ge=0, le=1000)
    quota: Optional[int] = Field(default=None, ge=0)
    units: str = Field(default="points", max_length=40)


class DocumentOut(BaseModel):
    id: UUID
    kind: DocumentKind
    filename: str
    mime: str
    size_bytes: int
    page_count: int
    status: DocumentStatus
    error: str
    extraction: Optional[dict] = None

    model_config = {"from_attributes": True}
