"""Interview practice schemas: the question plan, the per-turn
feedback/rubric payload and the API In/Out shapes.

Structured over plain text: the plan and the rubric are pydantic-
validated into JSONB; technical questions reference taxonomy skill keys
(`skill_key`) — the service resolves labels, never trusting model text.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

QuestionKind = Literal["technical", "behavioral", "research"]

MAX_PLAN_ITEMS = 12


class InterviewQuestion(BaseModel):
    """One plan item: what to ask, why, and what a good answer contains."""

    id: str = Field(min_length=1, max_length=40)
    kind: QuestionKind = "technical"
    # Taxonomy key when kind == "technical" (resolved, never model-invented).
    skill_key: str | None = None
    skill_label: str = Field(default="", max_length=120)
    # Calibration: the level this question probes (1-10), aimed at the
    # user's current level for the skill — not the posting requirement.
    target_level: int | None = Field(default=None, ge=1, le=10)
    question: str = Field(min_length=1, max_length=600)
    focus: str = Field(default="", max_length=400)


class InterviewPlan(BaseModel):
    """The generated question plan (draft on create; user-editable)."""

    items: list[InterviewQuestion] = Field(max_length=MAX_PLAN_ITEMS)
    rationale: str = Field(default="", max_length=2000)


class InterviewPlanPatch(BaseModel):
    """User edit of the plan before/while practicing (add/remove/reorder)."""

    items: list[InterviewQuestion] = Field(max_length=MAX_PLAN_ITEMS)


class InterviewSessionCreate(BaseModel):
    """Setup: a posting (ref or id) or a catalog archetype (job code)."""

    posting_ref: str | None = Field(default=None, max_length=64)
    job_code: str | None = Field(default=None, max_length=120)
    kind: Literal["technical", "behavioral", "mixed", "research"] = "mixed"
    story_ids: list[uuid.UUID] = Field(default_factory=list, max_length=3)

    @field_validator("story_ids")
    @classmethod
    def _unique_story_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("story_ids must be unique")
        return value


class RubricScores(BaseModel):
    """Light rubric per answer: structure/evidence/clarity."""

    structure: int = Field(ge=0, le=10)
    evidence: int = Field(ge=0, le=10)
    clarity: int = Field(ge=0, le=10)
    notes: str = Field(default="", max_length=600)


class TurnFeedback(BaseModel):
    """Per-answer feedback: what worked, one improvement, own evidence."""

    stars: list[str] = Field(default_factory=list, max_length=4)
    improvement: str = Field(default="", max_length=600)
    evidence_suggestions: list[str] = Field(default_factory=list, max_length=3)


class InterviewTurn(BaseModel):
    """One practice turn: coaching narrative + feedback structure.

    `answer` is the display text streamed to the chat UI (what worked,
    one improvement, evidence pointers — the same facts as `feedback`);
    the rubric and the next question are persisted server-side, and the
    next question itself is injected deterministically from the plan.
    `next_question_id` is null when the plan is exhausted (`done`).
    """

    answer: str = Field(min_length=1, max_length=4000)
    feedback: TurnFeedback
    rubric: RubricScores
    next_question_id: str | None = None
    done: bool = False


class DebriefResource(BaseModel):
    """A learning resource linked from a weak skill."""

    skill_key: str | None = None
    title: str = Field(min_length=1, max_length=300)
    provider: str = Field(default="", max_length=120)
    url: str = Field(default="", max_length=1000)
    kind: str = Field(default="", max_length=40)


class InterviewDebrief(BaseModel):
    """Session summary: rubric aggregates are computed deterministically;
    the LLM supplies the narrative and the gap reading."""

    summary: str = Field(min_length=1, max_length=2000)
    strengths: list[str] = Field(default_factory=list, max_length=5)
    gaps: list[str] = Field(default_factory=list, max_length=5)
    recommendations: list[str] = Field(default_factory=list, max_length=5)


class InterviewSessionOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    role_label: str
    posting_ref: str | None = None
    chat_session_id: uuid.UUID | None = None
    plan: list[dict]
    rubric_scores: list[dict]
    debrief: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InterviewStoryIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    competency_keys: list[str] = Field(default_factory=list, max_length=8)
    situation: str = Field(default="", max_length=2000)
    task: str = Field(default="", max_length=2000)
    action: str = Field(default="", max_length=2000)
    result: str = Field(default="", max_length=2000)
    experience_item_id: uuid.UUID | None = None
    evidence_refs: list[dict] = Field(default_factory=list, max_length=8)


class InterviewStoryPatch(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, min_length=1, max_length=200)
    competency_keys: list[str] | None = Field(default=None, max_length=8)
    situation: str | None = Field(default=None, max_length=2000)
    task: str | None = Field(default=None, max_length=2000)
    action: str | None = Field(default=None, max_length=2000)
    result: str | None = Field(default=None, max_length=2000)
    experience_item_id: uuid.UUID | None = None
    evidence_refs: list[dict] | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def _reject_null_text(self):
        for field in (
            "title",
            "competency_keys",
            "situation",
            "task",
            "action",
            "result",
            "evidence_refs",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class InterviewStoryOut(BaseModel):
    id: uuid.UUID
    title: str
    competency_keys: list
    situation: str
    task: str
    action: str
    result: str
    experience_item_id: uuid.UUID | None = None
    evidence_refs: list
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StorySuggestionOut(BaseModel):
    experience_item_id: uuid.UUID
    title: str
    org: str
    hint: str
