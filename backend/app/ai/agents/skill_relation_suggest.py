"""LLM verdicts over skill-relation candidates (plan 138, step 5).

One batched structured call per batch of candidate pairs: the model says
which typed relation (if any) holds between the two skills of each pair,
grounded on the deterministic evidence the candidate pass collected. The
offline teacher of the taxonomy — never on a query path. Unconfigured or
failing AI surfaces as ``None``/``AINotConfiguredError`` and the caller
falls back to deterministic derived proposals.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import RunRef, ainvoke_structured, register_mock_fixture
from app.core.errors import AINotConfiguredError
from app.models.enums import AITaskType, SkillRelationType

MAX_PAIRS_PER_CALL = 40

VerdictRelation = SkillRelationType | Literal["none"]

_SYSTEM = (
    "You are the offline teacher of a skill taxonomy on a student career "
    "platform. You receive pairs of catalog skills with the deterministic "
    "evidence that made them candidates. Decide which typed relation, if "
    "any, holds between the two skills of each pair; answer for EVERY pair "
    "exactly once.\n"
    "Relations (closed vocabulary):\n"
    "- is_a: the subject_key skill is a KIND OF the other (java is_a "
    "programming). subject_key names the MORE SPECIFIC skill.\n"
    "- part_of: the subject_key skill is a COMPONENT OF the other "
    "(subject_key is the component).\n"
    "- synonym: the two names denote the SAME skill (machine-learning / ml).\n"
    "- related_to: they are meaningfully related but neither is a kind nor a "
    "component of the other (typescript related_to javascript).\n"
    "- none: no relation above holds.\n"
    "Hard rules (the traps this corpus exists for):\n"
    "- Co-occurrence in job postings is NOT a relation: c# and java appear "
    "together constantly and are none. Competitor tools (react / angular) "
    "are related_to at most, never is_a. Near-name pairs (c / c++) are "
    "related_to at most, never synonym.\n"
    "- Distinct skills that merely overlap in meaning (problem-solving / "
    "critical-thinking) must not merge: related_to at most.\n"
    "- A specific skill never generalizes its own general; watch direction.\n"
    "- Unsure between two relations: pick the weaker one. Unsure whether any "
    "relation holds: answer none with low confidence.\n"
    "Each verdict: pair_ref copied exactly, relation, subject_key (only for "
    "is_a and part_of; copy one of the pair's keys exactly), confidence "
    "0.0-1.0, rationale one sentence (max 500 chars)."
)


class SkillEdgeVerdict(BaseModel):
    """The model's answer for one candidate pair."""

    pair_ref: str = Field(min_length=1, max_length=40)
    relation: VerdictRelation
    subject_key: str = Field(default="", max_length=80)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=500)


class SkillEdgeVerdictSet(BaseModel):
    """Bounded verdict list — one entry per pair in the batch."""

    verdicts: list[SkillEdgeVerdict] = Field(max_length=MAX_PAIRS_PER_CALL)


def _mock_skill_edge_verdicts(_schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    verdicts = []
    for pair in ctx.get("pairs", []):
        skills = pair.get("skills") or []
        hypothesis = str(pair.get("hypothesis") or SkillRelationType.RELATED_TO.value)
        directed = hypothesis in (
            SkillRelationType.IS_A.value,
            SkillRelationType.PART_OF.value,
        )
        verdicts.append(
            {
                "pair_ref": pair.get("pair_ref", ""),
                "relation": hypothesis,
                "subject_key": (skills[0].get("key", "") if directed and skills else ""),
                "confidence": 0.9,
                "rationale": "Deterministic mock verdict confirming the candidate hypothesis.",
            }
        )
    return {"verdicts": verdicts}


register_mock_fixture(AITaskType.SKILL_RELATION_SUGGEST, _mock_skill_edge_verdicts)


def build_pair_prompt(pairs: list[dict]) -> str:
    """Serialize one batch of candidate pair contexts for the model."""
    return context_json({"pairs": pairs})


async def suggest_skill_edges(
    db: AsyncSession,
    pairs: list[dict],
    *,
    user_id=None,
    run: RunRef | None = None,
) -> SkillEdgeVerdictSet | None:
    """Verdicts for one batch of pair contexts. ``None`` = AI failed.

    Raises:
        AINotConfiguredError: when no provider is configured — the caller
            falls back to deterministic derived proposals for the run.
    """
    if not pairs:
        return SkillEdgeVerdictSet(verdicts=[])
    try:
        return await ainvoke_structured(
            db,
            AITaskType.SKILL_RELATION_SUGGEST,
            SkillEdgeVerdictSet,
            _SYSTEM,
            build_pair_prompt(pairs),
            user_id=user_id,
            run=run,
        )
    except AINotConfiguredError:
        raise
    except Exception:
        return None
