import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
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
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True
    )

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
    family_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("job_families.id", ondelete="RESTRICT"), nullable=True
    )
    skill_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), nullable=True
    )
    education_level: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # Free display detail; the typed refs above are the identity.
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    optional: Mapped[bool] = mapped_column(nullable=False, default=False)

    path: Mapped[CareerPath] = relationship(back_populates="steps")
    family = relationship("JobFamily")
    skill = relationship("Skill")
