import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Date,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.job_model import Job


class University(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A university entered manually or extracted from an uploaded document."""

    __tablename__ = "universities"
    __table_args__ = (
        UniqueConstraint("name", "country", name="uq_universities_name_country"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    country: Mapped[str] = mapped_column(
        String(80), nullable=False, default="", index=True
    )
    city: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    university_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="public"
    )
    website: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    departments: Mapped[list["Department"]] = relationship(
        back_populates="university", cascade="all, delete-orphan"
    )


class Department(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A department/school within a university."""

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("university_id", "name", name="uq_departments_uni_name"),
    )

    university_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("universities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    field_key: Mapped[str] = mapped_column(
        String(80), nullable=False, default="", index=True
    )
    degree: Mapped[str] = mapped_column(String(20), nullable=False, default="bachelor")
    duration_years: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    language: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    application_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    tuition: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    university: Mapped[University] = relationship(back_populates="departments")
    admissions: Mapped[list["DepartmentAdmission"]] = relationship(
        back_populates="department", cascade="all, delete-orphan"
    )
    job_links: Mapped[list["JobDepartmentLink"]] = relationship(
        back_populates="department", cascade="all, delete-orphan"
    )


class DepartmentAdmission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Historical admission baseline for one department and year."""

    __tablename__ = "department_admissions"
    __table_args__ = (
        UniqueConstraint(
            "department_id", "year", "source", name="uq_admissions_dept_year_source"
        ),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(nullable=False, index=True)
    baseline_score: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    top_score: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    quota: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    units: Mapped[str] = mapped_column(String(40), nullable=False, default="points")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    department: Mapped[Department] = relationship(back_populates="admissions")


class JobDepartmentLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rich relation between a job and a university department pathway."""

    __tablename__ = "job_department_links"
    __table_args__ = (
        UniqueConstraint("job_id", "department_id", name="uq_job_department"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relevance: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    required_subjects: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    typical_position: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    salary_band: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
    employment_rate_pct: Mapped[Optional[float]] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")

    job: Mapped["Job"] = relationship(back_populates="department_links")
    department: Mapped[Department] = relationship(back_populates="job_links")
