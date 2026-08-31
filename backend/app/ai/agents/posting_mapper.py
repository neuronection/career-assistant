"""AI posting mapper: extracts taxonomy skill keys from posting text
(AITaskType.POSTING_MAP, audited). Keyword/alias matching runs first in
core; this pass covers the remainder. Unknown keys are dropped by the
caller (plan-21 discipline — never hard-fail, never label-match)."""

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.provider import ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType


class PostingSkillExtract(BaseModel):
    skill_keys: list[str] = Field(default_factory=list, max_length=40)


def _mock_extract(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    taxonomy = ctx.get("skill_taxonomy") or []
    text = str(ctx.get("posting_text") or "").lower()
    hits = [key for key in taxonomy if key.lower() in text]
    return {"skill_keys": hits[:10]}


register_mock_fixture(AITaskType.POSTING_MAP, _mock_extract)


async def extract_skill_keys(
    db: AsyncSession,
    user_id,
    title: str,
    description: str,
    skill_taxonomy_keys: list[str],
) -> list[str]:
    """Validated skill keys for one posting (caller resolves to FK ids)."""
    result = await ainvoke_structured(
        db,
        AITaskType.POSTING_MAP,
        PostingSkillExtract,
        system=(
            "You map job posting text onto a fixed skill taxonomy. Return "
            "only keys that appear verbatim in the provided taxonomy list. "
            "Return an empty list when nothing matches — never invent keys."
        ),
        user=context_json(
            {
                "title": title,
                "posting_text": description[:4000],
                "skill_taxonomy": skill_taxonomy_keys,
            }
        ),
        user_id=user_id,
    )
    known = {k.lower() for k in skill_taxonomy_keys}
    return [key for key in result.skill_keys if key.lower() in known]
