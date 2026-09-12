from enum import Enum


class EducationLevel(str, Enum):
    NO_FORMAL = "no_formal"
    MIDDLE_SCHOOL = "middle_school"
    HIGH_SCHOOL = "high_school"
    VOCATIONAL = "vocational"
    BACHELOR = "bachelor"
    MASTER = "master"
    DOCTORATE = "doctorate"


class EducationLevelOrder:
    """Ranking used to compare education requirements with what users have/want."""

    ORDER = {
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


class DemandOutlook(str, Enum):
    DECLINING = "declining"
    STABLE = "stable"
    GROWING = "growing"
    HOT = "hot"


class JobStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


class JobSource(str, Enum):
    SEED = "seed"
    AI = "ai"
    USER = "user"


class RelationType(str, Enum):
    SIMILAR_TO = "similar_to"
    SPECIALISES_INTO = "specialises_into"
    LEADS_TO = "leads_to"
    ALTERNATIVE_TO = "alternative_to"
    PREREQUISITE_OF = "prerequisite_of"


class Environment(str, Enum):
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


class PhysicalActivity(str, Enum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    ACTIVE = "active"
    INTENSE = "physical_intense"


class PhysicalCondition(str, Enum):
    NONE = "none"
    MOBILITY_LIMITED = "mobility_limited"
    HEARING_IMPAIRED = "hearing_impaired"
    VISION_IMPAIRED = "vision_impaired"
    CHRONIC_FATIGUE = "chronic_fatigue"
    OTHER = "other"


class UniversityType(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    OTHER = "other"


class DegreeLevel(str, Enum):
    VOCATIONAL = "vocational"
    BACHELOR = "bachelor"
    MASTER = "master"
    PHD = "phd"


class DocumentKind(str, Enum):
    UNIVERSITY_CATALOG = "university_catalog"
    CV = "cv"
    PHOTO = "photo"
    OTHER = "other"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    ERROR = "error"
    APPLIED = "applied"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class MatchStatus(str, Enum):
    INTERESTED = "interested"
    CONSIDERING = "considering"
    DISMISSED = "dismissed"


class PrerequisiteStatus(str, Enum):
    MET = "met"
    UNMET = "unmet"
    UNKNOWN = "unknown"


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class SkillStatus(str, Enum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class SkillOrigin(str, Enum):
    BANK = "bank"
    AI = "ai"
    USER = "user"
    IMPORT = "import"
    CV_PARSE = "cv_parse"


class JobSkillImportance(str, Enum):
    CORE = "core"
    IMPORTANT = "important"
    BONUS = "bonus"


class JobSkillSource(str, Enum):
    SEED = "seed"
    AI = "ai"
    ADMIN = "admin"


class UserSkillSource(str, Enum):
    SELF_REPORT = "self_report"
    ASSESSMENT = "assessment"
    EXPERIENCE = "experience"
    AI_INFERRED = "ai_inferred"
    DOCUMENT = "document"


class PathStepKind(str, Enum):
    EDUCATION = "education"
    JOB = "job"
    EXPERIENCE = "experience"
    CERTIFICATION = "certification"


class PathSource(str, Enum):
    SEED = "seed"
    AI = "ai"
    ADMIN = "admin"


class PathStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


class AssessmentKind(str, Enum):
    ONBOARDING = "onboarding"
    FULL = "full"
    CUSTOM = "custom"
    TEMPLATE = "template"


class AssessmentStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class QuestionKind(str, Enum):
    SCENARIO_MCQ = "scenario_mcq"
    TIME_ALLOCATION = "time_allocation"
    RANKING = "ranking"
    SLIDER = "slider"


class QuestionSource(str, Enum):
    BANK = "bank"
    AI = "ai"


class QuestionStatus(str, Enum):
    ACTIVE = "active"
    RETIRED = "retired"


class AITaskType(str, Enum):
    ASSESSMENT_GENERATE = "assessment_generate"
    TEMPLATE_DESIGN = "template_design"
    PROFILE_ANALYZE = "profile_analyze"
    JOB_GENERATE = "job_generate"
    RELATION_SUGGEST = "relation_suggest"
    MATCH_SCORE = "match_score"
    UNIVERSITY_PARSE = "university_parse"
    CHAT = "chat"
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
    AUTOPILOT_RUN = "autopilot_run"
    INTERVIEW_PLAN = "interview_plan"
    INTERVIEW_TURN = "interview_turn"
    INTERVIEW_DEBRIEF = "interview_debrief"
    EMBED = "embed"
    MCP_TOOL_CALL = "mcp_tool_call"


class AIScope(str, Enum):
    SYSTEM = "system"
    USER = "user"


class AIProviderType(str, Enum):
    MOCK = "mock"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    GOOGLE = "google"


class AITaskTier(str, Enum):
    """Model tiers: fast interactive tasks vs deep quality ones."""

    FAST = "fast"
    STRONG = "strong"


class AICapability(str, Enum):
    """Capabilities a task requires from its assigned model.

    Also the allowed values of the persisted ``ai_models.caps`` list —
    the vocabulary must stay in sync with the UI's capability toggles.
    """

    TEXT = "text"
    VISION = "vision"
    TOOLS = "tools"
    EMBEDDINGS = "embeddings"
    AUDIO = "audio"


class TagSource(str, Enum):
    SELF = "self"
    AI = "ai"
    EXPRESS = "express"


class CareerStage(str, Enum):
    STUDENT = "student"
    EARLY_CAREER = "early_career"
    EXPERIENCED = "experienced"
    SWITCHING = "switching"
    RETURNING = "returning"


class OnboardingPath(str, Enum):
    """Start-path choice from the /onboarding hero.

    Drives the wizard step list and the required-section scope;
    changeable later, never a cage.
    """

    EXPLORE = "explore"
    TARGET = "target"
    CV_IMPORT = "cv_import"
    BROWSE = "browse"


class SearchScope(str, Enum):
    CATALOG = "catalog"
    RANKINGS = "rankings"
    UNIVERSITIES = "universities"
    POSTINGS = "postings"


class PostingStatus(str, Enum):
    NEW = "new"
    MAPPED = "mapped"
    EXPIRED = "expired"
    HIDDEN = "hidden"


class PostingEvidence(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"


class PostingSkillPriority(str, Enum):
    MUST_HAVE = "must_have"
    NICE_TO_HAVE = "nice_to_have"
    BONUS = "bonus"


class MappingMethod(str, Enum):
    SKILL_OVERLAP = "skill_overlap"
    AI = "ai"
    MANUAL = "manual"


class SalaryPeriod(str, Enum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class ApplicationStage(str, Enum):
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"


class Seniority(str, Enum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"


class GrowthPlanStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class GrowthStepKind(str, Enum):
    SKILL = "skill"
    EXPERIENCE = "experience"
    CERTIFICATION = "certification"
    EDUCATION = "education"


class GrowthStepStatus(str, Enum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    SKIPPED = "skipped"


class ResourceKind(str, Enum):
    COURSE = "course"
    BOOK = "book"
    CERT = "cert"
    DOC = "doc"
    VIDEO = "video"


class ResourceCost(str, Enum):
    FREE = "free"
    FREEMIUM = "freemium"
    PAID = "paid"


class ResourceStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


class ResourceSource(str, Enum):
    ADMIN = "admin"
    AI = "ai"


class InterestTagKind(str, Enum):
    TOPIC = "topic"
    INDUSTRY = "industry"


class JobLinkKind(str, Enum):
    APPLY = "apply"
    LEARN = "learn"
    CERTIFICATION = "certification"
    VIDEO = "video"


class NotificationRuleKind(str, Enum):
    FIT_THRESHOLD = "fit_threshold"
    NEW_IN_FAMILY = "new_in_family"
    NEW_POSTING_MATCH = "new_posting_match"


class NotificationSeverity(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"


class NotificationStatus(str, Enum):
    """Inbox state of one (notification, recipient) pair."""

    UNREAD = "unread"
    READ = "read"
    DISMISSED = "dismissed"


class NotificationChannel(str, Enum):
    """Delivery channels; the registry leaves email/sms slots open."""

    IN_APP = "in_app"
    DESKTOP = "desktop"
    BROWSER = "browser"


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class ExperienceKind(str, Enum):
    """Experience item kinds; legacy JSONB `part_time` maps to job."""

    JOB = "job"
    PROJECT = "project"
    INTERNSHIP = "internship"
    VOLUNTEER = "volunteer"
    FREELANCE = "freelance"


class ExperienceItemSource(str, Enum):
    SELF_REPORT = "self_report"
    CV_PARSE = "cv_parse"
    ASSESSMENT = "assessment"
    IMPORT = "import"


class ExperienceItemStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"


class RoleInItem(str, Enum):
    """The skill's role inside one experience item."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    EXPOSURE = "exposure"


class OrgStatus(str, Enum):
    """Organization lifecycle."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class AchievementMetricKind(str, Enum):
    TIME_SAVED = "time_saved"
    SCALE = "scale"
    REVENUE = "revenue"
    QUALITY = "quality"


class TemplateSource(str, Enum):
    """Where a template came from."""

    BANK = "bank"
    AI = "ai"
    USER = "user"
    IMPORTED = "imported"


class TemplateVisibility(str, Enum):
    """Visibility ladder; `public` stays unreachable until community
    sharing ships."""

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class TemplateStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class BackgroundJobType(str, Enum):
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
    AUTOPILOT_RUN = "autopilot_run"
    CV_GENERATE = "cv_generate"
    CV_POLISH = "cv_polish"
    CV_SYNTH = "cv_synth"
    FOLLOWUP_SWEEP = "followup_sweep"
    MARKET_HISTORY_CAPTURE = "market_history_capture"


class ScheduleKind(str, Enum):
    SYSTEM_SOURCE_SYNC = "system_source_sync"
    SYSTEM_DIGEST = "system_digest"
    SYSTEM_DEMAND_IMPORT = "system_demand_import"
    SYSTEM_REFIT_SWEEP = "system_refit_sweep"
    SYSTEM_CATALOG_ENRICH = "system_catalog_enrich"
    SYSTEM_FOLLOWUPS = "system_followups"
    SYSTEM_MARKET_HISTORY = "system_market_history"
    USER_SAVED_SEARCH = "user_saved_search"
    USER_CHECKIN = "user_checkin"
    USER_AUTOPILOT = "user_autopilot"


class MisfirePolicy(str, Enum):
    ASAP = "asap"
    SKIP = "skip"
    NEXT_SLOT = "next_slot"


class ScheduleStatus(str, Enum):
    CLAIMED = "claimed"
    QUEUED = "queued"
    SKIPPED_OVERLAP = "skipped_overlap"
    SKIPPED_MISFIRE = "skipped_misfire"
    BACKOFF = "backoff"
    FAILED = "failed"
    OK = "ok"


class BackgroundJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CvKind(str, Enum):
    """CV record kinds; cover letters land with 34.3."""

    RESUME = "resume"
    COVER_LETTER = "cover_letter"


class CvStatus(str, Enum):
    DRAFT = "draft"
    FINAL = "final"
    ARCHIVED = "archived"


class CvPageSize(str, Enum):
    A4 = "a4"
    LETTER = "letter"


class CvVersionCreator(str, Enum):
    """What produced an immutable cv_versions row."""

    USER_SAVE = "user_save"
    AI_APPLY = "ai_apply"
    EXPORT = "export"
    RESTORE = "restore"
    DUPLICATE = "duplicate"


class CvSynthStatus(str, Enum):
    """Lifecycle of a synthesized CV item (draft-then-approve)."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class CvSynthScope(str, Enum):
    """What a synthesized item replaces."""

    ITEM = "item"
    SUMMARY = "summary"


class CvSynthSource(str, Enum):
    """Who wrote the variant text."""

    AI = "ai"
    MANUAL = "manual"


class CvPageTextSource(str, Enum):
    """Where a source document page's text came from."""

    TEXT_LAYER = "text_layer"
    OCR_VISION = "ocr_vision"
    OCR_TESSERACT = "ocr_tesseract"


class MetricGroup(str, Enum):
    """Metric dimension families."""

    INTEREST = "interest"
    VALUE = "value"
    WORKSTYLE = "workstyle"
    CONSTRAINT = "constraint"
    APTITUDE = "aptitude"


class UserMetricSource(str, Enum):
    """How a user metric value was produced."""

    SELF_REPORT = "self_report"
    ASSESSMENT = "assessment"
    BEHAVIOR = "behavior"
    DERIVED = "derived"


class CvTemplateSource(str, Enum):
    """Where a CV template came from."""

    BANK = "bank"
    AI = "ai"
    USER = "user"
    IMPORTED = "imported"
    DUPLICATED = "duplicated"


class CvTemplateVisibility(str, Enum):
    """Visibility ladder; `public` stays unreachable until community
    sharing ships."""

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class CvTemplateStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class CvOverflowPolicy(str, Enum):
    """What the renderer does when content exceeds the page budget."""

    SHRINK = "shrink"
    TRUNCATE = "truncate"
    WARN = "warn"


class AutopilotRunStatus(str, Enum):
    """Lifecycle of one autopilot run."""

    RUNNING = "running"
    COMPLETED = "completed"
    BUDGET_ABORTED = "budget_aborted"
    CANCELLED = "cancelled"
    FAILED = "failed"


class InterviewKind(str, Enum):
    """Interview practice session focus."""

    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    MIXED = "mixed"
    RESEARCH = "research"


class InterviewStatus(str, Enum):
    """Lifecycle of one interview practice session."""

    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class AutopilotFeedback(str, Enum):
    """Finding feedback that teaches the goal's constraints."""

    MORE_LIKE_THIS = "more_like_this"
    HIDE_LIKE_THIS = "hide_like_this"
