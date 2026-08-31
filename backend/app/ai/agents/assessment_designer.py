"""AI scenario designer: drafts personalized scenario questions (Phase 23).

Phase 25 adds career-stage awareness: the same pipeline asks a returner
about re-entry gaps and a switcher about transferable skills.
"""

from app.ai.agents.context import context_json, parse_context
from app.ai.provider import ainvoke_structured, register_mock_fixture
from app.ai.schemas import AssessmentQuestionSet
from app.models.enums import AITaskType
from sqlalchemy.ext.asyncio import AsyncSession

STAGE_PROMPT_HINTS = {
    "student": "current coursework and first jobs",
    "early_career": "first full-time roles and fast skill growth",
    "experienced": "deep expertise and the next step",
    "switching": "transferable skills and the move into a new field",
    "returning": "re-entry after a gap and rebuilding momentum",
}


def _build_user_prompt(
    profile_snapshot: dict,
    top_family_keys: list[str],
    skill_keys: list[str],
    count: int,
    stage: str = "student",
) -> str:
    return context_json(
        {
            "profile": profile_snapshot,
            "top_family_keys": top_family_keys,
            "skill_taxonomy": skill_keys,
            "career_stage": stage,
            "count": count,
        }
    )


def _mock_question_set(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    families = ctx.get("top_family_keys") or ["technology"]
    skills = ctx.get("skill_taxonomy") or []
    stage = ctx.get("career_stage") or "student"
    questions = []
    for index in range(min(3, max(1, int(ctx.get("count", 3))))):
        skill_a = skills[index % len(skills)] if skills else "problem-solving"
        skill_b = skills[(index + 1) % len(skills)] if skills else "teamwork"
        questions.append(
            {
                "kind": "scenario_mcq",
                "prompt": f"For someone at the {stage} stage in a {families[index % len(families)]} project: your team hits a mid-project setback. What do you do first?",
                "help": "Pick the option closest to what you would actually do.",
                "options": [
                    {
                        "label": "Dig into the technical fault yourself",
                        "detail": "Hands-on debugging until the cause is clear.",
                        "scores": {"skill_levels": {skill_a: 4}, "interest_keys": []},
                    },
                    {
                        "label": "Pull the team together and re-plan",
                        "detail": "Align people, then divide the work.",
                        "scores": {"skill_levels": {skill_b: 3}, "interest_keys": []},
                    },
                    {
                        "label": "Talk to the stakeholders about scope",
                        "detail": "Reset expectations before fixing anything.",
                        "scores": {"skill_levels": {skill_b: 2}, "interest_keys": []},
                    },
                ],
            }
        )
    return {"questions": questions}


register_mock_fixture(AITaskType.ASSESSMENT_GENERATE, _mock_question_set)


async def generate_question_set(
    db: AsyncSession,
    user_id,
    profile_snapshot: dict,
    top_family_keys: list[str],
    skill_keys: list[str],
    count: int = 4,
    stage: str = "student",
) -> AssessmentQuestionSet:
    """Draft personalized scenario questions validated onto the taxonomy."""
    hint = STAGE_PROMPT_HINTS.get(stage, "career exploration")
    return await ainvoke_structured(
        db,
        AITaskType.ASSESSMENT_GENERATE,
        AssessmentQuestionSet,
        system=(
            "You design career-discovery scenario questions. The user's "
            f"career stage is '{stage}' — ground scenarios in {hint}. "
            "Every question must be answerable by anyone; options must be "
            "concrete, non-judgmental and spread across different job "
            "families. skill_levels keys must come from the provided skill "
            "taxonomy; interest_keys from interest taxonomy keys."
        ),
        user=_build_user_prompt(
            profile_snapshot, top_family_keys, skill_keys, count, stage
        ),
        user_id=user_id,
    )
