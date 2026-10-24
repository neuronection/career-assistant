"""I18n API schemas: locale choice, translation batches and label overlays."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import LabelEntityKind, LabelField, LabelSource, LabelStatus


class LocaleIn(BaseModel):
    """A personal or instance-wide locale choice (BCP-47 short form)."""

    locale: str = Field(min_length=2, max_length=8)


class LocaleOut(BaseModel):
    """The caller's resolved locale plus the supported registry."""

    locale: str
    supported: list[str]
    source: str


class TranslationItem(BaseModel):
    """One translated catalog entry (source key preserved verbatim)."""

    key: str
    value: str


class TranslationBatch(BaseModel):
    """Structured output of one TRANSLATE gateway call for UI catalogs."""

    translations: list[TranslationItem]


class TranslateKeysIn(BaseModel):
    """Maintainer batch: source strings to translate into one locale."""

    locale: str = Field(min_length=2, max_length=8)
    entries: dict[str, str] = Field(min_length=1)


class OverlayItem(BaseModel):
    """One drafted catalog-label override."""

    entity_kind: LabelEntityKind
    entity_id: uuid.UUID
    field: LabelField
    value: str = Field(min_length=1, max_length=4000)


class OverlayDraftBatch(BaseModel):
    """Structured output of one TRANSLATE gateway call for label overlays."""

    items: list[OverlayItem]


class OverlayDraftIn(BaseModel):
    """Administrator request to draft overlays for taxonomy rows."""

    locale: str = Field(min_length=2, max_length=8)
    entity_kinds: list[LabelEntityKind] = Field(
        default_factory=lambda: [LabelEntityKind.JOB, LabelEntityKind.SKILL, LabelEntityKind.FAMILY]
    )
    limit: int = Field(default=20, ge=1, le=200)


class OverlayOut(BaseModel):
    """One overlay row with its base label, for the review queue."""

    id: uuid.UUID
    entity_kind: LabelEntityKind
    entity_id: uuid.UUID
    locale: str
    field: LabelField
    value: str
    base_value: str
    source: LabelSource
    status: LabelStatus
    created_at: datetime
    updated_at: datetime


class OverlayPatchIn(BaseModel):
    """Reviewer edit of a drafted value (approval stays a separate action)."""

    value: str = Field(min_length=1, max_length=4000)


class LocaleStateOut(BaseModel):
    """Instance default UI locale plus the supported registry."""

    locale: str
    supported: list[str]


class OverlayDraftResultOut(BaseModel):
    """AI-draft batch result: drafted overlay counts per entity kind."""

    locale: str
    drafted: dict[str, int]


class OverlayStatusOut(BaseModel):
    """Minimal overlay mutation result (id + resulting status)."""

    id: uuid.UUID
    status: LabelStatus
    value: str | None = None
