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
    OTHER = "other"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    ERROR = "error"
    APPLIED = "applied"


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


class AIScope(str, Enum):
    SYSTEM = "system"
    USER = "user"


class AIProviderType(str, Enum):
    MOCK = "mock"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"


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
    """Inbox state of one (notification, recipient) pair (plan 36)."""

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


class ScheduleKind(str, Enum):
    SYSTEM_SOURCE_SYNC = "system_source_sync"
    SYSTEM_DIGEST = "system_digest"
    SYSTEM_DEMAND_IMPORT = "system_demand_import"
    SYSTEM_REFIT_SWEEP = "system_refit_sweep"
    USER_SAVED_SEARCH = "user_saved_search"
    USER_CHECKIN = "user_checkin"


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
