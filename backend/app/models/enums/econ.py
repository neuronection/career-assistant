"""Closed vocabularies for the economic-context wave (plan 127 §3.0).

Every member is mirrored by a DB CHECK landed in migration
``0054_econ_context``; the parity wall in
``tests/test_schema_contracts.py`` keeps the lists honest on both
dialects.
"""

from enum import StrEnum


class GeoRegionKind(StrEnum):
    COUNTRY = "country"
    NUTS1 = "nuts1"
    NUTS2 = "nuts2"
    METRO = "metro"
    ITL1 = "itl1"
    CITY = "city"


class EconPackKind(StrEnum):
    PACK = "pack"
    LIVE = "live"
    HARVESTED = "harvested"


class EconPackStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class CoverageLevel(StrEnum):
    FULL = "full"
    REGIONAL = "regional"
    COUNTRY = "country"
    MODELLED_ESTIMATE = "modelled_estimate"


class LicenseClass(StrEnum):
    PUBLIC_DOMAIN = "public_domain"
    OPEN_DATA = "open_data"
    ATTRIBUTION = "attribution"
    RESEARCH_ONLY = "research_only"


class ProvenanceTier(StrEnum):
    OFFICIAL = "official"
    EXTRACTED = "extracted"
    DERIVED = "derived"
    AI_ESTIMATED = "ai_estimated"


class CrosswalkMethod(StrEnum):
    OFFICIAL = "official"
    AI = "ai"
    MANUAL = "manual"


class ExposureMethod(StrEnum):
    ILO_GENAI = "ilo_genai"
    ONET_TASK = "onet_task"


class ScenarioScope(StrEnum):
    GLOBAL = "global"
    GEO = "geo"
    SECTOR = "sector"
    OCCUPATION = "occupation"
    JOB = "job"


class ScenarioStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    REFUTED = "refuted"
    RETIRED = "retired"


class ClaimStatus(StrEnum):
    OPEN = "open"
    SUPPORTED = "supported"
    CONTESTED = "contested"
    RESOLVED = "resolved"


class ClaimAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    REOPEN = "reopen"
    RESOLVE = "resolve"
    NOTE = "note"


class WatchScopeKind(StrEnum):
    GEO = "geo"
    SECTOR = "sector"
    SERIES = "series"
    INDICATOR = "indicator"
