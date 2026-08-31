"""AI posting extractor (Phase 31): one structured call per posting that
squeezes the raw text into auditable data — skills with required level
1–10 + priority + mandatory evidence quote, seniority, salary,
responsibilities with time splits. Every field is optional-with-confidence
(`field_confidence`); the caller suppresses low-confidence fields instead
of storing guesses. Unresolvable skills come back as `unresolved` rows
with the raw label — never dropped, never label-matched."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.provider import ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType


class ExtractSkill(BaseModel):
    """One skill requirement. `skill_key` resolvable against the provided
    taxonomy; otherwise `unresolved` with `raw_label` (plan-15 queue)."""

    skill_key: Optional[str] = None
    raw_label: Optional[str] = None
    unresolved: bool = False
    required_level: int = Field(ge=1, le=10)
    priority: Literal["must_have", "nice_to_have", "bonus"]
    evidence_quote: str = Field(min_length=3, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("raw_label")
    @classmethod
    def _label_when_unresolved(cls, value, info):
        if info.data.get("unresolved") and not value:
            raise ValueError("unresolved skills need a raw_label")
        return value


class ExtractResponsibility(BaseModel):
    text: str = Field(min_length=3, max_length=400)
    time_pct: Optional[int] = Field(default=None, ge=0, le=100)
    optional: bool = False


class ExtractSalary(BaseModel):
    min: Optional[float] = Field(default=None, ge=0)
    max: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    period: Optional[Literal["hour", "day", "week", "month", "year"]] = None


class ExtractLocation(BaseModel):
    city: Optional[str] = Field(default=None, max_length=120)
    country: Optional[str] = Field(default=None, max_length=120)


class ExtractEducation(BaseModel):
    level: Optional[str] = Field(default=None, max_length=40)
    field: Optional[str] = Field(default=None, max_length=120)


class PostingExtract(BaseModel):
    """Schema contract for AITaskType.POSTING_EXTRACT (plan 31)."""

    title_norm: Optional[str] = Field(default=None, max_length=300)
    seniority: Optional[
        Literal["intern", "junior", "mid", "senior", "lead", "principal"]
    ] = None
    employment_type: Optional[
        Literal["full_time", "part_time", "contract", "temporary", "internship"]
    ] = None
    remote_policy: Optional[Literal["onsite", "hybrid", "remote"]] = None
    location: Optional[ExtractLocation] = None
    salary: Optional[ExtractSalary] = None
    education: Optional[ExtractEducation] = None
    languages: list[str] = Field(default_factory=list, max_length=12)
    benefits: list[str] = Field(default_factory=list, max_length=20)
    responsibilities: list[ExtractResponsibility] = Field(
        default_factory=list, max_length=20
    )
    skills: list[ExtractSkill] = Field(default_factory=list, max_length=40)
    # Per-top-level-field confidence 0..1 — the caller drops fields below
    # its threshold and flags the posting for review instead of guessing.
    field_confidence: dict[str, float] = Field(default_factory=dict)


def _quote_around(text: str, needle: str) -> str:
    """A short verbatim window around `needle` — auditable evidence."""
    lowered = text.lower()
    idx = lowered.find(needle.lower())
    if idx == -1:
        return needle[:100]
    start = max(0, idx - 40)
    end = min(len(text), idx + len(needle) + 40)
    return " ".join(text[start:end].split())[:400]


def _mock_extract(schema: type, user_prompt: str) -> dict:
    """Deterministic deep extract from the prompt context: taxonomy keys
    found verbatim become resolved skills (level from seniority hints,
    priority by order); `skills_raw` entries outside the taxonomy come
    back unresolved. Other fields stay unset — the caller sees honestly
    what the mock can know."""
    ctx = parse_context(user_prompt)
    taxonomy = [str(k) for k in (ctx.get("skill_taxonomy") or [])]
    text = str(ctx.get("posting_text") or "")
    lowered = text.lower()
    title = str(ctx.get("title") or "").lower()

    if "senior" in title or "lead" in title:
        level = 6
    elif "junior" in title or "intern" in title:
        level = 2
    else:
        level = 4

    skills: list[dict] = []
    for pos, key in enumerate([k for k in taxonomy if k.lower() in lowered]):
        priority = (
            "must_have"
            if len(skills) < 2
            else "nice_to_have"
            if len(skills) < 4
            else "bonus"
        )
        skills.append(
            {
                "skill_key": key,
                "unresolved": False,
                "required_level": min(10, level + (1 if pos >= 4 else 0)),
                "priority": priority,
                "evidence_quote": _quote_around(text, key),
                "confidence": 0.9,
            }
        )
    for raw_label in ctx.get("skills_raw") or []:
        label = str(raw_label)
        if label.lower() in lowered and not any(
            label.lower() == str(s.get("skill_key", "")).lower() for s in skills
        ):
            if not any(
                str(s.get("raw_label", "")).lower() == label.lower() for s in skills
            ):
                skills.append(
                    {
                        "raw_label": label,
                        "unresolved": True,
                        "required_level": 3,
                        "priority": "nice_to_have",
                        "evidence_quote": _quote_around(text, label),
                        "confidence": 0.8,
                    }
                )
    return {
        "title_norm": (ctx.get("title") or None),
        "skills": skills[:40],
        "field_confidence": {
            "title_norm": 0.9,
            "seniority": 0.9,
            "salary": 0.7,
            "responsibilities": 0.8,
            "skills": 0.9,
        },
    }


register_mock_fixture(AITaskType.POSTING_EXTRACT, _mock_extract)


async def extract_posting(
    db: AsyncSession,
    user_id,
    title: str,
    description: str,
    skills_raw: list[str],
    skill_taxonomy_keys: list[str],
) -> PostingExtract:
    """Validated deep extract for one posting (caller applies + audits)."""
    return await ainvoke_structured(
        db,
        AITaskType.POSTING_EXTRACT,
        PostingExtract,
        system=(
            "You extract structured facts from job postings. Resolve every "
            "skill mention onto the provided taxonomy keys — when no key "
            "fits, return the skill as unresolved with its raw label. Every "
            "skill needs a verbatim evidence_quote from the text. Never "
            "guess: fields you cannot support get a field_confidence below "
            "0.6 so the caller drops them."
        ),
        user=context_json(
            {
                "title": title,
                "posting_text": description[:6000],
                "skills_raw": skills_raw[:60],
                "skill_taxonomy": skill_taxonomy_keys,
            }
        ),
        user_id=user_id,
    )
