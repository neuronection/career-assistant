"""AI, assessment, interview, autopilot and HITL-proposal vocabularies (plan 123.6 split)."""

from enum import StrEnum


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
    SANDBOX_CAPABILITY_CALL = "sandbox_capability_call"
    TOOL_RUN = "tool_run"  # D20: one audit row per confirmed tool execution
    TRANSLATE = "translate"  # plan 121: UI catalog + catalog-label translation batches
    DECISION = "decision"  # ADR-0036: the decision default slot beside the kind overrides
    DECISION_TOOL_DISPATCH = "decision_tool_dispatch"
    DECISION_BOOLEAN_GATE = "decision_boolean_gate"
    DECISION_CHOICE = "decision_choice"
    DECISION_SCORE = "decision_score"


class AIProviderType(StrEnum):
    MOCK = "mock"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    GOOGLE = "google"
    DECISION = "decision"


class AITaskTier(StrEnum):
    """Model tiers: fast interactive tasks vs deep quality ones."""

    FAST = "fast"
    STRONG = "strong"


class AICapability(StrEnum):
    """Capabilities a task requires from its assigned model.

    Also the allowed values of the persisted ``ai_models.caps`` list —
    the vocabulary must stay in sync with the UI's capability toggles
    and the family canonical (§15: ``stt``/``tts`` split, no ``audio``;
    ``decision`` is explicit-only, never name-inferred).
    """

    TEXT = "text"
    VISION = "vision"
    TOOLS = "tools"
    EMBEDDINGS = "embeddings"
    STT = "stt"
    TTS = "tts"
    DECISION = "decision"


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


class AutopilotRunStatus(StrEnum):
    """Lifecycle of one autopilot run."""

    RUNNING = "running"
    COMPLETED = "completed"
    BUDGET_ABORTED = "budget_aborted"
    CANCELLED = "cancelled"
    FAILED = "failed"


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
    TOOL_EXECUTION = "tool_execution"  # D20: one destructive tool call, confirmed


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
    MCP = "mcp"
    AUTOPILOT = "autopilot"
    IMPORT = "import"


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
