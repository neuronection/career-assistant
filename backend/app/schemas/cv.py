"""CV Studio schemas: source-document extraction + CV records.

`CvSourceExtraction` is the validated shape stored on `documents.extraction`
for kind="cv" files. `OcrPagesResult` is the structured AI output for the
vision-OCR fallback. CV CRUD schemas cover the living
record; versioning snapshots land with's endpoints.
"""

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.enums import CvKind, CvPageSize, CvStatus


class CvSourcePage(BaseModel):
    """One source page: recovered text + where it came from."""

    index: int = Field(ge=0)
    text: str = ""
    source: Literal["text_layer", "ocr_vision", "ocr_tesseract"]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    image_path: Optional[str] = None


class CvSourceExtraction(BaseModel):
    """Validated `documents.extraction` payload for kind="cv" files."""

    pages: list[CvSourcePage] = Field(default_factory=list, max_length=50)
    full_text: str = ""
    has_text_layer: bool = False
    ocr_used: bool = False
    content_sha256: str = Field(default="", max_length=64)
    engine: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class OcrPage(BaseModel):
    """One OCR'd page as returned by the vision model."""

    index: int = Field(ge=0)
    text: str = Field(min_length=1)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class OcrPagesResult(BaseModel):
    """Structured output of the vision OCR task (one call per page batch)."""

    pages: list[OcrPage] = Field(max_length=10)


class CvContextRef(BaseModel):
    """A typed context item reference."""

    source_key: str = Field(min_length=1, max_length=60)
    item_id: str = Field(min_length=1, max_length=64)


class CvContextSelection(BaseModel):
    """Per-CV context selection: include-all-minus / none-plus / custom."""

    mode: Literal["all", "none", "custom"] = "all"
    include: list[CvContextRef] = Field(default_factory=list, max_length=500)
    exclude: list[CvContextRef] = Field(default_factory=list, max_length=500)


class CvDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: CvKind = CvKind.RESUME
    language: str = Field(default="en", min_length=2, max_length=10)
    page_size: CvPageSize = CvPageSize.A4
    max_pages: int = Field(default=1, ge=1, le=10)
    target_posting_id: Optional[uuid.UUID] = None
    template_id: Optional[uuid.UUID] = None
    photo_document_id: Optional[uuid.UUID] = None
    source_document_id: Optional[uuid.UUID] = None
    context: CvContextSelection = Field(default_factory=CvContextSelection)


class CvDocumentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[CvStatus] = None
    language: Optional[str] = Field(default=None, min_length=2, max_length=10)
    page_size: Optional[CvPageSize] = None
    max_pages: Optional[int] = Field(default=None, ge=1, le=10)
    target_posting_id: Optional[uuid.UUID] = None
    template_id: Optional[uuid.UUID] = None
    photo_document_id: Optional[uuid.UUID] = None
    working_content: Optional[dict] = None
    context: Optional[CvContextSelection] = None


class CvVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    content: dict
    context_resolution: dict
    content_hash: str
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CvDocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    kind: CvKind
    target_posting_id: Optional[uuid.UUID] = None
    template_id: Optional[uuid.UUID] = None
    photo_document_id: Optional[uuid.UUID] = None
    language: str
    page_size: CvPageSize
    max_pages: int
    status: CvStatus
    working_content: dict
    context: dict
    source_document_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    latest_version: Optional[int] = None

    model_config = {"from_attributes": True}

    @field_validator("context", mode="before")
    @classmethod
    def _validate_context(cls, value):  # noqa: ANN001 - raw JSONB
        if isinstance(value, dict) and value:
            CvContextSelection.model_validate(value)
        return value


class CvContextItemInfo(BaseModel):
    """One resolvable item as shown in the editor's source tree."""

    item_id: str
    label: str
    detail: str = ""


class CvContextSourceOut(BaseModel):
    key: str
    label: str
    description: str
    items: list[CvContextItemInfo] = Field(default_factory=list)


class CvContextSourcesOut(BaseModel):
    sources: list[CvContextSourceOut]


class CvContextItemRef(BaseModel):
    """Trace ref: one resolved item inside a compiled snapshot."""

    source_key: str
    item_id: str
    label: str = ""
    updated_at: Optional[str] = None


class CvResolutionOut(BaseModel):
    snapshot: dict
    snapshot_index: dict[str, list[str]]
    items: list[CvContextItemRef]
    resolved_at: datetime


class CvPreviewOut(BaseModel):
    html: str
    metrics: dict
    resolution: CvResolutionOut
    blocks: list[dict] = Field(default_factory=list)


class CvCompileOut(BaseModel):
    version: CvVersionOut
    html: str
    metrics: dict


class CvContextStatusOut(BaseModel):
    has_baseline: bool
    stale: bool
    changed: list[CvContextItemRef] = Field(default_factory=list)
    added: list[CvContextItemRef] = Field(default_factory=list)
    removed: list[CvContextItemRef] = Field(default_factory=list)
