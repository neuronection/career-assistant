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


# ---------------------------------------------- template drafting (plan 37)


def _mock_template_content(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    skills = ctx.get("skill_taxonomy") or ["problem-solving"]
    brief = ctx.get("brief") or {}
    length = int(brief.get("question_count") or 2)
    skill_a = skills[0]
    skill_b = skills[1 % len(skills)]
    questions = []
    for index in range(max(1, min(length, 5))):
        if index % 2 == 0:
            questions.append(
                {
                    "kind": "scenario_mcq",
                    "prompt": (
                        f"{brief.get('title') or 'A work scenario'}: the deadline "
                        "moves up by a week. What is your first move?"
                    ),
                    "help": "Pick the closest option.",
                    "options": [
                        {
                            "id": "o1",
                            "label": "Re-plan the work with the team",
                            "scores": {
                                "skill_levels": {skill_a: 3},
                                "interest_keys": [],
                            },
                        },
                        {
                            "id": "o2",
                            "label": "Shield the team and renegotiate scope",
                            "scores": {
                                "skill_levels": {skill_b: 3},
                                "interest_keys": [],
                            },
                        },
                    ],
                }
            )
        else:
            questions.append(
                {
                    "kind": "slider",
                    "prompt": f"How confident are you with {skill_a.replace('-', ' ')}?",
                    "help": "1 = new to it, 10 = teach it.",
                    "skill_key": skill_a,
                }
            )
    return {
        "schema_version": 1,
        "phases": [
            {"title": brief.get("title") or "Draft template", "questions": questions}
        ],
        "normalization": {
            "multiplier": 1.0,
            "clamp_min": 1.0,
            "clamp_max": 10.0,
            "bands": [
                {
                    "min": 0.0,
                    "max": 5.0,
                    "label": "Exploring",
                    "summary": "Early signal — try more scenarios.",
                    "suggested_levels": {skill_a: 3},
                    "next_actions": [],
                },
                {
                    "min": 5.0,
                    "max": 10.0,
                    "label": "Building",
                    "summary": "Solid foundation — deepen your practice.",
                    "suggested_levels": {skill_a: 6},
                    "next_actions": [],
                },
            ],
        },
    }


register_mock_fixture(AITaskType.TEMPLATE_DESIGN, _mock_template_content)


async def generate_template_draft(
    db: AsyncSession,
    user_id,
    *,
    brief: dict,
    skill_keys: list[str],
    extend_of: dict | None = None,
):
    """Draft (or extend) a full template from a brief; output validates
    like any write — the author reviews before publish (plan 37)."""
    from app.schemas.assessment_template import TemplateContent

    mode = "extend" if extend_of else "draft"
    return await ainvoke_structured(
        db,
        AITaskType.TEMPLATE_DESIGN,
        TemplateContent,
        system=(
            "You design career self-assessment templates as structured "
            "content. Use only the provided skill taxonomy keys in deltas. "
            "Options must be concrete and non-judgmental; keep the tone "
            f"{brief.get('tone') or 'encouraging'}. Produce a complete, "
            "runnable template."
            + (
                " You are EXTENDING an existing template — match its style "
                "and only add questions."
                if extend_of
                else ""
            )
        ),
        user=context_json(
            {
                "brief": brief,
                "skill_taxonomy": skill_keys,
                "mode": mode,
                "existing_template": extend_of or {},
            }
        ),
        user_id=user_id,
    )
