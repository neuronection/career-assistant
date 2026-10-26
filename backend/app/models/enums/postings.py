"""Posting, market and application-pipeline vocabularies (plan 123.6 split)."""

from enum import StrEnum


class PostingStatus(StrEnum):
    NEW = "new"
    MAPPED = "mapped"
    EXPIRED = "expired"
    HIDDEN = "hidden"


class SourceKind(StrEnum):
    """What a `job_sources` row feeds: postings or a wider data family."""

    POSTING = "posting"
    MARKET = "market"
    UNIVERSITY = "university"
    SEARCH = "search"
    WEBHOOK_IN = "webhook_in"


class RadarCadence(StrEnum):
    """How often a job radar emits match digests (off = silent)."""

    INSTANT = "instant"
    DAILY = "daily"
    WEEKLY = "weekly"
    OFF = "off"


class HealthStatus(StrEnum):
    """Connector/webhook health, surfaced as a source badge."""

    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


class WebhookTarget(StrEnum):
    """Which pipeline consumes an inbound webhook event."""

    POSTING_STATUS = "posting_status"
    APPLICATION_STATUS = "application_status"
    INGEST = "ingest"


class PostingEvidence(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"


class PostingSkillPriority(StrEnum):
    MUST_HAVE = "must_have"
    NICE_TO_HAVE = "nice_to_have"
    BONUS = "bonus"


class MappingMethod(StrEnum):
    SKILL_OVERLAP = "skill_overlap"
    AI = "ai"
    MANUAL = "manual"


class SearchScope(StrEnum):
    CATALOG = "catalog"
    RANKINGS = "rankings"
    UNIVERSITIES = "universities"
    POSTINGS = "postings"


class Environment(StrEnum):
    OFFICE = "office"
    FIELD = "field"
    LAB = "lab"
    STUDIO = "studio"
    WORKSHOP = "workshop"
    CLINIC = "clinic"
    CLASSROOM = "classroom"
    VEHICLE = "vehicle"
    OUTDOORS = "outdoors"
    REMOTE = "remote"
    KITCHEN = "kitchen"
    STAGE = "stage"


class PhysicalActivity(StrEnum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    ACTIVE = "active"
    INTENSE = "physical_intense"


class PhysicalCondition(StrEnum):
    NONE = "none"
    MOBILITY_LIMITED = "mobility_limited"
    HEARING_IMPAIRED = "hearing_impaired"
    VISION_IMPAIRED = "vision_impaired"
    CHRONIC_FATIGUE = "chronic_fatigue"
    OTHER = "other"


class DemandOutlook(StrEnum):
    DECLINING = "declining"
    STABLE = "stable"
    GROWING = "growing"
    HOT = "hot"


class ApplicationStage(StrEnum):
    """Where an application sits in the pipeline."""

    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ApplicationVia(StrEnum):
    """The channel an application was submitted through."""

    URL = "url"
    EMAIL = "email"
    PORTAL = "portal"
    REFERRAL = "referral"
    EVENT = "event"
    OTHER = "other"


class ApplicationEventKind(StrEnum):
    """Timeline event kinds; every stage move writes `stage_change`."""

    STAGE_CHANGE = "stage_change"
    NOTE = "note"
    DOCUMENT_LINKED = "document_linked"
    FOLLOWUP_SENT = "followup_sent"
    FOLLOWUP_SNOOZED = "followup_snoozed"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    OFFER_RECEIVED = "offer_received"
    EXTERNAL_UPDATE = "external_update"
    IMPORTED = "imported"


class ApplicationActor(StrEnum):
    """Who wrote an application event."""

    USER = "user"
    SYSTEM = "system"
    ASSISTANT = "assistant"
    EXTENSION = "extension"


class ApplicationOutcome(StrEnum):
    """Terminal result of an application."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"
    GHOSTED = "ghosted"
