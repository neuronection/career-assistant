"""Career Autopilot: goals, runs, findings.

A goal is a natural-language career objective plus structured
constraints the agent must honor; runs are the audited executions
(`searches_executed` renders the "what I searched & why" timeline);
findings are the curated shortlist — `why` stays grounded in extract
evidence, ordering stays deterministic (posting_fit sort).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    TZDateTime,
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class AutopilotGoal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One AI-activated search goal owned by a user."""

    __tablename__ = "autopilot_goals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'paused')",
            name="status_allowed",
        ),
        Index("ix_autopilot_goals_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    goal_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured constraint set: must_terms, never_terms, family_keys,
    # remote, salary_min, seniority, exclude_seen/applied — the agent
    # reads it, feedback mutates it (shown back to the user explicitly).
    constraints: Mapped[dict] = mapped_column(
        StructuredJSON, nullable=False, default=dict
    )
    # trigger dict {"type":..., "params": {...}}; NULL = manual.
    cadence: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
    # Optional run-level cap layered over ai_budgets: {"max_tokens": N}.
    budget: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_run_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)


class AutopilotRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execution of a goal: plan → search → filter → curate → deliver.

    `searches_executed` is the transparency record (per-variant queries +
    filters + kept/dropped counts) the goal page renders as a timeline.
    """

    __tablename__ = "autopilot_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'budget_aborted', "
            "'cancelled', 'failed')",
            name="status_allowed",
        ),
        Index("ix_autopilot_runs_goal_started", "goal_id", "started_at"),
    )

    goal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("autopilot_goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    started_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)
    tokens_used: Mapped[int] = mapped_column(nullable=False, default=0)
    searches_executed: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    goal = relationship("AutopilotGoal", viewonly=True)


class AutopilotFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One curated shortlist entry: a posting, its fit score and the
    grounded `why`. Feedback buttons drive constraint learning."""

    __tablename__ = "autopilot_findings"
    __table_args__ = (
        UniqueConstraint("run_id", "posting_id", name="uq_autopilot_run_posting"),
        CheckConstraint(
            "feedback IS NULL OR feedback IN ('more_like_this', 'hide_like_this')",
            name="feedback_allowed",
        ),
        CheckConstraint(
            "score >= 0 AND score <= 10",
            name="score_range",
        ),
        Index("ix_autopilot_findings_run", "run_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("autopilot_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Evidence quotes + fit breakdown dims backing `why` (honesty guards).
    evidence: Mapped[dict] = mapped_column(StructuredJSON, nullable=False, default=dict)
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        TZDateTime(), nullable=True
    )
    feedback: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    posting = relationship("JobPosting", viewonly=True)  # noqa: F821
