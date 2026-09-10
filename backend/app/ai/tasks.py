"""Task registry — one TaskDef per ``AITaskType``.

Declares, as data: what capability the task requires (validated against
the provider system), its default model tier (``fast`` | ``strong`` —
overridable per task through AI Settings tier assignments), and a
human description for the settings UI. The registry is the single place
that maps task semantics; the gateway consults it for audit metadata and
tier routing.
"""

from dataclasses import dataclass

from app.models.enums import AICapability, AITaskType, AITaskTier


@dataclass(frozen=True)
class TaskDef:
    """Static declaration of one AI task type."""

    task: str
    description: str
    requires: str
    tier: str


TASK_DEFS: list[TaskDef] = [
    TaskDef(
        AITaskType.ASSESSMENT_GENERATE.value,
        "Assessment question generation",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.TEMPLATE_DESIGN.value,
        "Assessment template drafting",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.PROFILE_ANALYZE.value,
        "Profile analysis into structured insights",
        AICapability.TEXT.value,
        AITaskTier.FAST.value,
    ),
    TaskDef(
        AITaskType.JOB_GENERATE.value,
        "Catalog job + relation draft generation",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.RELATION_SUGGEST.value,
        "Typed job relation suggestions (batch)",
        AICapability.TEXT.value,
        AITaskTier.FAST.value,
    ),
    TaskDef(
        AITaskType.MATCH_SCORE.value,
        "Per-user job match score with rationale + prerequisites",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.UNIVERSITY_PARSE.value,
        "University catalog / admission-baseline parsing",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.CHAT.value,
        "Catalog-grounded chatbot",
        AICapability.TEXT.value,
        AITaskTier.FAST.value,
    ),
    TaskDef(
        AITaskType.ASSIST.value,
        "Contextual Ask-AI popup answers",
        AICapability.TEXT.value,
        AITaskTier.FAST.value,
    ),
    TaskDef(
        AITaskType.PATH_SUGGEST.value,
        "Career path suggestions from the catalog graph",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.POSTING_MAP.value,
        "Fast-pass posting-to-catalog mapping",
        AICapability.TEXT.value,
        AITaskTier.FAST.value,
    ),
    TaskDef(
        AITaskType.POSTING_EXTRACT.value,
        "Deep posting extraction (skills, salary, benefits)",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.TARGET_RESOLVE.value,
        "Express target-mode archetype resolution",
        AICapability.TEXT.value,
        AITaskTier.FAST.value,
    ),
    TaskDef(
        AITaskType.CV_OCR.value,
        "CV page OCR into text (vision)",
        AICapability.VISION.value,
        AITaskTier.FAST.value,
    ),
    TaskDef(
        AITaskType.CV_PARSE.value,
        "CV field extraction with evidence quotes",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.CV_TEMPLATE_DESIGN.value,
        "CV template block drafting",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.CV_TEMPLATE_REVIEW.value,
        "CV visual review critique",
        AICapability.VISION.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.CV_SUGGEST.value,
        "CV writing proposals (summary, bullets, compaction, tailoring)",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.CV_COVER_LETTER.value,
        "Cover-letter drafting grounded in the evidence allowlist",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.CV_BUILDER_CHAT.value,
        "CV builder copilot: structured builder operations from chat",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.CV_DRAFT.value,
        "One-shot CV drafting: section plan + grounded section texts",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.CATALOG_ENRICH.value,
        "Catalog archetype v2 enrichment proposals",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.AUTOPILOT_RUN.value,
        "Autopilot search planning/curation for a career goal",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.TRANSCRIBE.value,
        "Dictation audio transcription",
        AICapability.TEXT.value,
        AITaskTier.FAST.value,
    ),
    TaskDef(
        AITaskType.INTERVIEW_PLAN.value,
        "Mock-interview question plan from a posting extract or archetype",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.INTERVIEW_TURN.value,
        "Interview practice turn: answer feedback + next question",
        AICapability.TEXT.value,
        AITaskTier.FAST.value,
    ),
    TaskDef(
        AITaskType.INTERVIEW_DEBRIEF.value,
        "Interview debrief narrative over the rubric aggregate",
        AICapability.TEXT.value,
        AITaskTier.STRONG.value,
    ),
    TaskDef(
        AITaskType.EMBED.value,
        "Semantic-search embeddings for postings and catalog text",
        AICapability.EMBEDDINGS.value,
        AITaskTier.FAST.value,
    ),
    TaskDef(
        AITaskType.MCP_TOOL_CALL.value,
        "External MCP bridge tool execution",
        AICapability.TEXT.value,
        AITaskTier.FAST.value,
    ),
]

TASKS_BY_NAME: dict[str, TaskDef] = {t.task: t for t in TASK_DEFS}


def task_def(task_value: str) -> TaskDef:
    """The TaskDef for a task type value (KeyError on unknown)."""
    return TASKS_BY_NAME[task_value]


def task_tier(task_value: str) -> str:
    """Default model tier of a task type."""
    return TASKS_BY_NAME[task_value].tier


def task_capability(task_value: str) -> str:
    """Capability required by a task type."""
    return TASKS_BY_NAME[task_value].requires
