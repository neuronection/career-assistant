"""Saved screening-answer schemas (plan 212 S1.5)."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

AnswerText = Annotated[str, Field(min_length=1, max_length=4000)]
QuestionKey = Annotated[str, Field(min_length=1, max_length=80)]


class SavedAnswerIn(BaseModel):
    question_key: QuestionKey
    question_text: str = Field(default="", max_length=300)
    answer_text: AnswerText
    evidence_refs: list[dict] = Field(default_factory=list, max_length=8)


class SavedAnswerPatch(BaseModel):
    question_text: str | None = Field(default=None, max_length=300)
    answer_text: str | None = Field(default=None, min_length=1, max_length=4000)
    evidence_refs: list[dict] | None = Field(default=None, max_length=8)

    @field_validator("question_text", "answer_text", "evidence_refs", mode="before")
    @classmethod
    def _no_explicit_null(cls, value):
        if value is None:
            raise ValueError("field cannot be null; omit it to leave it unchanged")
        return value


class SavedAnswerOut(BaseModel):
    id: uuid.UUID
    question_key: str
    question_text: str
    answer_text: str
    evidence_refs: list = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
