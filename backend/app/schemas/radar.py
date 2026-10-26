"""Job radar wire schemas (plan 129 phase 4a).

The radar is the profile's saved job-search configuration. Validation
mirrors the explore vocabulary it maps onto; everything is optional —
an empty radar is a disabled radar.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import RadarCadence

_SENIORITY_BAND = Literal["intern", "junior", "mid", "senior", "lead", "principal"]
SeniorityBand = _SENIORITY_BAND
_ONSITE = Literal["onsite", "hybrid", "remote"]


class RadarLocation(BaseModel):
    """One preferred location. `remote: true` rows map to the remote
    work-mode filter; city/country rows map to the location filters."""

    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=60)
    remote: bool = False

    @model_validator(mode="after")
    def _some_location(self) -> "RadarLocation":
        if not (self.city or self.country or self.remote):
            raise ValueError("a location row needs a city, a country or remote=true")
        return self


class RadarIn(BaseModel):
    """Upsert payload: replace-all semantics, omit = clear."""

    keywords: list[str] = Field(default_factory=list, max_length=24)
    locations: list[RadarLocation] = Field(default_factory=list, max_length=12)
    seniority: list[SeniorityBand] = Field(default_factory=list, max_length=8)
    onsite_policy: _ONSITE | None = None
    salary_min_annual: Decimal | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    source_keys: list[str] = Field(default_factory=list, max_length=24)
    cadence: RadarCadence = RadarCadence.OFF
    enabled: bool = False

    @model_validator(mode="after")
    def _sane(self) -> "RadarIn":
        for tag in self.keywords + self.seniority + self.source_keys:
            if not tag.strip() or len(tag) > 80:
                raise ValueError("radar list entries must be 1-80 characters")
        if self.salary_min_annual is not None and not self.salary_currency:
            raise ValueError("a salary floor needs its currency")
        return self


class RadarOut(BaseModel):
    """The saved radar exactly as the write path stored it."""

    keywords: list[str] = Field(default_factory=list)
    locations: list[RadarLocation] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    onsite_policy: _ONSITE | None = None
    salary_min_annual: Decimal | None = None
    salary_currency: str | None = None
    source_keys: list[str] = Field(default_factory=list)
    cadence: RadarCadence = RadarCadence.OFF
    enabled: bool = False
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
