"""Contact and outreach API schemas (plan 213 W1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ContactSource = Literal["manual", "application_migration", "import"]
InteractionKind = Literal["intro", "follow_up", "thank_you", "referral", "informational", "other"]
InteractionChannel = Literal["email", "call", "meeting", "message", "other"]
DraftKind = Literal["intro", "follow_up", "thank_you", "referral", "informational"]


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    org: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=160)
    email: str = Field(default="", max_length=200)
    profile_url: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    source: ContactSource = "manual"

    @field_validator("profile_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        value = value.strip()
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("profile_url must use http(s)")
        return value


class ContactPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    org: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=200)
    profile_url: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("name", "org", "role", "email", "profile_url", "notes", "tags")
    @classmethod
    def _no_explicit_null(cls, value):
        if value is None:
            raise ValueError("field cannot be null; omit it to leave it unchanged")
        return value


class ContactOut(BaseModel):
    id: uuid.UUID
    name: str
    org: str
    role: str
    email: str
    profile_url: str
    notes: str
    tags: list
    last_contacted_at: datetime | None = None
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContactInteractionIn(BaseModel):
    application_id: uuid.UUID | None = None
    kind: InteractionKind = "other"
    at: datetime
    channel: InteractionChannel = "other"
    notes: str = Field(default="", max_length=5000)


class ContactInteractionOut(BaseModel):
    id: uuid.UUID
    contact_id: uuid.UUID
    application_id: uuid.UUID | None = None
    kind: str
    at: datetime
    channel: str
    notes: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ContactDetailOut(ContactOut):
    interactions: list[ContactInteractionOut] = Field(default_factory=list)


class OutreachDraftIn(BaseModel):
    kind: DraftKind
    application_id: uuid.UUID | None = None


class OutreachEvidence(BaseModel):
    source: Literal["contact", "application", "posting", "profile"]
    label: str = Field(min_length=1, max_length=200)
    quote: str = Field(default="", max_length=500)


class OutreachDraftOut(BaseModel):
    kind: DraftKind
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=6000)
    evidence_refs: list[OutreachEvidence] = Field(default_factory=list, max_length=12)
    model: str = ""
    generated_at: datetime
    draft_only: bool = True


class OutreachDraftAI(BaseModel):
    """The structured model output before the service adds provenance."""

    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=6000)
    evidence_refs: list[OutreachEvidence] = Field(default_factory=list, max_length=12)
