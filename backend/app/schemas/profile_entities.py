"""CV-data profile entity schemas: education, certifications,
achievements, plus the deterministic cv-readiness report."""

import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.enums import EducationLevel

GRADE_BANDS = ("low", "below_average", "average", "good", "excellent", "unknown")


class EducationItemIn(BaseModel):
    institution: str = Field(min_length=1, max_length=200)
    org_name: str = Field(default="", max_length=200)
    program: str = Field(default="", max_length=200)
    level: EducationLevel = EducationLevel.HIGH_SCHOOL
    start: Optional[date] = None
    end: Optional[date] = None
    in_progress: bool = False
    grade_band: Optional[
        Literal["low", "below_average", "average", "good", "excellent", "unknown"]
    ] = None
    focus_subjects: list[str] = Field(default_factory=list, max_length=12)
    description: str = Field(default="", max_length=4000)
    status: Literal["draft", "active"] = "active"
    university_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None


class EducationItemPatch(BaseModel):
    institution: Optional[str] = Field(default=None, min_length=1, max_length=200)
    org_name: Optional[str] = Field(default=None, max_length=200)
    program: Optional[str] = Field(default=None, max_length=200)
    level: Optional[EducationLevel] = None
    start: Optional[date] = None
    end: Optional[date] = None
    in_progress: Optional[bool] = None
    grade_band: Optional[
        Literal["low", "below_average", "average", "good", "excellent", "unknown"]
    ] = None
    focus_subjects: Optional[list[str]] = Field(default=None, max_length=12)
    description: Optional[str] = Field(default=None, max_length=4000)
    status: Optional[Literal["draft", "active"]] = None
    university_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None


class EducationItemOut(BaseModel):
    id: uuid.UUID
    institution: str
    org_name: str
    program: str
    level: str
    start: Optional[date] = None
    end: Optional[date] = None
    in_progress: bool
    grade_band: Optional[str] = None
    focus_subjects: list
    description: str
    source: str
    status: str
    university_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CertificationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    issuer: str = Field(default="", max_length=200)
    issued: Optional[date] = None
    expires: Optional[date] = None
    credential_id: str = Field(default="", max_length=120)
    link: str = Field(default="", max_length=500)
    status: Literal["draft", "active"] = "active"


class CertificationPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    issuer: Optional[str] = Field(default=None, max_length=200)
    issued: Optional[date] = None
    expires: Optional[date] = None
    credential_id: Optional[str] = Field(default=None, max_length=120)
    link: Optional[str] = Field(default=None, max_length=500)
    status: Optional[Literal["draft", "active"]] = None


class CertificationOut(BaseModel):
    id: uuid.UUID
    name: str
    issuer: str
    issued: Optional[date] = None
    expires: Optional[date] = None
    credential_id: str
    link: str
    source: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProfileAchievementIn(BaseModel):
    kind: Literal["award", "honor", "publication", "extracurricular"] = "award"
    title: str = Field(min_length=1, max_length=200)
    issuer: str = Field(default="", max_length=200)
    date: Optional[date] = None
    detail: str = Field(default="", max_length=4000)
    link: str = Field(default="", max_length=500)
    status: Literal["draft", "active"] = "active"


class ProfileAchievementPatch(BaseModel):
    kind: Optional[Literal["award", "honor", "publication", "extracurricular"]] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    issuer: Optional[str] = Field(default=None, max_length=200)
    date: Optional[date] = None
    detail: Optional[str] = Field(default=None, max_length=4000)
    link: Optional[str] = Field(default=None, max_length=500)
    status: Optional[Literal["draft", "active"]] = None


class ProfileAchievementOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    issuer: str
    date: Optional[date] = None
    detail: str
    link: str
    source: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReadinessSection(BaseModel):
    key: str
    label: str
    weight: int
    score: int
    complete: bool
    missing: list[str] = Field(default_factory=list)


class CvReadiness(BaseModel):
    overall: int = Field(ge=0, le=100)
    sections: list[ReadinessSection]
