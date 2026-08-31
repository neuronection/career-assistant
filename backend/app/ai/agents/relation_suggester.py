from pydantic import BaseModel, Field

from app.models.enums import AITaskType
from app.ai.agents.context import context_json, parse_context
from app.ai.provider import ainvoke_structured, register_mock_fixture
from app.ai.schemas import RelationSuggestion
from sqlalchemy.ext.asyncio import AsyncSession


class RelationSuggestionSet(BaseModel):
    """Wrapper schema so the model returns a bounded list of edges."""

    suggestions: list[RelationSuggestion] = Field(default_factory=list, max_length=60)


def _build_user_prompt(jobs: list[dict], max_suggestions: int) -> str:
    data = {"jobs": jobs, "max_suggestions": max_suggestions}
    return context_json(data)


def _mock_suggestion_set(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    jobs = ctx.get("jobs", [])
    suggestions = []
    for i in range(len(jobs) - 1):
        suggestions.append(
            {
                "from_code": jobs[i]["code"],
                "to_code": jobs[i + 1]["code"],
                "relation_type": "similar_to",
                "weight": 0.5,
                "rationale": "Adjacent roles sharing core skills.",
                "confidence": 0.6,
            }
        )
    return {"suggestions": suggestions[: max(1, ctx.get("max_suggestions", 10))]}


register_mock_fixture(AITaskType.RELATION_SUGGEST, _mock_suggestion_set)


async def suggest_relations(
    db: AsyncSession,
    user_id,
    jobs: list[dict],
    max_suggestions: int = 10,
) -> list[RelationSuggestion]:
    """Propose typed relations among the given jobs (code/title/family dicts)."""
    result: RelationSuggestionSet = await ainvoke_structured(
        db,
        AITaskType.RELATION_SUGGEST,
        RelationSuggestionSet,
        system="Suggest useful typed relations between the given jobs.",
        user=_build_user_prompt(jobs, max_suggestions),
        user_id=user_id,
    )
    codes = {j["code"] for j in jobs}
    return [
        s
        for s in result.suggestions[:max_suggestions]
        if s.from_code in codes and s.to_code in codes and s.from_code != s.to_code
    ]
