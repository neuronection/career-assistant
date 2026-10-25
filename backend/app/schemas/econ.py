"""Typed payloads for the economic-context surface (plan 127 §3.1)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import CoverageLevel, GeoRegionKind


class RegionRef(BaseModel):
    """A canonical region as the resolver returns it."""

    id: UUID
    kind: GeoRegionKind
    code: str
    country: str
    label: str


class RegionResolution(BaseModel):
    """Outcome of resolving a profile country/city pair against the gazetteer.

    ``ambiguous`` carries the candidates for the caller to choose from (the
    choice is written back as an alias); ``unresolved`` means the gazetteer
    has nothing — never a guess.
    """

    status: Literal["resolved", "ambiguous", "unresolved"]
    region: RegionRef | None = None
    candidates: list[RegionRef] = Field(default_factory=list)
    source: Literal["code", "label", "alias"] | None = None


class CoverageSummary(BaseModel):
    """What a scope can honestly show: the best level any active series reaches.

    ``level is None`` means no data at all — the caller renders "no data",
    never a silent estimate. ``series_count`` counts every matching active
    series row, not only the winning level's.
    """

    level: CoverageLevel | None
    series_count: int
    providers: list[str] = Field(default_factory=list)
    vintages: list[str] = Field(default_factory=list)
    license_classes: list[str] = Field(default_factory=list)
