from enum import StrEnum
from typing import ClassVar


class EducationLevel(StrEnum):
    NO_FORMAL = "no_formal"
    MIDDLE_SCHOOL = "middle_school"
    HIGH_SCHOOL = "high_school"
    VOCATIONAL = "vocational"
    BACHELOR = "bachelor"
    MASTER = "master"
    DOCTORATE = "doctorate"


class EducationLevelOrder:
    """Ranking used to compare education requirements with what users have/want."""

    ORDER: ClassVar[dict[EducationLevel, int]] = {
        EducationLevel.NO_FORMAL: 0,
        EducationLevel.MIDDLE_SCHOOL: 1,
        EducationLevel.HIGH_SCHOOL: 2,
        EducationLevel.VOCATIONAL: 3,
        EducationLevel.BACHELOR: 4,
        EducationLevel.MASTER: 5,
        EducationLevel.DOCTORATE: 6,
    }

    @classmethod
    def at_least(cls, level: "EducationLevel", minimum: "EducationLevel") -> bool:
        """Return True when ``level`` meets or exceeds ``minimum``."""
        return cls.ORDER.get(level, 0) >= cls.ORDER.get(minimum, 0)


class DemandOutlook(StrEnum):
    DECLINING = "declining"
    STABLE = "stable"
    GROWING = "growing"
    HOT = "hot"


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


class UniversityType(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    OTHER = "other"


class DegreeLevel(StrEnum):
    VOCATIONAL = "vocational"
    BACHELOR = "bachelor"
    MASTER = "master"
    PHD = "phd"


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


class MatchStatus(StrEnum):
    INTERESTED = "interested"
    CONSIDERING = "considering"
    DISMISSED = "dismissed"


class PrerequisiteStatus(StrEnum):
    MET = "met"
    UNMET = "unmet"
    UNKNOWN = "unknown"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class SkillStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class SkillOrigin(StrEnum):
    BANK = "bank"
    AI = "ai"
    USER = "user"
    IMPORT = "import"
    CV_PARSE = "cv_parse"


class JobSkillImportance(StrEnum):
    CORE = "core"
    IMPORTANT = "important"
    BONUS = "bonus"


class JobSkillSource(StrEnum):
    SEED = "seed"
    AI = "ai"
    ADMIN = "admin"


class UserSkillSource(StrEnum):
    SELF_REPORT = "self_report"
    ASSESSMENT = "assessment"
    EXPERIENCE = "experience"
    AI_INFERRED = "ai_inferred"
    DOCUMENT = "document"


class PathStepKind(StrEnum):
    EDUCATION = "education"
    JOB = "job"
    EXPERIENCE = "experience"
    CERTIFICATION = "certification"


class PathSource(StrEnum):
    SEED = "seed"
    AI = "ai"
    ADMIN = "admin"


class PathStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class AssessmentKind(StrEnum):
    ONBOARDING = "onboarding"
    FULL = "full"
    CUSTOM = "custom"
    TEMPLATE = "template"


class AssessmentStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class QuestionKind(StrEnum):
    SCENARIO_MCQ = "scenario_mcq"
    TIME_ALLOCATION = "time_allocation"
    RANKING = "ranking"
    SLIDER = "slider"


class QuestionSource(StrEnum):
    BANK = "bank"
    AI = "ai"


class QuestionStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class AITaskType(StrEnum):
    ASSESSMENT_GENERATE = "assessment_generate"
    TEMPLATE_DESIGN = "template_design"
    PROFILE_ANALYZE = "profile_analyze"
    JOB_GENERATE = "job_generate"
    RELATION_SUGGEST = "relation_suggest"
    MATCH_SCORE = "match_score"
    UNIVERSITY_PARSE = "university_parse"
    CHAT = "chat"
    CHAT_OPS = "chat_ops"
    ASSIST = "assist"
    PATH_SUGGEST = "path_suggest"
    POSTING_MAP = "posting_map"
    POSTING_EXTRACT = "posting_extract"
    TARGET_RESOLVE = "target_resolve"
    TRANSCRIBE = "transcribe"
    CV_OCR = "cv_ocr"
    CV_PARSE = "cv_parse"
    CV_TEMPLATE_DESIGN = "cv_template_design"
    CV_TEMPLATE_REVIEW = "cv_template_review"
    CV_TEMPLATE_PICK = "cv_template_pick"
    CV_BUILD_REVIEW = "cv_build_review"
    CV_SUGGEST = "cv_suggest"
    CV_COVER_LETTER = "cv_cover_letter"
    CV_BUILDER_CHAT = "cv_builder_chat"
    CV_DRAFT = "cv_draft"
    CV_SYNTH = "cv_synth"
    CATALOG_ENRICH = "catalog_enrich"
    CHAT_TITLE = "chat_title"
    AUTOPILOT_RUN = "autopilot_run"
    INTERVIEW_PLAN = "interview_plan"
    INTERVIEW_TURN = "interview_turn"
    INTERVIEW_DEBRIEF = "interview_debrief"
    EMBED = "embed"
    MCP_TOOL_CALL = "mcp_tool_call"


class AIScope(StrEnum):
    SYSTEM = "system"
    USER = "user"


class AIProviderType(StrEnum):
    MOCK = "mock"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    GOOGLE = "google"


class AITaskTier(StrEnum):
    """Model tiers: fast interactive tasks vs deep quality ones."""

    FAST = "fast"
    STRONG = "strong"


class AICapability(StrEnum):
    """Capabilities a task requires from its assigned model.

    Also the allowed values of the persisted ``ai_models.caps`` list —
    the vocabulary must stay in sync with the UI's capability toggles.
    """

    TEXT = "text"
    VISION = "vision"
    TOOLS = "tools"
    EMBEDDINGS = "embeddings"
    AUDIO = "audio"


class TagSource(StrEnum):
    SELF = "self"
    AI = "ai"
    EXPRESS = "express"


class CareerStage(StrEnum):
    STUDENT = "student"
    EARLY_CAREER = "early_career"
    EXPERIENCED = "experienced"
    SWITCHING = "switching"
    RETURNING = "returning"


class OnboardingPath(StrEnum):
    """Start-path choice from the /onboarding hero.

    Drives the wizard step list and the required-section scope;
    changeable later, never a cage.
    """

    EXPLORE = "explore"
    TARGET = "target"
    CV_IMPORT = "cv_import"
    BROWSE = "browse"


class SearchScope(StrEnum):
    CATALOG = "catalog"
    RANKINGS = "rankings"
    UNIVERSITIES = "universities"
    POSTINGS = "postings"


class PostingStatus(StrEnum):
    NEW = "new"
    MAPPED = "mapped"
    EXPIRED = "expired"
    HIDDEN = "hidden"


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


class SalaryPeriod(StrEnum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class ApplicationStage(StrEnum):
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"


class GrowthPlanStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class GrowthStepKind(StrEnum):
    SKILL = "skill"
    EXPERIENCE = "experience"
    CERTIFICATION = "certification"
    EDUCATION = "education"


class GrowthStepStatus(StrEnum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    SKIPPED = "skipped"


class ResourceKind(StrEnum):
    COURSE = "course"
    BOOK = "book"
    CERT = "cert"
    DOC = "doc"
    VIDEO = "video"


class ResourceCost(StrEnum):
    FREE = "free"
    FREEMIUM = "freemium"
    PAID = "paid"


class ResourceStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class ResourceSource(StrEnum):
    ADMIN = "admin"
    AI = "ai"


class InterestTagKind(StrEnum):
    TOPIC = "topic"
    INDUSTRY = "industry"


class JobLinkKind(StrEnum):
    APPLY = "apply"
    LEARN = "learn"
    CERTIFICATION = "certification"
    VIDEO = "video"


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
    """Delivery channels; the registry leaves email/sms slots open."""

    IN_APP = "in_app"
    DESKTOP = "desktop"
    BROWSER = "browser"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class ExperienceKind(StrEnum):
    """Experience item kinds; legacy JSONB `part_time` maps to job."""

    JOB = "job"
    PROJECT = "project"
    INTERNSHIP = "internship"
    VOLUNTEER = "volunteer"
    FREELANCE = "freelance"


class ExperienceItemSource(StrEnum):
    SELF_REPORT = "self_report"
    CV_PARSE = "cv_parse"
    ASSESSMENT = "assessment"
    IMPORT = "import"


class ExperienceItemStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"


class RoleInItem(StrEnum):
    """The skill's role inside one experience item."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    EXPOSURE = "exposure"


class OrgStatus(StrEnum):
    """Organization lifecycle."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class AchievementMetricKind(StrEnum):
    TIME_SAVED = "time_saved"
    SCALE = "scale"
    REVENUE = "revenue"
    QUALITY = "quality"


class TemplateSource(StrEnum):
    """Where a template came from."""

    BANK = "bank"
    AI = "ai"
    USER = "user"
    IMPORTED = "imported"


class TemplateVisibility(StrEnum):
    """Visibility ladder; `public` stays unreachable until community
    sharing ships."""

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


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
    CV_EXTRACT_TEXT = "cv_extract_text"
    CV_OCR = "cv_ocr"
    CV_PARSE = "cv_parse"
    CATALOG_ENRICH = "catalog_enrich"
    CHAT_TITLE = "chat_title"
    AUTOPILOT_RUN = "autopilot_run"
    CV_GENERATE = "cv_generate"
    CV_POLISH = "cv_polish"
    CV_SYNTH = "cv_synth"
    FOLLOWUP_SWEEP = "followup_sweep"
    MARKET_HISTORY_CAPTURE = "market_history_capture"
    PROPOSAL_SWEEP = "proposal_sweep"
    CHECKPOINT_PRUNE = "checkpoint_prune"


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
    USER_SAVED_SEARCH = "user_saved_search"
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


class CvKind(StrEnum):
    """CV record kinds; cover letters land with 34.3."""

    RESUME = "resume"
    COVER_LETTER = "cover_letter"


class CvStatus(StrEnum):
    DRAFT = "draft"
    FINAL = "final"
    ARCHIVED = "archived"


class CvPageSize(StrEnum):
    A4 = "a4"
    LETTER = "letter"


class CvVersionCreator(StrEnum):
    """What produced an immutable cv_versions row."""

    USER_SAVE = "user_save"
    AI_APPLY = "ai_apply"
    EXPORT = "export"
    RESTORE = "restore"
    DUPLICATE = "duplicate"


class CvSynthStatus(StrEnum):
    """Lifecycle of a synthesized CV item (draft-then-approve)."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class CvSynthScope(StrEnum):
    """What a synthesized item replaces."""

    ITEM = "item"
    SUMMARY = "summary"


class CvSynthSource(StrEnum):
    """Who wrote the variant text."""

    AI = "ai"
    MANUAL = "manual"


class CvPageTextSource(StrEnum):
    """Where a source document page's text came from."""

    TEXT_LAYER = "text_layer"
    OCR_VISION = "ocr_vision"
    OCR_TESSERACT = "ocr_tesseract"


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


class CvTemplateSource(StrEnum):
    """Where a CV template came from."""

    BANK = "bank"
    AI = "ai"
    USER = "user"
    IMPORTED = "imported"
    DUPLICATED = "duplicated"


class CvTemplateVisibility(StrEnum):
    """Visibility ladder; `public` stays unreachable until community
    sharing ships."""

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class CvTemplateStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class CvOverflowPolicy(StrEnum):
    """What the renderer does when content exceeds the page budget."""

    SHRINK = "shrink"
    TRUNCATE = "truncate"
    WARN = "warn"


class AutopilotRunStatus(StrEnum):
    """Lifecycle of one autopilot run."""

    RUNNING = "running"
    COMPLETED = "completed"
    BUDGET_ABORTED = "budget_aborted"
    CANCELLED = "cancelled"
    FAILED = "failed"


class InterviewKind(StrEnum):
    """Interview practice session focus."""

    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    MIXED = "mixed"
    RESEARCH = "research"


class InterviewStatus(StrEnum):
    """Lifecycle of one interview practice session."""

    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class AutopilotFeedback(StrEnum):
    """Finding feedback that teaches the goal's constraints."""

    MORE_LIKE_THIS = "more_like_this"
    HIDE_LIKE_THIS = "hide_like_this"


class ProposalKind(StrEnum):
    """Entity kinds a HITL profile proposal can mutate (plan 77, 82)."""

    EXPERIENCE_ITEM = "experience_item"
    EDUCATION_ITEM = "education_item"
    CERTIFICATION = "certification"
    PROFILE_ACHIEVEMENT = "profile_achievement"
    USER_SKILL = "user_skill"
    PROFILE_SECTION = "profile_section"
    CV_SYNTH = "cv_synth"
    CV_SET_BULLETS = "cv_set_bullets"
    CV_CHOICE = "cv_choice"


class ProposalAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class ProposalStatus(StrEnum):
    """Detached-card lifecycle: resolve is idempotent per terminal state."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONFLICT = "conflict"
    EXPIRED = "expired"
    REVERTED = "reverted"


class ProposalSource(StrEnum):
    CHAT = "chat"
