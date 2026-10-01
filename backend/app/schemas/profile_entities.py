# ruff: noqa: E501 -- long immutable template/message strings; reflow when touched
"""CV-data profile entity schemas: education, certifications,
achievements, plus the deterministic cv-readiness report."""

import re
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import EducationLevel
from app.services.rich_text import validate_rich_text

_Date = date  # annotation alias: the `date` field name shadows the type in pydantic's resolution namespace

GRADE_BANDS = ("low", "below_average", "average", "good", "excellent", "unknown")


class EducationItemIn(BaseModel):
    institution: str = Field(min_length=1, max_length=200)
    org_name: str = Field(default="", max_length=200)
    program: str = Field(default="", max_length=200)
    level: EducationLevel = EducationLevel.HIGH_SCHOOL
    start: date | None = None
    end: date | None = None
    in_progress: bool = False
    grade_band: Literal["low", "below_average", "average", "good", "excellent", "unknown"] | None = None
    focus_subjects: list[str] = Field(default_factory=list, max_length=12)
    description: str = Field(default="", max_length=4000)
    status: Literal["draft", "active"] = "active"
    university_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None

    @field_validator("description")
    @classmethod
    def _rich(cls, value: str) -> str:
        return validate_rich_text(value, 4000)


class EducationItemPatch(BaseModel):
    institution: str | None = Field(default=None, min_length=1, max_length=200)
    org_name: str | None = Field(default=None, max_length=200)
    program: str | None = Field(default=None, max_length=200)
    level: EducationLevel | None = None
    start: date | None = None
    end: date | None = None
    in_progress: bool | None = None
    grade_band: Literal["low", "below_average", "average", "good", "excellent", "unknown"] | None = None
    focus_subjects: list[str] | None = Field(default=None, max_length=12)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["draft", "active"] | None = None
    university_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None

    @field_validator("description")
    @classmethod
    def _rich(cls, value: str | None) -> str | None:
        return None if value is None else validate_rich_text(value, 4000)


class EducationItemOut(BaseModel):
    id: uuid.UUID
    institution: str
    org_name: str
    program: str
    level: str
    start: date | None = None
    end: date | None = None
    in_progress: bool
    grade_band: str | None = None
    focus_subjects: list
    description: str
    source: str
    status: str
    university_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CertificationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    issuer: str = Field(default="", max_length=200)
    issued: date | None = None
    expires: date | None = None
    credential_id: str = Field(default="", max_length=120)
    link: str = Field(default="", max_length=500)
    language_code: str | None = Field(default=None, max_length=10)
    status: Literal["draft", "active"] = "active"

    @field_validator("language_code")
    @classmethod
    def _language_code_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not re.fullmatch(r"[a-z]{2,3}", cleaned):
            raise ValueError("language_code must be a 2-3 letter language code")
        return cleaned


class CertificationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    issuer: str | None = Field(default=None, max_length=200)
    issued: date | None = None
    expires: date | None = None
    credential_id: str | None = Field(default=None, max_length=120)
    link: str | None = Field(default=None, max_length=500)
    language_code: str | None = Field(default=None, max_length=10)
    status: Literal["draft", "active"] | None = None

    @field_validator("language_code")
    @classmethod
    def _language_code_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not re.fullmatch(r"[a-z]{2,3}", cleaned):
            raise ValueError("language_code must be a 2-3 letter language code")
        return cleaned


class CertificationOut(BaseModel):
    id: uuid.UUID
    name: str
    issuer: str
    issued: date | None = None
    expires: date | None = None
    credential_id: str
    link: str
    language_code: str | None = None
    source: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProfileAchievementIn(BaseModel):
    kind: Literal["award", "honor", "publication", "extracurricular"] = "award"
    title: str = Field(min_length=1, max_length=200)
    issuer: str = Field(default="", max_length=200)
    date: "_Date | None" = None
    detail: str = Field(default="", max_length=4000)
    link: str = Field(default="", max_length=500)
    status: Literal["draft", "active"] = "active"


class ProfileAchievementPatch(BaseModel):
    kind: Literal["award", "honor", "publication", "extracurricular"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    issuer: str | None = Field(default=None, max_length=200)
    date: "_Date | None" = None
    detail: str | None = Field(default=None, max_length=4000)
    link: str | None = Field(default=None, max_length=500)
    status: Literal["draft", "active"] | None = None


class ProfileAchievementOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    issuer: str
    date: "_Date | None" = None
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
