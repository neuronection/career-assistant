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
    DETAIL_ENRICHMENT = "detail_enrichment"
    COMPANY_TRIAGE = "company_triage"
    DIGEST = "digest"
    SAVED_SEARCH_RUN = "saved_search_run"
    RADAR_DIGEST = "radar_digest"
    SMART_DIGEST = "smart_digest"  # plan 179: the opt-in daily smart digest
    QUERY_CURATOR = "query_curator"
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
    SKILL_RELATION_LEARN = "skill_relation_learn"
    VECTOR_INDEX = "vector_index"
    VECTOR_RECONCILE = "vector_reconcile"
    # Plan 51 Q1b: maintenance runs and synchronous cutover/gate evaluations.
    VECTOR_MAINTENANCE = "vector_maintenance"
    VECTOR_CUTOVER = "vector_cutover"
    RETRIEVAL_ALERT_SWEEP = "retrieval_alert_sweep"
    POSTING_REMAP = "posting_remap"
    # Plan 52 T2b: a bounded admin fetch of a pinned tokenizer asset. It is
    # deliberately not a VECTOR_* space run (no space lock, no run DTO).
    TOKENIZER_FETCH = "tokenizer_fetch"
    JOB_PROPOSAL_BACKFILL = "job_proposal_backfill"
    # Plan 205 S2: one-shot derivation of the typed mapping outcome columns
    # for legacy rows (deterministic, no AI, bounded, idempotent).
    MAPPING_OUTCOME_BACKFILL = "mapping_outcome_backfill"
    # Plan 205 S9: the daily coverage snapshot capture and the admin
    # mapping-alert sweep (the retrieval-alert pattern).
    MAPPING_COVERAGE_CAPTURE = "mapping_coverage_capture"
    MAPPING_ALERT_SWEEP = "mapping_alert_sweep"


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
    SYSTEM_SKILL_RELATION_LEARN = "system_skill_relation_learn"
    SYSTEM_VECTOR_RECONCILE = "system_vector_reconcile"
    SYSTEM_RETRIEVAL_ALERTS = "system_retrieval_alerts"
    # Plan 205 S9: the mapping console's daily snapshot + alert schedules.
    SYSTEM_MAPPING_COVERAGE = "system_mapping_coverage"
    SYSTEM_MAPPING_ALERTS = "system_mapping_alerts"
    USER_SAVED_SEARCH = "user_saved_search"
    USER_RADAR_DIGEST = "user_radar_digest"
    USER_SMART_DIGEST = "user_smart_digest"
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
