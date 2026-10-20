import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CareerPath(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Curated or AI-drafted route to a destination job (Phase 21)."""

    __tablename__ = "career_paths"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="ai")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)

    job = relationship("Job")
    steps: Mapped[list["CareerPathStep"]] = relationship(
        back_populates="path",
        cascade="all, delete-orphan",
        order_by="CareerPathStep.position",
    )


class CareerPathStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One step of a career path; `kind` decides which typed ref is set."""

    __tablename__ = "career_path_steps"
    __table_args__ = (
        UniqueConstraint("path_id", "position", name="uq_career_path_steps_position"),
    )

    path_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("career_paths.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_families.id", ondelete="RESTRICT"), nullable=True
    )
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), nullable=True
    )
    education_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Free display detail; the typed refs above are the identity.
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    optional: Mapped[bool] = mapped_column(nullable=False, default=False)

    path: Mapped[CareerPath] = relationship(back_populates="steps")
    family = relationship("JobFamily")
    skill = relationship("Skill")
    parent_step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("career_path_steps.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Why this branch exists ("or: research track") — display only.
    edge_label: Mapped[str] = mapped_column(String(120), nullable=False, default="")


class UserPathFlag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's mark on a career path or one of its steps.

    `step_id` NULL flags the whole path. The uniqueness is two partial
    unique indexes instead of one UNIQUE(...) tuple: both PostgreSQL and
    SQLite treat NULLs as distinct inside a unique constraint, which
    would let a user flag the same path twice.
    """

    __tablename__ = "user_path_flags"
    __table_args__ = (
        CheckConstraint(
            "flag IN ('interested', 'dismissed', 'pinned')",
            name="flag_allowed",
        ),
        Index(
            "uq_user_path_flags_step",
            "user_id",
            "path_id",
            "step_id",
            unique=True,
            sqlite_where=text("step_id IS NOT NULL"),
            postgresql_where=text("step_id IS NOT NULL"),
        ),
        Index(
            "uq_user_path_flags_path",
            "user_id",
            "path_id",
            unique=True,
            sqlite_where=text("step_id IS NULL"),
            postgresql_where=text("step_id IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    path_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("career_paths.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("career_path_steps.id", ondelete="CASCADE"), nullable=True
    )
    flag: Mapped[str] = mapped_column(String(12), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
