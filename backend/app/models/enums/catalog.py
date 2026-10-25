"""Job/university/relation/matching/label/metric vocabularies (plan 123.6 split)."""

from enum import StrEnum


class JobStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class JobSource(StrEnum):
    SEED = "seed"
    AI = "ai"
    USER = "user"


class RelationType(StrEnum):
    SIMILAR_TO = "similar_to"
    SPECIALISES_INTO = "specialises_into"
    LEADS_TO = "leads_to"
    ALTERNATIVE_TO = "alternative_to"
    PREREQUISITE_OF = "prerequisite_of"


class UniversityType(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    OTHER = "other"


class DegreeLevel(StrEnum):
    VOCATIONAL = "vocational"
    BACHELOR = "bachelor"
    MASTER = "master"
    PHD = "phd"


class PrerequisiteStatus(StrEnum):
    MET = "met"
    UNMET = "unmet"
    UNKNOWN = "unknown"


class MatchStatus(StrEnum):
    INTERESTED = "interested"
    CONSIDERING = "considering"
    DISMISSED = "dismissed"


class OrgStatus(StrEnum):
    """Organization lifecycle."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class CompanyType(StrEnum):
    """Company legal/operational type (company_profiles.company_type)."""

    PUBLIC = "public"
    PRIVATE = "private"
    SUBSIDIARY = "subsidiary"
    NONPROFIT = "nonprofit"
    GOVERNMENT = "government"
    STARTUP = "startup"


class FinancialClaimKind(StrEnum):
    """One reviewed financial claim (company_profiles.financials)."""

    REVENUE = "revenue"
    VALUATION = "valuation"
    MARKET_CAP = "market_cap"
    FUNDING = "funding"
    NET_WORTH = "net_worth"


class CompanyProfileSource(StrEnum):
    """Where a company-profile row's facts came from."""

    MANUAL = "manual"
    DERIVED = "derived"


class JobLinkKind(StrEnum):
    APPLY = "apply"
    LEARN = "learn"
    CERTIFICATION = "certification"
    VIDEO = "video"


class MetricGroup(StrEnum):
    """Metric dimension families."""

    INTEREST = "interest"
    VALUE = "value"
    WORKSTYLE = "workstyle"
    CONSTRAINT = "constraint"
    APTITUDE = "aptitude"


class UserMetricSource(StrEnum):
    """How a user metric value was produced."""

    SELF_REPORT = "self_report"
    ASSESSMENT = "assessment"
    BEHAVIOR = "behavior"
    DERIVED = "derived"


class LabelEntityKind(StrEnum):
    """Catalog entity families a label overlay can target."""

    JOB = "job"
    SKILL = "skill"
    FAMILY = "family"
    UNIVERSITY = "university"
    DEPARTMENT = "department"
    METRIC_DIMENSION = "metric_dimension"
    ASSESSMENT_TEMPLATE = "assessment_template"
    CV_TEMPLATE = "cv_template"


class LabelField(StrEnum):
    """Which display field an overlay replaces."""

    LABEL = "label"
    DESCRIPTION = "description"
    SHORT_DESCRIPTION = "short_description"


class LabelSource(StrEnum):
    """Who drafted an overlay (approval is the only route to `approved`)."""

    AI_DRAFT = "ai_draft"
    HUMAN = "human"


class LabelStatus(StrEnum):
    """Overlay review state."""

    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentKind(StrEnum):
    UNIVERSITY_CATALOG = "university_catalog"
    CV = "cv"
    PHOTO = "photo"
    OTHER = "other"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    ERROR = "error"
    APPLIED = "applied"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
