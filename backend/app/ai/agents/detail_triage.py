"""AI detail-fetch triage (the smart funnel's Layer 2): ranks candidate
postings by how worth-a-description-page they look, from list-card
metadata alone.

Deterministic Layer 1 (radar match + recency + salary) always runs and
is the fallback; this re-rank is optional and only ever called from the
background enrichment job — a missing or unconfigured provider returns
None and the caller keeps Layer 1's order. One structured call per
batch, never on the ingest hot path."""

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType

_SYSTEM = (
    "You triage job postings for a student's job radar. You see only the "
    "list-card metadata of each candidate (title, company, seniority, "
    "salary). Score each candidate 0.0-1.0 for how worth it is to fetch "
    "its full job-description page: 1.0 = clearly a real, relevant "
    "vacancy worth understanding deeply; 0.0 = junk, duplicate-looking, "
    "or clearly off-radar. Be decisive; do not explain."
)


class TriagePick(BaseModel):
    external_id: str = Field(min_length=1, max_length=300)
    worth: float = Field(ge=0.0, le=1.0)


class TriageRanking(BaseModel):
    picks: list[TriagePick] = Field(min_length=1, max_length=40)


def _mock_triage(_schema, user: str) -> dict:
    ids = [line.split(":", 1)[0].strip() for line in user.splitlines() if ":" in line]
    return {"picks": [{"external_id": value, "worth": 1.0} for value in ids[:1]]}


register_mock_fixture(AITaskType.DETAIL_TRIAGE, _mock_triage)


async def triage_candidates(
    db: AsyncSession, user_id, candidates: list[dict]
) -> dict[str, float] | None:
    """external_id → worth for one batch. None = AI unavailable; the
    caller keeps the deterministic order (never raises)."""
    if not candidates:
        return {}
    lines = [
        f"{c['external_id']}: {c['title']} @ {c['org'] or '-'} "
        f"({c.get('seniority') or '-'}, {c.get('salary') or '-'})"
        for c in candidates
    ]
    try:
        result = await ainvoke_structured(
            db,
            AITaskType.DETAIL_TRIAGE,
            TriageRanking,
            _SYSTEM,
            "\n".join(lines),
            user_id=user_id,
        )
    except Exception:
        return None
    picks = {pick.external_id: pick.worth for pick in result.picks}
    return picks or None
