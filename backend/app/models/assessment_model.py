import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin


class AssessmentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One assessment execution walked through the phase pipeline (Phase 23)."""

    __tablename__ = "assessment_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="full")
    # Set when a run executes a plan-37 template; built-ins run template-less.
    # UUID today — plan 37 adds the table + real FK.
    template_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    phase_order: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    context: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="in_progress", index=True
    )
    current_phase: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    progress: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)

    questions: Mapped[list["AssessmentQuestion"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    answers: Mapped[list["AssessmentAnswer"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AssessmentQuestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A question instance; run_id NULL marks a bank item (Phase 23)."""

    __tablename__ = "assessment_questions"

    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    phase: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # Every question ships one line of guidance.
    help: Mapped[str] = mapped_column(Text, nullable=False, default="")
    options: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    time_split: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
    # Career stages this question targets (Phase 25); empty = every stage.
    audience_stages: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="bank")
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="active", index=True
    )
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    run: Mapped[Optional[AssessmentRun]] = relationship(back_populates="questions")
    answers: Mapped[list["AssessmentAnswer"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class AssessmentAnswer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The user's raw answer + computed deltas for one question."""

    __tablename__ = "assessment_answers"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "question_id", name="uq_assessment_answers_run_question"
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_questions.id", ondelete="CASCADE"), nullable=False
    )
    answer: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    derived: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)

    run: Mapped[AssessmentRun] = relationship(back_populates="answers")
    question: Mapped[AssessmentQuestion] = relationship(back_populates="answers")
