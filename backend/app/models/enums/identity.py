"""Platform/account, scheduling, notification and token vocabularies (plan 123.6 split)."""

from enum import StrEnum


class OnboardingPath(StrEnum):
    """Start-path choice from the /onboarding hero.

    Drives the wizard step list and the required-section scope;
    changeable later, never a cage.
    """

    EXPLORE = "explore"
    TARGET = "target"
    CV_IMPORT = "cv_import"
    BROWSE = "browse"


class BackgroundJobType(StrEnum):
    DOCUMENT_PARSE = "document_parse"
    JOB_GENERATE = "job_generate"
    MATCH_SCORE = "match_score"
    DATA_EXPORT = "data_export"
    PATH_SUGGEST = "path_suggest"
    FIT_REFIT = "fit_refit"
    POSTING_SYNC = "posting_sync"
    POSTING_EXTRACT = "posting_extract"
    DIGEST = "digest"
    SAVED_SEARCH_RUN = "saved_search_run"
    RADAR_DIGEST = "radar_digest"
    CV_EXTRACT_TEXT = "cv_extract_text"
    CV_OCR = "cv_ocr"
    CV_PARSE = "cv_parse"
    CATALOG_ENRICH = "catalog_enrich"
    AUTOPILOT_RUN = "autopilot_run"
    CV_GENERATE = "cv_generate"
    CV_POLISH = "cv_polish"
    CV_SYNTH = "cv_synth"
    FOLLOWUP_SWEEP = "followup_sweep"
    MARKET_HISTORY_CAPTURE = "market_history_capture"
    PROPOSAL_SWEEP = "proposal_sweep"
    CHECKPOINT_PRUNE = "checkpoint_prune"
    EXTENSION_RECONCILE = "extension_reconcile"
    NOTIFICATION_DELIVERY = "notification_delivery"
    DEMAND_IMPORT = "demand_import"


class ScheduleKind(StrEnum):
    SYSTEM_SOURCE_SYNC = "system_source_sync"
    SYSTEM_DIGEST = "system_digest"
    SYSTEM_DEMAND_IMPORT = "system_demand_import"
    SYSTEM_REFIT_SWEEP = "system_refit_sweep"
    SYSTEM_CATALOG_ENRICH = "system_catalog_enrich"
    SYSTEM_FOLLOWUPS = "system_followups"
    SYSTEM_MARKET_HISTORY = "system_market_history"
    SYSTEM_PROPOSAL_SWEEP = "system_proposal_sweep"
    SYSTEM_CHECKPOINT_PRUNE = "system_checkpoint_prune"
    SYSTEM_EXTENSION_RECONCILE = "system_extension_reconcile"
    USER_SAVED_SEARCH = "user_saved_search"
    USER_RADAR_DIGEST = "user_radar_digest"
    USER_CHECKIN = "user_checkin"
    USER_AUTOPILOT = "user_autopilot"


class MisfirePolicy(StrEnum):
    ASAP = "asap"
    SKIP = "skip"
    NEXT_SLOT = "next_slot"


class ScheduleStatus(StrEnum):
    CLAIMED = "claimed"
    QUEUED = "queued"
    SKIPPED_OVERLAP = "skipped_overlap"
    SKIPPED_MISFIRE = "skipped_misfire"
    BACKOFF = "backoff"
    FAILED = "failed"
    OK = "ok"


class BackgroundJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class McpTokenScope(StrEnum):
    """Closed MCP token scope vocabulary; `write` ships with 119's tools."""

    READ = "read"
    WRITE = "write"


class FeedTokenKind(StrEnum):
    """Signed-subscription flavours (calendar feed, RSS)."""

    ICS = "ics"
    RSS = "rss"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class NotificationRuleKind(StrEnum):
    FIT_THRESHOLD = "fit_threshold"
    NEW_IN_FAMILY = "new_in_family"
    NEW_POSTING_MATCH = "new_posting_match"


class NotificationSeverity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"


class NotificationStatus(StrEnum):
    """Inbox state of one (notification, recipient) pair."""

    UNREAD = "unread"
    READ = "read"
    DISMISSED = "dismissed"


class NotificationChannel(StrEnum):
    """Delivery channels; the channel registry is the extensibility seam."""

    IN_APP = "in_app"
    DESKTOP = "desktop"
    BROWSER = "browser"
    EMAIL = "email"
    WEBHOOK = "webhook"
