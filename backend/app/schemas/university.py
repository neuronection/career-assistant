import re
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.models.enums import DegreeLevel, DocumentKind, DocumentStatus, UniversityType
from app.storage.object_storage import InvalidObjectKey, normalize_key

_OBJECT_KEY_ROOT = "tenants/"
_ABSOLUTE_PATH_TOKEN = re.compile(r"(?<![\w:/])(?:[A-Za-z]:[\\/]|/)[^\s'\"<>]+")
_RELATIVE_LOCAL_TOKEN = re.compile(
    r"\b(?:uploads|derived|career-cv-pages|career-legacy)/[^\s'\"<>]+"
)


def _is_object_key(value: object, owner_id: object | None = None) -> bool:
    """Only the owner's tenant keys are publishable.

    With an owner id (the API passes the row's `user_id` as validation
    context) the key must live under `tenants/<owner>/`; without one, the
    structural family prefix is the best the schema can enforce. A relative
    legacy path is never a key.
    """
    text = str(value or "")
    prefix = f"{_OBJECT_KEY_ROOT}{owner_id}/" if owner_id is not None else _OBJECT_KEY_ROOT
    if not text.startswith(prefix):
        return False
    try:
        normalize_key(text)
    except InvalidObjectKey:
        return False
    return True


def _scrub_local_paths(text: str) -> str:
    """Replace absolute path tokens and relative local trees with `<path>`.

    Every absolute token is treated as a path even when it sits outside a
    configured root (`/home/...`, `C:\\Users\\...`): an error string is
    never the place to expose where the server keeps files.
    """
    text = _ABSOLUTE_PATH_TOKEN.sub("<path>", text)
    return _RELATIVE_LOCAL_TOKEN.sub("<path>", text)


class AdmissionOut(BaseModel):
    id: UUID
    year: int
    baseline_score: float | None = None
    top_score: float | None = None
    quota: int | None = None
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
    application_deadline: date | None = None
    description: str = Field(default="", max_length=2000)


class DepartmentOut(BaseModel):
    id: UUID
    university_id: UUID
    name: str
    field_key: str
    degree: DegreeLevel
    duration_years: int
    language: str
    application_deadline: date | None = None
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


class UniversityDetailOut(UniversityOut):
    """University detail: the list row plus its departments."""

    departments: list[DepartmentOut] = Field(default_factory=list)


class JobDepartmentLinkOut(BaseModel):
    id: UUID
    job_id: UUID
    department_id: UUID
    relevance: float
    rationale: str
    required_subjects: list[str] = Field(default_factory=list)
    typical_position: str
    salary_band: dict | None = None
    employment_rate_pct: float | None = None
    source: str

    model_config = {"from_attributes": True}


class JobDepartmentLinkCreate(BaseModel):
    job_id: UUID
    department_id: UUID
    relevance: float = Field(default=5.0, ge=0, le=10)
    rationale: str = ""
    required_subjects: list[str] = Field(default_factory=list, max_length=12)
    typical_position: str = Field(default="", max_length=200)
    employment_rate_pct: float | None = Field(default=None, ge=0, le=100)


class AdmissionCreate(BaseModel):
    year: int = Field(ge=1990, le=2100)
    baseline_score: float | None = Field(default=None, ge=0, le=1000)
    top_score: float | None = Field(default=None, ge=0, le=1000)
    quota: int | None = Field(default=None, ge=0)
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
    extraction: dict | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_validator("extraction")
    @classmethod
    def _scrub_extraction_paths(cls, value: dict | None, info: ValidationInfo) -> dict | None:
        """Never expose a filesystem path from the stored extraction.

        Pre-contract CV rows carry `pages[].image_path` as an absolute
        `/…/uploads/derived/…` path or a relative `uploads/derived/…` one.
        The migration rewrites them to tenant object keys, but the response
        stays safe for any row that has not been migrated yet (or was
        written by an older process): only `tenants/…` keys pass.
        """
        if not isinstance(value, dict) or "pages" not in value:
            return value
        pages = value.get("pages")
        if not isinstance(pages, list):
            return value
        owner_id = (info.context or {}).get("user_id")
        scrubbed: list = []
        for page in pages:
            if (
                isinstance(page, dict)
                and page.get("image_path")
                and not _is_object_key(page["image_path"], owner_id)
            ):
                page = {**page, "image_path": None}
            scrubbed.append(page)
        return {**value, "pages": scrubbed}

    @field_validator("error")
    @classmethod
    def _scrub_error_paths(cls, value: str) -> str:
        """Redact local path fragments a processor/provider error may carry."""
        if not value:
            return value
        from app.core.config import settings

        text = value
        for root in {str(settings.upload_root), str(settings.data_dir)}:
            if root and root not in (".", "/"):
                text = text.replace(root.rstrip("/"), "<path>")
        return _scrub_local_paths(text)
