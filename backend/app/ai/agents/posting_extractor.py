"""AI posting extractor (Phase 31): one structured call per posting that
squeezes the raw text into auditable data — skills with required level
1-10 + priority + mandatory evidence quote, seniority, salary,
responsibilities with time splits. Every field is optional-with-confidence
(`field_confidence`); the caller suppresses low-confidence fields instead
of storing guesses. Pass 1 is taxonomy-blind (plan 153): skills come back
as verbatim `raw_label` rows — no resolution, no key anchoring; the
deterministic matcher + pass-2 resolver own resolution."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import RunRef, ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType


class ExtractSkill(BaseModel):
    """One skill requirement, verbatim. Pass 1 is taxonomy-blind:
    `raw_label` copies the posting's own wording; resolution happens in
    pass 2 (plan 153) — the model never answers keys."""

    raw_label: str = Field(min_length=1, max_length=200)
    required_level: int = Field(ge=1, le=10)
    priority: Literal["must_have", "nice_to_have", "bonus"]
    evidence_quote: str = Field(min_length=3, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractResponsibility(BaseModel):
    text: str = Field(min_length=3, max_length=400)
    time_pct: int | None = Field(default=None, ge=0, le=100)
    optional: bool = False


class ExtractSalary(BaseModel):
    min: float | None = Field(default=None, ge=0)
    max: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    period: Literal["hour", "day", "week", "month", "year"] | None = None
    basis: Literal["gross", "net"] | None = None


class ExtractPrerequisite(BaseModel):
    """One stated requirement outside the skill/salary axes: a degree,
    certificate, license, language or other gate — with its verbatim
    evidence. Degrees ALSO stay in `education` (the level comparison);
    this row carries the wording."""

    kind: Literal["degree", "certificate", "license", "language", "other"]
    label: str = Field(min_length=2, max_length=200)
    evidence_quote: str = Field(min_length=3, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractLocation(BaseModel):
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)


_EDUCATION_LEVEL_MAP: dict[str, str] = {
    "no_formal": "no_formal",
    "middle_school": "middle_school",
    "high_school": "high_school",
    "vocational": "vocational",
    "bachelor": "bachelor",
    "master": "master",
    "doctorate": "doctorate",
    "degree": "bachelor",
    "bachelors": "bachelor",
    "bachelor's": "bachelor",
    "bsc": "bachelor",
    "bs": "bachelor",
    "masters": "master",
    "master's": "master",
    "msc": "master",
    "ms": "master",
    "phd": "doctorate",
    "doctoral": "doctorate",
    "high school": "high_school",
    "high school diploma": "high_school",
    "secondary school": "high_school",
    "apprenticeship": "vocational",
    "no formal": "no_formal",
}


class ExtractEducation(BaseModel):
    """`level` coerces onto the EducationLevel taxonomy — job ads write
    "degree", "MSc", "high school diploma"; anything unmappable drops to
    None (the fit service scores unknown levels neutral) instead of
    leaking a free-form string into consumers."""

    level: (
        Literal[
            "no_formal",
            "middle_school",
            "high_school",
            "vocational",
            "bachelor",
            "master",
            "doctorate",
        ]
        | None
    ) = None
    field: str | None = Field(default=None, max_length=120)

    @field_validator("level", mode="before")
    @classmethod
    def _coerce_level(cls, value):
        if value is None:
            return None
        key = str(value).strip().lower()
        return _EDUCATION_LEVEL_MAP.get(key)


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
    hours_per_week_min: int | None = Field(default=None, ge=1, le=80)
    hours_per_week_max: int | None = Field(default=None, ge=1, le=80)
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
    days_per_month: int | None = Field(default=None, ge=0, le=31)
    evidence_quote: str = Field(min_length=3, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractOnsite(BaseModel):
    """Onsite refinement of remote_policy."""

    policy: Literal["onsite", "hybrid", "remote"]
    office_days_per_week: int | None = Field(default=None, ge=0, le=7)
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

    title_norm: str | None = Field(default=None, max_length=300)
    # The role description with board chrome removed (premium upsells,
    # applicant counts, recruiter/company blocks, job alerts) — what the
    # user reads as "About this role". None when the text is too noisy
    # to distill confidently. Native to the posting's language (the
    # student surface reads it).
    description_clean: str | None = Field(default=None, max_length=8000)
    # The role distilled to 2-3 self-contained sentences in the catalog's
    # canonical language (the instance default locale) — the standardized
    # surface the catalog job proposal shows. Optional: older extracts and
    # too-noisy texts leave it out; consumers fall back to
    # description_clean.
    catalog_summary: str | None = Field(default=None, max_length=1200)
    seniority: Literal["intern", "junior", "mid", "senior", "lead", "principal"] | None = None
    employment_type: (
        Literal["full_time", "part_time", "contract", "temporary", "internship"] | None
    ) = None
    remote_policy: Literal["onsite", "hybrid", "remote"] | None = None
    location: ExtractLocation | None = None
    salary: ExtractSalary | None = None
    education: ExtractEducation | None = None
    languages: list[str] = Field(default_factory=list, max_length=12)
    prerequisites: list[ExtractPrerequisite] = Field(default_factory=list, max_length=12)
    benefits: list[ExtractBenefit] = Field(default_factory=list, max_length=20)
    responsibilities: list[ExtractResponsibility] = Field(default_factory=list, max_length=20)
    skills: list[ExtractSkill] = Field(default_factory=list, max_length=40)
    # ---- v2: optional-with-confidence + evidence, never guessed
    contract_type: ExtractContract | None = None
    work_hours: ExtractHours | None = None
    schedule_cues: list[ExtractScheduleCue] = Field(default_factory=list, max_length=6)
    travel_required: ExtractTravel | None = None
    onsite_policy: ExtractOnsite | None = None
    values_cues: list[str] = Field(default_factory=list, max_length=8)
    # Per-top-level-field confidence 0..1 — the caller drops fields below
    # its threshold and flags the posting for review instead of guessing.
    field_confidence: dict[str, float] = Field(default_factory=dict)

    @field_validator(
        "languages",
        "prerequisites",
        "responsibilities",
        "skills",
        "schedule_cues",
        "values_cues",
        mode="before",
    )
    @classmethod
    def _coerce_lists(cls, value):
        return [] if value is None else value

    @field_validator("benefits", mode="before")
    @classmethod
    def _coerce_legacy_benefits(cls, value):
        if value is None:
            return []
        if isinstance(value, list):
            return [ExtractBenefit.coerce(item) for item in value]
        return value

    @field_validator("field_confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value):
        return {} if value is None else value


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
    """Deterministic deep extract from the prompt context: every
    `skills_raw` mention present in the text becomes a verbatim
    `raw_label` row (pass 1 is taxonomy-blind — no keys are echoed).
    Level comes from seniority hints, priority by order; other fields
    stay unset — the caller sees honestly what the mock can know."""
    ctx = parse_context(user_prompt)
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
    for raw_label in ctx.get("skills_raw") or []:
        label = str(raw_label)
        normalized = label.lower()
        if (
            not normalized
            or normalized not in lowered
            or any(str(s.get("raw_label", "")).lower() == normalized for s in skills)
        ):
            continue
        priority = (
            "must_have" if len(skills) < 2 else "nice_to_have" if len(skills) < 4 else "bonus"
        )
        skills.append(
            {
                "raw_label": label,
                "required_level": min(10, level + (1 if len(skills) >= 4 else 0)),
                "priority": priority,
                "evidence_quote": _quote_around(text, label),
                "confidence": 0.9,
            }
        )
    return {
        "title_norm": (ctx.get("title") or None),
        "description_clean": text[:2000] if text.strip() else None,
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
    return [{"kind": kind, "raw": cue, "confidence": 0.8} for cue, kind in cues if cue in lowered]


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
        "part_time" if "part-time" in lowered else ("full_time" if "full-time" in lowered else None)
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
    *,
    run: "RunRef | None" = None,
) -> "tuple[PostingExtract, dict]":
    """Validated deep extract for one posting (caller applies + audits).

    Pass 1 of the two-pass pipeline (plan 153): the context carries NO
    taxonomy — labels are extracted verbatim and resolved later by the
    deterministic matcher + pass-2 resolver, so the call's token spend
    never scales with the active catalog. The per-feature brief is
    GENERATED from the feature map (39.3) — schema and prompt cannot
    drift apart. ``run`` (a gateway ``RunRef``) pins the audit row to the
    background job the call served (``ai_generations.run_id``, the
    amendment-5 identity); the audit summary comes back alongside the
    result so the journal (plan 142) can link the generation id."""
    from app.services.feature_map import generated_feature_instructions
    from app.services.locale_service import instance_default_locale

    # The catalog-side summary standardizes into the instance's canonical
    # language (the admin's default-locale setting; English when unset).
    locale = await instance_default_locale(db)
    language_name = {"en": "English", "de": "German", "el": "Greek"}.get(locale, "English")

    return await ainvoke_structured(
        db,
        AITaskType.POSTING_EXTRACT,
        PostingExtract,
        system=(
        system=(
            "You extract structured facts from job postings verbatim. For "
            "skills, extract what the posting says: copy every skill "
            "mention into `raw_label` EXACTLY as written (case, spelling, "
            "punctuation) — never map, expand or translate labels onto "
            "any taxonomy, and never answer with a key or id; a later "
            "pass resolves the labels. Facts that carry an evidence "
            "contract (skills, prerequisites, contract, hours, schedule, "
            "travel, onsite) need a verbatim evidence_quote from the "
            "text. Never guess: fields you cannot support get a "
            "field_confidence below 0.6 so the caller drops them.\n\n"
            '`title_norm` is the BARE role title: no "Job Title:" chrome, '
            "no seniority or level qualifiers (those belong in "
            "`seniority`), no location, no company name.\n\n"
            "Also write `description_clean`: the role description with all "
            "job-board chrome removed — premium upsells, applicant counts, "
            "recruiter contact blocks, company marketing, job alerts, "
            '"see how you compare" — and no section scaffolding ("Job '
            'Title:", "Job Location:", "Job Description:", "Main '
            'Responsibilities:", location/visa/apply blocks). Keep ONLY '
            "what describes the role itself (position, responsibilities, "
            "requirements, stack, benefits). Preserve the text's original "
            "language and its structure as plain paragraphs and bullets. "
            "Leave it null when the text is too noisy to distill "
            "confidently.\n\n"
            "Also write `catalog_summary`: the role distilled to 2-3 "
            "self-contained sentences of plain prose — the same content "
            f"as description_clean, written in {language_name}, with no "
            "headers, lists or formatting. It standardizes the "
            "catalog-side surface across postings of any language. Leave "
            "it null when you cannot distill confidently."
        ),
        user=(
            generated_feature_instructions()
            + "\n\n"
            + context_json(
                {
                    "title": title,
                    "posting_text": description[:24000],
                    "skills_raw": skills_raw[:60],
                }
            )
        ),
        user_id=user_id,
        run=run,
        with_audit_ref=True,
    )
