"""AI template advisor (AITaskType.CV_TEMPLATE_PICK, audited).

Ranks the deterministically-scored template candidates the service
submits — the AI may only reorder + explain, never add or substitute
templates. Candidates are stable ids (`t0`, `t1`, …) so validation
never depends on model output echoing UUIDs.
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType
from pydantic import BaseModel, Field


class TemplatePick(BaseModel):
    template_ref: str = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=200)


class TemplateRanking(BaseModel):
    ranking: list[TemplatePick] = Field(default_factory=list, max_length=10)


class TemplateCandidate(BaseModel):
    """One row of the service-built candidate list (refed + pre-scored)."""

    ref: str
    template_id: str
    title: str
    source: str
    language: str
    page_size: str
    ats_safe: bool
    layout: str
    score: float


def _mock_rank(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    refs = [candidate["ref"] for candidate in (ctx.get("candidates") or [])]
    query = str(ctx.get("target") or "").lower()
    ordered = [
        ref
        for ref in refs
        if any(word in query for word in ("sidebar", "ats-safe", "classic"))
    ]
    ordered += [ref for ref in refs if ref not in ordered]
    return {
        "ranking": [
            {"template_ref": ref, "reason": "Matches the request context"}
            for ref in ordered[:5]
        ]
    }


register_mock_fixture(AITaskType.CV_TEMPLATE_PICK, _mock_rank)


async def rank_templates(
    db: AsyncSession,
    user_id,
    candidates: list[TemplateCandidate],
    target: Optional[dict] = None,
) -> TemplateRanking:
    """Rank template refs best-first; output filtered to the allowlist."""
    refs = [candidate.ref for candidate in candidates]
    result = await ainvoke_structured(
        db,
        AITaskType.CV_TEMPLATE_PICK,
        TemplateRanking,
        system=(
            "You rank CV template candidates for a student's new CV. Each "
            "candidate arrives with deterministic signal scores; the "
            "signals are the baseline — reorder them only for qualities "
            "the scores cannot see, and give one short reason per pick. "
            "Return only template_ref values from the provided list, "
            "each at most once."
        ),
        user=context_json(
            {
                "candidates": [candidate.model_dump() for candidate in candidates],
                "target": target or {},
            }
        ),
        user_id=user_id,
    )
    known = set(refs)
    seen: set[str] = set()
    ranked: list[TemplatePick] = []
    for pick in result.ranking:
        ref = str(pick.template_ref)
        if ref not in known or ref in seen:
            continue
        seen.add(ref)
        ranked.append(pick)
    return TemplateRanking(ranking=ranked)
