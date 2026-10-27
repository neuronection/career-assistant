"""AI company triage (the gray band's arbiter, plan 135): decides whether
one ambiguous employer label names one existing organization.

The deterministic matcher (quality gate → exclusions → exact keys →
initials guard → blocked fuzzy) always runs and is the fallback; this
arbiter is only called from the background ``company_triage`` job, one
structured call per ≤40 pairs, and never on the ingest hot path. An
unconfigured provider returns None and the caller records suggestions
instead (family AI-with-fallback law). Verdicts persist on the pair rows
(paid once) — the same pair is never re-asked.
"""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.core.errors import AINotConfiguredError
from app.models.enums import AITaskType

_SYSTEM = (
    "You are an entity-resolution arbiter for a job board. Each line "
    "describes one candidate pair: an employer label as written in a "
    "posting (with its URL signals) and one existing company (name, known "
    "aliases, domain, city). Decide whether the label names that same "
    "company: 'same' when it is a genuine variant (initialism, trade "
    "name, suffix form, abbreviation), 'different' when it is another "
    "employer (similar wording is not evidence), 'uncertain' when the "
    "evidence does not settle it. Give confidence 0.0-1.0 and the "
    "canonical company name when verdict is 'same'. Answer every pair."
)


class PairVerdict(BaseModel):
    pair_id: str = Field(min_length=1, max_length=64)
    verdict: Literal["same", "different", "uncertain"]
    confidence: float = Field(ge=0.0, le=1.0)
    canonical_name: str | None = Field(default=None, max_length=200)


class PairVerdictSet(BaseModel):
    verdicts: list[PairVerdict] = Field(min_length=1, max_length=40)


def _mock_triage(_schema, user: str) -> dict:
    ids = [
        line.split(":", 1)[0].strip()
        for line in user.splitlines()
        if line.strip().startswith("pair-") and ":" in line
    ]
    return {
        "verdicts": [
            {"pair_id": pair_id, "verdict": "uncertain", "confidence": 0.5} for pair_id in ids
        ]
    }


register_mock_fixture(AITaskType.COMPANY_TRIAGE, _mock_triage)


def pair_line(pair: dict) -> str:
    """One prompt line per pair (the mock parses the ``pair-`` prefix)."""
    aliases = ", ".join(pair.get("aliases") or []) or "-"
    label = str(pair.get("label") or "")[:200]
    name = str(pair.get("candidate_name") or "")[:200]
    domain = str(pair.get("domain") or "-")[:120]
    url_hint = str(pair.get("url_hint") or "-")[:160]
    city = str(pair.get("city") or "-")[:80]
    return (
        f"{pair['pair_id']}: label={label!r} (url={url_hint}, domain={domain}) "
        f"| existing={name!r} (aliases=[{aliases}], domain={domain}, city={city})"
    )


async def triage_pairs(db: AsyncSession, pairs: list[dict]) -> list[PairVerdict] | None:
    """Verdicts for one batch. None = AI unconfigured (suggestions take
    over); transient failures raise so the job retries with pairs intact."""
    if not pairs:
        return []
    try:
        result = await ainvoke_structured(
            db,
            AITaskType.COMPANY_TRIAGE,
            PairVerdictSet,
            _SYSTEM,
            "\n".join(pair_line(pair) for pair in pairs),
        )
    except AINotConfiguredError:
        return None
    return result.verdicts
