"""Market-statistics wire shapes (plan 170 slice 1).

Typed response models for the postings and companies stats endpoints —
one model per endpoint shape. Counts carry an explicit status basis
(``open`` = the explore feed's ``mapped``/``new`` set, ``all`` = every
status) and every windowed metric compares against the immediately
preceding window of equal length via :class:`DeltaOut`.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

StatusBasis = Literal["open", "all"]
TrendDir = Literal["up", "down", "flat"]
BucketName = Literal["hour", "day", "week", "month"]
FreshnessState = Literal["ok", "stale", "paused", "never"]
InsightKind = Literal["volume", "share", "skill_lead"]


class DeltaOut(BaseModel):
    """One count with its equal-length predecessor for delta math.

    ``delta_pct`` is null when the previous window counted zero — the UI
    renders "new", never a divide-by-zero.
    """

    count: int = Field(ge=0)
    prev: int = Field(ge=0)
    delta_pct: float | None = None
    trend: TrendDir


class SparkPointOut(BaseModel):
    bucket: str
    count: int = Field(ge=0)


class FreshnessSourceOut(BaseModel):
    """One source's ingestion freshness — named when not ``ok``."""

    source_key: str
    status: FreshnessState
    last_success: datetime | None = None


class FreshnessOut(BaseModel):
    as_of: datetime
    stale_sources: list[FreshnessSourceOut] = Field(default_factory=list)


class CoverageOut(BaseModel):
    """Data-coverage honesty chips over the window population (shares)."""

    salary: float = Field(ge=0, le=1)
    location: float = Field(ge=0, le=1)
    org_linked: float = Field(ge=0, le=1)
    skill_tagged: float = Field(ge=0, le=1)


class InsightOut(BaseModel):
    """One deterministic anomaly card (trailing-baseline rule, H2).

    ``text_key`` is rendered client-side; the server never writes free
    text here.
    """

    kind: InsightKind
    subject: str
    delta_pct: float | None = None
    baseline: float | None = None
    text_key: str


class PostingStatsSummary(BaseModel):
    """The pulse (stats rail + page hero): fixed-window counts on one
    basis, each with its delta, plus the 14-day sparkline and source
    freshness. ``open_total`` is the open set by definition (§A)."""

    as_of: datetime
    status_basis: StatusBasis
    new_24h: DeltaOut
    new_7d: DeltaOut
    new_30d: DeltaOut
    open_total: int = Field(ge=0)
    sparkline: list[SparkPointOut] = Field(default_factory=list)
    freshness: FreshnessOut


class PostingStatsOverview(BaseModel):
    """Page narrative payload: in-range KPIs, the status mix, coverage
    chips and the deterministic insights strip."""

    as_of: datetime
    window: str
    status_basis: StatusBasis
    start: datetime | None = None
    end: datetime
    new_in_range: DeltaOut
    open_total: int = Field(ge=0)
    status_mix: dict[str, int] = Field(default_factory=dict)
    coverage: CoverageOut
    insights: list[InsightOut] = Field(default_factory=list)


class TimeseriesPointOut(BaseModel):
    bucket: str
    count: int = Field(ge=0)
    prev: int = Field(ge=0)
    ingestion: int = Field(ge=0)
    series: dict[str, int] = Field(default_factory=dict)


class PostingStatsTimeseries(BaseModel):
    """Volume-over-time buckets (zero-filled), the equal-length previous
    period ghost, ingestion-vs-market counts and the optional split
    series."""

    as_of: datetime
    window: str
    status_basis: StatusBasis
    start: datetime | None = None
    end: datetime
    bucket: BucketName
    split: str | None = None
    points: list[TimeseriesPointOut] = Field(default_factory=list)


class SkillStatOut(BaseModel):
    key: str
    label: str
    count: int = Field(ge=0)
    share: float = Field(ge=0, le=1)
    delta_pct: float | None = None
    trend: TrendDir


class SkillCategoryOut(BaseModel):
    key: str
    count: int = Field(ge=0)
    share: float = Field(ge=0, le=1)


class SkillLevelOut(BaseModel):
    level: int = Field(ge=1, le=10)
    count: int = Field(ge=0)


class PostingStatsSkills(BaseModel):
    """Skills demand: top asked, rising/cooling trends, category mix,
    level histogram and priority mix over the window."""

    as_of: datetime
    window: str
    status_basis: StatusBasis
    start: datetime | None = None
    end: datetime
    top: list[SkillStatOut] = Field(default_factory=list)
    rising: list[SkillStatOut] = Field(default_factory=list)
    falling: list[SkillStatOut] = Field(default_factory=list)
    categories: list[SkillCategoryOut] = Field(default_factory=list)
    levels: list[SkillLevelOut] = Field(default_factory=list)
    avg_level: float | None = None
    priority: dict[str, int] = Field(default_factory=dict)
    avg_skills_per_posting: float = Field(ge=0, default=0.0)


class BreakdownRowOut(BaseModel):
    key: str
    count: int = Field(ge=0)
    share: float = Field(ge=0, le=1)
    prev: int = Field(ge=0)
    delta_pct: float | None = None
    trend: TrendDir


class PostingStatsBreakdown(BaseModel):
    """One dimension of market structure — grouped counts with share and
    delta, top-N with an ``other`` rollup where the vocabulary is open."""

    as_of: datetime
    window: str
    status_basis: StatusBasis
    start: datetime | None = None
    end: datetime
    dimension: str
    total: int = Field(ge=0)
    rows: list[BreakdownRowOut] = Field(default_factory=list)


class SalaryBucketOut(BaseModel):
    floor: float
    ceiling: float
    count: int = Field(ge=0)


class SalarySeniorityOut(BaseModel):
    seniority: str
    count: int = Field(ge=0)
    median: float | None = None


class SalaryCurrencyOut(BaseModel):
    """Per-currency salary statistics on the annualized normalized basis
    (no FX conversion). Bands are suppressed below the disclosure
    floor."""

    currency: str
    disclosed: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    thin_sample: bool
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    histogram: list[SalaryBucketOut] = Field(default_factory=list)
    by_seniority: list[SalarySeniorityOut] = Field(default_factory=list)
    period_basis: dict[str, int] = Field(default_factory=dict)


class PostingStatsSalary(BaseModel):
    as_of: datetime
    window: str
    status_basis: StatusBasis
    start: datetime | None = None
    end: datetime
    primary_currency: str | None = None
    currencies: list[SalaryCurrencyOut] = Field(default_factory=list)


class CompanyStatsSummary(BaseModel):
    as_of: datetime
    window: str
    status_basis: StatusBasis
    start: datetime | None = None
    end: datetime
    companies_hiring: int = Field(ge=0)
    new_companies: DeltaOut


class CompanyHiringOut(BaseModel):
    key: str
    name: str
    open_postings: int = Field(ge=0)
    new_in_range: DeltaOut


class IndustryMixOut(BaseModel):
    key: str
    count: int = Field(ge=0)
    share: float = Field(ge=0, le=1)


class OpeningsBucketOut(BaseModel):
    bucket: str
    count: int = Field(ge=0)


class CompanyStatsOverview(BaseModel):
    as_of: datetime
    window: str
    status_basis: StatusBasis
    start: datetime | None = None
    end: datetime
    top_hiring: list[CompanyHiringOut] = Field(default_factory=list)
    industry_mix: list[IndustryMixOut] = Field(default_factory=list)
    openings_histogram: list[OpeningsBucketOut] = Field(default_factory=list)
