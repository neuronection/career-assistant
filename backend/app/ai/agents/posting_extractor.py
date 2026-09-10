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
from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType


class ExtractSkill(BaseModel):
    """One skill requirement. `skill_key` resolvable against the provided
    taxonomy; otherwise `unresolved` with `raw_label`."""

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


class ExtractContract(BaseModel):
    """Employment contract detail — refines employment_type."""

    contract_type: Literal[
        "permanent",
        "temporary",
        "contract",
        "freelance",
        "b2b",
        "internship",
        "apprenticeship",
    ]
    evidence_quote: str = Field(min_length=3, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractHours(BaseModel):
    """Work-hours pattern with optional stated weekly range."""

    pattern: Literal["full_time", "part_time"]
    hours_per_week_min: Optional[int] = Field(default=None, ge=1, le=80)
    hours_per_week_max: Optional[int] = Field(default=None, ge=1, le=80)
    evidence_quote: str = Field(min_length=3, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractScheduleCue(BaseModel):
    """One schedule signal with its verbatim evidence."""

    cue: Literal["shift_work", "on_call", "nights", "weekends", "flexible"]
    evidence_quote: str = Field(min_length=3, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractTravel(BaseModel):
    """Travel demand; days_per_month only when stated."""

    level: Literal["none", "occasional", "frequent"]
    days_per_month: Optional[int] = Field(default=None, ge=0, le=31)
    evidence_quote: str = Field(min_length=3, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractOnsite(BaseModel):
    """Onsite refinement of remote_policy."""

    policy: Literal["onsite", "hybrid", "remote"]
    office_days_per_week: Optional[int] = Field(default=None, ge=0, le=7)
    evidence_quote: str = Field(min_length=3, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)


BENEFIT_KINDS = (
    "healthcare",
    "pension",
    "leave",
    "remote_budget",
    "learning",
    "equity",
    "meals",
    "transport",
    "other",
)


class ExtractBenefit(BaseModel):
    """Typed benefit: kind powers filters/values hints;
    `raw` preserves the original wording for audit."""

    kind: Literal[
        "healthcare",
        "pension",
        "leave",
        "remote_budget",
        "learning",
        "equity",
        "meals",
        "transport",
        "other",
    ]
    raw: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)

    @classmethod
    def coerce(cls, value) -> "ExtractBenefit":
        """extracts stored benefits as plain strings — coerce them
        honestly instead of failing old rows on read."""
        if isinstance(value, ExtractBenefit):
            return value
        if isinstance(value, str):
            return cls(kind="other", raw=value, confidence=0.5)
        return cls.model_validate(value)


class PostingExtract(BaseModel):
    """Schema contract for AITaskType.POSTING_EXTRACT."""

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
    benefits: list[ExtractBenefit] = Field(default_factory=list, max_length=20)
    responsibilities: list[ExtractResponsibility] = Field(
        default_factory=list, max_length=20
    )
    skills: list[ExtractSkill] = Field(default_factory=list, max_length=40)
    # ---- v2: optional-with-confidence + evidence, never guessed
    contract_type: Optional[ExtractContract] = None
    work_hours: Optional[ExtractHours] = None
    schedule_cues: list[ExtractScheduleCue] = Field(default_factory=list, max_length=6)
    travel_required: Optional[ExtractTravel] = None
    onsite_policy: Optional[ExtractOnsite] = None
    values_cues: list[str] = Field(default_factory=list, max_length=8)
    # Per-top-level-field confidence 0..1 — the caller drops fields below
    # its threshold and flags the posting for review instead of guessing.
    field_confidence: dict[str, float] = Field(default_factory=dict)

    @field_validator("benefits", mode="before")
    @classmethod
    def _coerce_legacy_benefits(cls, value):
        if isinstance(value, list):
            return [ExtractBenefit.coerce(item) for item in value]
        return value


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
        "benefits": _mock_benefits(lowered),
        "contract_type": _mock_contract(lowered),
        "work_hours": _mock_hours(lowered),
        "schedule_cues": _mock_schedule(lowered),
        "travel_required": _mock_travel(lowered),
        "onsite_policy": _mock_onsite(lowered),
        "field_confidence": {
            "title_norm": 0.9,
            "seniority": 0.9,
            "salary": 0.7,
            "responsibilities": 0.8,
            "skills": 0.9,
            "benefits": 0.7,
            "contract_type": 0.8,
            "work_hours": 0.8,
            "schedule_cues": 0.8,
            "travel_required": 0.8,
            "onsite_policy": 0.8,
        },
    }


def _quote(text: str, needle: str) -> str:
    return _quote_around(text, needle) if needle else "verbatim cue"


def _mock_benefits(lowered: str) -> list[dict]:
    cues = [
        ("health insurance", "healthcare"),
        ("pension", "pension"),
        ("annual leave", "leave"),
        ("remote budget", "remote_budget"),
        ("learning budget", "learning"),
        ("equity", "equity"),
        ("meals", "meals"),
        ("transport", "transport"),
    ]
    return [
        {"kind": kind, "raw": cue, "confidence": 0.8}
        for cue, kind in cues
        if cue in lowered
    ]


def _mock_contract(lowered: str) -> dict | None:
    for needle, kind in (
        ("b2b", "b2b"),
        ("freelance", "freelance"),
        ("fixed-term", "temporary"),
        ("apprenticeship", "apprenticeship"),
        ("internship", "internship"),
        ("permanent contract", "permanent"),
        ("contract position", "contract"),
    ):
        if needle in lowered:
            return {
                "contract_type": kind,
                "evidence_quote": _quote(lowered, needle),
                "confidence": 0.8,
            }
    return None


def _mock_hours(lowered: str) -> dict | None:
    pattern = (
        "part_time"
        if "part-time" in lowered
        else ("full_time" if "full-time" in lowered else None)
    )
    if pattern is None:
        return None
    return {
        "pattern": pattern,
        "hours_per_week_min": 20 if pattern == "part_time" else 35,
        "hours_per_week_max": 30 if pattern == "part_time" else 40,
        "evidence_quote": _quote(lowered, f"{pattern.replace('_', '-')}"),
        "confidence": 0.8,
    }


def _mock_schedule(lowered: str) -> list[dict]:
    cues = []
    for needle, cue in (
        ("shift", "shift_work"),
        ("on-call", "on_call"),
        ("on call", "on_call"),
        ("night", "nights"),
        ("weekend", "weekends"),
        ("flexible hours", "flexible"),
    ):
        if needle in lowered:
            cues.append(
                {
                    "cue": cue,
                    "evidence_quote": _quote(lowered, needle),
                    "confidence": 0.8,
                }
            )
    return cues[:6]


def _mock_travel(lowered: str) -> dict | None:
    if "travel" not in lowered:
        return None
    level = (
        "frequent"
        if ("frequent" in lowered or "extensive" in lowered)
        else ("none" if "no travel" in lowered else "occasional")
    )
    return {
        "level": level,
        "days_per_month": None,
        "evidence_quote": _quote(lowered, "travel"),
        "confidence": 0.8,
    }


def _mock_onsite(lowered: str) -> dict | None:
    if "days on-site" in lowered or "days onsite" in lowered:
        return {
            "policy": "hybrid",
            "office_days_per_week": 2,
            "evidence_quote": _quote(lowered, "days on"),
            "confidence": 0.8,
        }
    if "fully remote" in lowered:
        return {
            "policy": "remote",
            "office_days_per_week": 0,
            "evidence_quote": _quote(lowered, "fully remote"),
            "confidence": 0.8,
        }
    return None


register_mock_fixture(AITaskType.POSTING_EXTRACT, _mock_extract)


async def extract_posting(
    db: AsyncSession,
    user_id,
    title: str,
    description: str,
    skills_raw: list[str],
    skill_taxonomy_keys: list[str],
) -> PostingExtract:
    """Validated deep extract for one posting (caller applies + audits).

    The per-feature brief is GENERATED from the feature map (39.3) —
    schema and prompt cannot drift apart."""
    from app.services.feature_map import generated_feature_instructions

    return await ainvoke_structured(
        db,
        AITaskType.POSTING_EXTRACT,
        PostingExtract,
        system=(
            "You extract structured facts from job postings. Resolve every "
            "skill mention onto the provided taxonomy keys — when no key "
            "fits, return the skill as unresolved with its raw label. Facts "
            "that carry an evidence contract (skills, contract, hours, "
            "schedule, travel, onsite) need a verbatim evidence_quote from "
            "the text. Never guess: fields you cannot support get a "
            "field_confidence below 0.6 so the caller drops them."
        ),
        user=(
            generated_feature_instructions()
            + "\n\n"
            + context_json(
                {
                    "title": title,
                    "posting_text": description[:6000],
                    "skills_raw": skills_raw[:60],
                    "skill_taxonomy": skill_taxonomy_keys,
                }
            )
        ),
        user_id=user_id,
    )
