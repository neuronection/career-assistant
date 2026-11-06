"""Company profiles: reviewed facts + derived hiring stats (plan 129).

The wire layer for the company section. Reviewed facts come from
``CompanyProfileIn`` (admin writes); everything derived from postings is
computed at read time and carries no review state of its own. Unknown
stays None — the app's known/unknown clarity doctrine applies to
companies exactly like it does to postings.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.models.enums import CompanyType, FinancialClaimKind


class FinancialClaim(BaseModel):
    """One reviewed financial fact with its own source and as-of date."""

    kind: FinancialClaimKind
    amount: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    as_of: date | None = None
    source: str = Field(default="", max_length=300)

    model_config = {"from_attributes": True}


class CompanyLink(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=500)


class CompanyLinkIn(BaseModel):
    """Write-side link: the URL is scheme-checked (http/https only)."""

    label: str = Field(min_length=1, max_length=80)
    url: HttpUrl


class CompanyOut(BaseModel):
    """The list row: identity plus the coarse reviewed facts."""

    key: str
    name: str
    domain: str | None = None
    status: str = "active"
    company_type: CompanyType | None = None
    industry_tags: list[str] = Field(default_factory=list)
    employees_min: int | None = None
    employees_max: int | None = None
    hq_city: str | None = None
    hq_country: str | None = None
    founded_year: int | None = None
    open_postings: int = 0
    has_profile: bool = False

    model_config = {"from_attributes": True}


class CompanyFacets(BaseModel):
    """Per-value COMPANY counts over the filtered set's active postings —
    the filter options literally describe the hiring those companies are
    doing right now (plan 154)."""

    work_mode: dict[str, int] = Field(default_factory=dict)
    seniority: dict[str, int] = Field(default_factory=dict)
    employment: dict[str, int] = Field(default_factory=dict)
    industries: dict[str, int] = Field(default_factory=dict)
    locations: dict[str, int] = Field(default_factory=dict)


class CompaniesOut(BaseModel):
    """The companies list envelope: rows plus the optional facet
    distribution computed from the active postings behind them."""

    items: list[CompanyOut] = Field(default_factory=list)
    facets: CompanyFacets | None = None


class LocationCount(BaseModel):
    city: str | None = None
    country: str | None = None
    count: int = Field(ge=0)


class CompanyDerivedStats(BaseModel):
    """What the postings prove about this company — computed, never stored."""

    open_postings: int = Field(ge=0)
    by_seniority: dict[str, int] = Field(default_factory=dict)
    by_onsite_policy: dict[str, int] = Field(default_factory=dict)
    top_locations: list[LocationCount] = Field(default_factory=list)
    latest_posted_at: datetime | None = None


class CompanyDetailOut(CompanyOut):
    """The detail page: reviewed facts, financial claims, derived stats."""

    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    financials: list[FinancialClaim] = Field(default_factory=list)
    links: list[CompanyLink] = Field(default_factory=list)
    needs_review: bool = False
    derived: CompanyDerivedStats


class CompanyProfileIn(BaseModel):
    """Admin write: the reviewed facts. Omitted fields clear to unknown."""

    company_type: CompanyType | None = None
    industry_tags: list[str] = Field(default_factory=list, max_length=24)
    employees_min: int | None = Field(default=None, ge=0)
    employees_max: int | None = Field(default=None, ge=0)
    hq_city: str | None = Field(default=None, max_length=120)
    hq_country: str | None = Field(default=None, max_length=60)
    founded_year: int | None = Field(default=None, ge=1800, le=2100)
    description: str = Field(default="", max_length=4000)
    financials: list[FinancialClaim] = Field(default_factory=list, max_length=24)
    links: list[CompanyLinkIn] = Field(default_factory=list, max_length=12)
    needs_review: bool = False

    @model_validator(mode="after")
    def _employees_range_sane(self) -> "CompanyProfileIn":
        if (
            self.employees_min is not None
            and self.employees_max is not None
            and self.employees_min > self.employees_max
        ):
            raise ValueError("employees_min must not exceed employees_max")
        for tag in self.industry_tags:
            if not tag.strip() or len(tag) > 60:
                raise ValueError("industry tags must be 1-60 characters")
        return self
