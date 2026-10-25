"""Company profiles: reviewed firmographics for the normalized org entity.

Job feeds never carry company facts. `company_profiles` is the reviewed
1:1 layer over `organizations`: what postings prove (hiring volume,
roles, locations) is derived at read time and never stored here; what a
human entered lives here, every financial claim carrying its own source
and as-of date. Unknown stays NULL — never guessed.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.models.enums import CompanyProfileSource, CompanyType


def _in_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join("'" + value + "'" for value in values)
    return f"{column} IN ({quoted})"


_COMPANY_TYPE_CHECK = _in_check("company_type", tuple(kind.value for kind in CompanyType))
_SOURCE_CHECK = _in_check("source", tuple(source.value for source in CompanyProfileSource))


class CompanyProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reviewed company facts for one normalized organization (1:1).

    ``financials`` is a list of typed claims (see
    ``app.schemas.company.FinancialClaim``): kind, amount, currency,
    as-of date and source per claim.
    """

    __tablename__ = "company_profiles"
    __table_args__ = (
        CheckConstraint(_COMPANY_TYPE_CHECK, name="company_type_allowed"),
        CheckConstraint(_SOURCE_CHECK, name="source_allowed"),
        UniqueConstraint("organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    industry_tags: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    employees_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employees_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hq_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    hq_country: Mapped[str | None] = mapped_column(String(60), nullable=True)
    founded_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    financials: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    links: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CompanyProfileSource.MANUAL.value
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
