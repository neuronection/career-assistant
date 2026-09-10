"""Interview practice: posting-grounded mock interviews with
structured feedback, tracked per role.

The question `plan` is generated from the posting extract (must-have
skills at their levels, responsibilities with time-splits) or a catalog
archetype, edited by the user, then practiced in chat: the transcript
lives in `chat_sessions` (streaming + audit via), while rubric
scores accumulate here keyed by plan-item id. The debrief is the
aggregate — deterministic math over the rubric plus one structured LLM
summary, with links to learning resources for weak skills.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

MAX_PLAN_ITEMS = 12


class InterviewSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One mock-interview engagement: plan → chat practice → debrief."""

    __tablename__ = "interview_sessions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('technical', 'behavioral', 'mixed', 'research')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'abandoned')",
            name="status_allowed",
        ),
        Index("ix_interview_sessions_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Null = generic practice for a catalog archetype (family_key path).
    posting_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("job_postings.id", ondelete="SET NULL"), nullable=True
    )
    # The practice transcript lives in chat; set on start.
    chat_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="mixed")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    # Display label: posting title or the archetype job title.
    role_label: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # The user-approved question plan: list of InterviewQuestion dicts.
    plan: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    # Per-question rubric rows keyed by plan-item id (list of dicts).
    rubric_scores: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    # Debrief aggregate: summary, strengths, gaps,
    # recommendations, resources — written on completion.
    debrief: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)

    posting = relationship("JobPosting", viewonly=True)
    chat_session = relationship("ChatSession", viewonly=True)

    @property
    def answered_ids(self) -> set[str]:
        """Plan-item ids that already carry a rubric row."""
        return {
            str(row.get("question_id"))
            for row in (self.rubric_scores or [])
            if row.get("question_id")
        }

    @property
    def next_question(self) -> Optional[dict]:
        """First plan item without a rubric row (plan order is the flow)."""
        answered = self.answered_ids
        for item in self.plan or []:
            if str(item.get("id")) not in answered:
                return item
        return None

    @property
    def finished_at(self) -> Optional[datetime]:
        return self.updated_at
