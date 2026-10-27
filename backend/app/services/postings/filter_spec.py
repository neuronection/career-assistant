"""The postings filter system (plan 136): one uniform spec shape for
every axis, a pure query builder, and preset persistence.

The spec is versioned (``v``) so stored presets survive shape evolution.
Every axis uses three-valued semantics: an ``include`` list (match any,
OR), an ``exclude`` list (match none), both empty = don't care. Numeric
bounds are independently open (either side may be absent).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

SPEC_VERSION = 1


class IncludeExclude(BaseModel):
    """Three-valued: include = match any (OR), exclude = match none,
    both empty = don't care."""

    include: list[str] = Field(default_factory=list, max_length=50)
    exclude: list[str] = Field(default_factory=list, max_length=50)


class SkillFilter(BaseModel):
    include: list[str] = Field(default_factory=list, max_length=50)
    exclude: list[str] = Field(default_factory=list, max_length=50)
    min_level: int | None = Field(default=None, ge=1, le=10)


class SalaryFilter(BaseModel):
    min: float | None = Field(default=None, ge=0)
    max: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class CompanyFilter(BaseModel):
    include: list[str] = Field(default_factory=list, max_length=50)
    exclude: list[str] = Field(default_factory=list, max_length=50)
    industries_include: list[str] = Field(default_factory=list, max_length=30)
    industries_exclude: list[str] = Field(default_factory=list, max_length=30)


class LocationFilter(BaseModel):
    include: list[str] = Field(default_factory=list, max_length=30)
    exclude: list[str] = Field(default_factory=list, max_length=30)
    remote_only: bool | None = None


class PostedWithinFilter(BaseModel):
    days: int | None = Field(default=None, ge=1, le=365)


class MatchScoreFilter(BaseModel):
    min: float | None = Field(default=None, ge=0, le=10)
    max: float | None = Field(default=None, ge=0, le=10)


class SavedFilter(BaseModel):
    value: bool | None = None


class DescriptionFilter(BaseModel):
    text: str | None = Field(default=None, max_length=300)


class PostingFilterSpec(BaseModel):
    """The full filter spec — every axis, one shape."""

    v: int = SPEC_VERSION
    skills: SkillFilter = Field(default_factory=SkillFilter)
    salary: SalaryFilter = Field(default_factory=SalaryFilter)
    location: LocationFilter = Field(default_factory=LocationFilter)
    companies: CompanyFilter = Field(default_factory=CompanyFilter)
    seniority: IncludeExclude = Field(default_factory=IncludeExclude)
    employment: IncludeExclude = Field(default_factory=IncludeExclude)
    work_mode: IncludeExclude = Field(default_factory=IncludeExclude)
    languages: IncludeExclude = Field(default_factory=IncludeExclude)
    education: IncludeExclude = Field(default_factory=IncludeExclude)
    posted_within: PostedWithinFilter = Field(default_factory=PostedWithinFilter)
    match_score: MatchScoreFilter = Field(default_factory=MatchScoreFilter)
    source: IncludeExclude = Field(default_factory=IncludeExclude)
    saved: SavedFilter = Field(default_factory=SavedFilter)
    description: DescriptionFilter = Field(default_factory=DescriptionFilter)
    sort: str = Field(default="fresh", pattern="^(fit|fresh)$")

    def is_empty(self) -> bool:
        """No axis active — the feed is unfiltered."""
        return not any(
            [
                self.skills.include or self.skills.exclude or self.skills.min_level,
                self.salary.min is not None or self.salary.max is not None or self.salary.currency,
                self.location.include
                or self.location.exclude
                or self.location.remote_only is not None,
                any(
                    getattr(self.companies, f)()
                    for f in ("include", "exclude", "industries_include", "industries_exclude")
                    if callable(getattr(self.companies, f))
                )
                or self.companies.include
                or self.companies.exclude
                or self.companies.industries_include
                or self.companies.industries_exclude,
                self.seniority.include or self.seniority.exclude,
                self.employment.include or self.employment.exclude,
                self.work_mode.include or self.work_mode.exclude,
                self.languages.include or self.languages.exclude,
                self.education.include or self.education.exclude,
                self.posted_within.days is not None,
                self.match_score.min is not None or self.match_score.max is not None,
                self.source.include or self.source.exclude,
                self.saved.value is not None,
                self.description.text,
            ]
        )


class PostingFilterPresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=20)
    filters: dict[str, Any] = Field(default_factory=dict)
