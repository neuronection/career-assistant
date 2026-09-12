"""Prompt versions — a prompt change is a visible, revertable event.

Every audit row in ``ai_generations`` records the version of the system
prompt in effect, so a prompt edit is traceable per generation. Discipline:
bump a task's version in the SAME commit that changes its prompt text, and
re-bless the golden eval fixtures (``app/ai/evals``) — the eval suite fails
on a version bump it hasn't been re-blessed for, the same way ruff/pytest
block commits.
"""

from app.models.enums import AITaskType

PROMPT_VERSIONS: dict[str, int] = {
    AITaskType.ASSESSMENT_GENERATE.value: 1,
    AITaskType.TEMPLATE_DESIGN.value: 1,
    AITaskType.PROFILE_ANALYZE.value: 1,
    AITaskType.JOB_GENERATE.value: 2,
    AITaskType.RELATION_SUGGEST.value: 1,
    AITaskType.MATCH_SCORE.value: 1,
    AITaskType.UNIVERSITY_PARSE.value: 1,
    AITaskType.CHAT.value: 1,
    AITaskType.ASSIST.value: 1,
    AITaskType.PATH_SUGGEST.value: 1,
    AITaskType.POSTING_MAP.value: 1,
    AITaskType.POSTING_EXTRACT.value: 2,
    AITaskType.TARGET_RESOLVE.value: 1,
    AITaskType.CV_OCR.value: 1,
    AITaskType.CV_PARSE.value: 1,
    AITaskType.CV_TEMPLATE_DESIGN.value: 1,
    AITaskType.CV_TEMPLATE_REVIEW.value: 1,
    AITaskType.CV_TEMPLATE_PICK.value: 1,
    AITaskType.CV_BUILD_REVIEW.value: 1,
    AITaskType.CV_SUGGEST.value: 1,
    AITaskType.CV_COVER_LETTER.value: 1,
    AITaskType.CV_BUILDER_CHAT.value: 1,
    AITaskType.CV_DRAFT.value: 1,
    AITaskType.CV_SYNTH.value: 1,
    AITaskType.CATALOG_ENRICH.value: 1,
    AITaskType.AUTOPILOT_RUN.value: 1,
    AITaskType.INTERVIEW_PLAN.value: 1,
    AITaskType.INTERVIEW_TURN.value: 1,
    AITaskType.INTERVIEW_DEBRIEF.value: 1,
    AITaskType.EMBED.value: 1,
    AITaskType.MCP_TOOL_CALL.value: 1,
    AITaskType.TRANSCRIBE.value: 1,
}


def prompt_version(task_value: str) -> str:
    """Version label (``v1``, ``v2``…) of the prompt in effect for a task."""
    return f"v{PROMPT_VERSIONS[task_value]}"
