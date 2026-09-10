"""Deterministic, multi-dimensional fit scoring (Phase 22).

Pure functions over structured data — no DB, no LLM. Every formula is
documented next to its dimension and tested in
`tests/test_fit_engine.py`. Hard fairness rules:

1. No popularity/impression/family-size term anywhere.
2. Demand is never a default multiplier.
3. Unknown user dimension ⇒ neutral score + weight redistribution,
   never zeroing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Bump when any formula changes ⇒ stored fits become stale (refit on demand).
# 2: experience dimension scores per-skill derived evidence months.
# 3: interests blends RIASEC affinity vectors; salary gate added.
# 4: values dimension joins the engine.
# 5: benefit kinds feed the values signal.
FIT_VERSION = 5

# Neutral score for "no signal on either side" — never 0, never 10.
NEUTRAL = 7.0

# Importance → weight used by the skills dimension.
IMPORTANCE_WEIGHT = {"core": 3.0, "important": 2.0, "bonus": 1.0}

# Education levels → typical years of study (for the max_education_years gate).
EDUCATION_YEARS = {
    "no_formal": 0,
    "middle_school": 0,
    "high_school": 0,
    "vocational": 2,
    "bachelor": 4,
    "master": 6,
    "doctorate": 9,
}

# Evidence weight per experience kind (projects count fractionally).
EXPERIENCE_KIND_WEIGHT = {
    "internship": 0.75,
    "part_time": 0.6,
    "freelance": 0.75,
    "volunteer": 0.5,
    "project": 0.4,
}

# Work-style sliders compared 1–5; max mean distance is 4.
WORK_STYLE_KEYS = (
    "teamwork",
    "environment",
    "structure",
    "pace",
    "leadership",
)

# Interests blend: overlap + RIASEC affinity + work-style.
INTEREST_OVERLAP_WEIGHT = 0.4
INTEREST_AFFINITY_WEIGHT = 0.4
INTEREST_STYLE_WEIGHT = 0.2

DEFAULT_WEIGHTS = {
    "skills": 3,
    "location": 3,
    "experience": 3,
    "education": 3,
    "interests": 3,
    "values": 3,
}

# Per-dimension confidence (user slider × confidence = effective weight).
# All 1.0 today; the hook exists for future registry-driven confidence.
DIMENSION_CONFIDENCE = {k: 1.0 for k in DEFAULT_WEIGHTS}

DIMENSIONS = tuple(DEFAULT_WEIGHTS)

FIT_DIMENSION_LABELS = {
    "skills": "Skills",
    "location": "Location",
    "experience": "Experience",
    "education": "Education",
    "interests": "Interests",
    "values": "Values",
}


def fit_dimension_spec() -> list[dict]:
    """The fit engine's dimension list as one code-referenced spec
    : key, label and default weight — consumed by the metrics
    API and the settings UI, never re-hardcoded per call site."""
    return [
        {
            "engine": "fit",
            "key": key,
            "label": FIT_DIMENSION_LABELS[key],
            "default_weight": DEFAULT_WEIGHTS[key],
        }
        for key in DIMENSIONS
    ]


@dataclass
class FitResult:
    """Score + per-dimension breakdown for one user×job pair."""

    score: float
    breakdown: dict
    gates: list[str] = field(default_factory=list)
    specialist_dimension: str | None = None


def skills_dimension(
    required: list[dict], user_levels: dict[str, int]
) -> tuple[float, str]:
    """Importance-weighted coverage over `job_skills`.

    Per skill: `min(user, required) / required` — surplus never inflates.
    A skill the user hasn't claimed scores 0 for itself but its importance
    weight redistributes to the known skills (no blanket zero). A missing
    or fully-unmet **core** skill caps the dimension (4.0 when completely
    unmet, 6.0 when partially met). No requirements ⇒ neutral.
    """
    if not required:
        return NEUTRAL, "no skill requirements listed"
    known = [s for s in required if s["skill_id"] in user_levels]
    if not user_levels:
        return NEUTRAL, "you haven't rated any skills yet — no signal"
    total_weight = 0.0
    covered = 0.0
    core_unmet = 0
    core_partial = 0
    for s in required:
        weight = IMPORTANCE_WEIGHT.get(s["importance"], 1.0)
        total_weight += weight
        level = user_levels.get(s["skill_id"])
        if level is None:
            if s["importance"] == "core":
                core_unmet += 1
            continue
        ratio = min(level, s["required_level"]) / max(1, s["required_level"])
        covered += weight * ratio
        if s["importance"] == "core":
            if ratio <= 0:
                core_unmet += 1
            elif ratio < 1:
                core_partial += 1
    if total_weight <= 0:
        return NEUTRAL, "no weighted skill requirements"
    score = 10.0 * covered / total_weight
    if core_unmet:
        score = min(score, 4.0)
    elif core_partial:
        score = min(score, 6.0)
    detail = f"{len(known)}/{len(required)} required skills covered"
    if core_unmet:
        detail += f" · {core_unmet} core skill(s) missing"
    return round(score, 2), detail


def education_dimension(
    required_level: str | None, user_level: str | None
) -> tuple[float, str]:
    """EducationLevelOrder gap: meets → 10, one short (in progress) → 6.

    Students are the audience — being one level short is the *expected*
    state and scores as "on the way", not as a failure.
    """
    order = {
        "no_formal": 0,
        "middle_school": 1,
        "high_school": 2,
        "vocational": 3,
        "bachelor": 4,
        "master": 5,
        "doctorate": 6,
    }
    req = order.get(required_level or "", 2)
    usr = order.get(user_level or "", 2)
    gap = req - usr
    if gap <= 0:
        return 10.0, "meets or exceeds the education requirement"
    if gap == 1:
        return 6.0, "one level short — typically in progress for students"
    if gap == 2:
        return 3.0, "two levels short of the typical requirement"
    return 1.0, f"{gap} levels short of the typical requirement"


def experience_dimension(
    band: tuple[float, float] | None,
    required: list[dict],
    skill_months: dict[str, float],
) -> tuple[float, str, bool]:
    """Per-skill evidence months vs the job's required skills.

    Relevance of a required skill = min(1, derived months / target), where
    target = the band's low end in months (min 12). Months are kind/role/
    hours/recency weighted with overlap dedup (experience_derivation), so
    primary use counts most. No band, no evidence, or evidence that matches
    none of the required skills ⇒ neutral (fairness rule 3) — experience is
    never punished for being absent from a student profile.
    Third element: True when the dimension has real signal.
    """
    if band is None:
        return NEUTRAL, "no typical-experience band on this job", False
    low, _high = band
    target_months = max(12.0, 12.0 * float(low))
    if not required:
        return NEUTRAL, "no skill requirements to match evidence against", False
    total_weight = 0.0
    covered = 0.0
    matched = 0
    for s in required:
        weight = IMPORTANCE_WEIGHT.get(s["importance"], 1.0)
        total_weight += weight
        months = float(skill_months.get(s["skill_id"]) or 0.0)
        if months <= 0:
            continue
        matched += 1
        covered += weight * min(1.0, months / target_months)
    if matched == 0:
        return (
            NEUTRAL,
            "experience recorded but none matches this job's skills — no signal",
            False,
        )
    score = 10.0 * covered / total_weight if total_weight > 0 else NEUTRAL
    return (
        round(score, 2),
        (
            f"{matched}/{len(required)} required skills have evidence "
            f"(target ~{target_months / 12:.0f}y relevant use)"
        ),
        True,
    )


def location_dimension(
    *,
    job_city: str | None,
    job_country: str | None,
    job_remote: bool,
    user_city: str | None,
    user_country: str | None,
    remote_ok: bool,
    willing_to_relocate: bool,
) -> tuple[float, str, bool]:
    """Same city 10 · same country 7 · relocation-willing 8 · remote fit
    10/misaligned 4. Unknown job location ⇒ neutral (weight redistributes
    via the engine's neutral handling). Third element: False when the
    dimension has no signal and its weight should redistribute.
    """
    if job_remote:
        if remote_ok:
            return 10.0, "remote-friendly job and you're open to remote", True
        return 4.0, "remote job but you prefer on-site work", True
    if not job_city and not job_country:
        return NEUTRAL, "job location unknown", False
    if user_city and job_city and user_city.strip().lower() == job_city.strip().lower():
        return 10.0, f"same city ({job_city})", True
    if (
        user_country
        and job_country
        and user_country.strip().lower() == job_country.strip().lower()
    ):
        if willing_to_relocate:
            return 8.0, f"same country ({job_country}), relocation is an option", True
        return 7.0, f"same country ({job_country})", True
    if willing_to_relocate:
        return 8.0, "different location but you're willing to relocate", True
    return 2.0, "different location and no relocation willingness", True


def interests_dimension(
    *,
    job_interest_ids: set[str],
    user_interest_ids: set[str],
    user_work_style: dict | None,
    job_work_style: dict | None,
    user_riasec: dict[str, float] | None = None,
    job_riasec_letters: set[str] | None = None,
) -> tuple[float, str, bool]:
    """Interest signal: tag overlap (40%) + RIASEC
    affinity (40%) + work-style distance (20%), renormalized over the
    parts that actually have signal.

    Overlap = |shared| / |job interests|. Affinity = mean of the user's
    RIASEC values across the letters the job signals (both sides derive
    from interest-tag categories — the job's letter set is its tags'
    categories mapped through the registry). Work-style distance = mean
    absolute difference over the five 1–5 sliders → `10 − 2.5·distance`.
    A part with no signal on either side drops out; no parts ⇒ neutral.
    """
    interest_part: float | None = None
    if job_interest_ids and user_interest_ids:
        overlap = len(job_interest_ids & user_interest_ids) / len(job_interest_ids)
        interest_part = 10.0 * overlap
    affinity_part: float | None = None
    riasec = user_riasec or {}
    shared_letters = sorted(
        letter for letter in (job_riasec_letters or set()) if letter in riasec
    )
    if shared_letters:
        affinity_part = sum(riasec[letter] for letter in shared_letters) / len(
            shared_letters
        )
    style_part: float | None = None
    if user_work_style and job_work_style:
        deltas = [
            abs(float(user_work_style.get(k, 3)) - float(job_work_style.get(k, 3)))
            for k in WORK_STYLE_KEYS
        ]
        distance = sum(deltas) / len(deltas)
        style_part = max(0.0, 10.0 - 2.5 * distance)
    weighted = [
        (weight, part)
        for weight, part in (
            (INTEREST_OVERLAP_WEIGHT, interest_part),
            (INTEREST_AFFINITY_WEIGHT, affinity_part),
            (INTEREST_STYLE_WEIGHT, style_part),
        )
        if part is not None
    ]
    if not weighted:
        return NEUTRAL, "no interest or work-style signal", False
    total_weight = sum(weight for weight, _ in weighted)
    score = sum(weight * part for weight, part in weighted) / total_weight
    bits = []
    if interest_part is not None:
        bits.append("interest overlap")
    if affinity_part is not None:
        bits.append("interest affinity")
    if style_part is not None:
        bits.append("work-style fit")
    return round(score, 2), " + ".join(bits), True


def job_values_signal(attrs: dict) -> dict[str, float]:
    """Derive the job-side work-values signal from structured attributes
    . Deterministic, honest: only values with a real input are
    emitted — prestige is never fabricated, missing data never scores.

    Rules (catalog attributes only):
    - autonomy: inverse of the work-style `structure` slider (1→10, 5→2).
    - security: demand outlook (declining 2, stable 6, growing 8, hot 10).
    - compensation: median salary midpoint in bands (fallback: entry).
    - variety: environment breadth, +1 when the pace is high.
    - work_life_balance: inverse of the `pace` slider (1→10, 5→2).
    - altruism: people-serving environments (clinic/classroom) → 7.
    """
    work_style = attrs.get("work_style") or {}
    environments = [str(env) for env in attrs.get("environments") or []]
    signal: dict[str, float] = {}
    if work_style.get("structure"):
        signal["values.autonomy"] = float(12 - 2 * int(work_style["structure"]))
    outlook = str((attrs.get("demand") or {}).get("outlook") or "")
    if outlook in ("declining", "stable", "growing", "hot"):
        signal["values.security"] = {
            "declining": 2.0,
            "stable": 6.0,
            "growing": 8.0,
            "hot": 10.0,
        }[outlook]
    salary = attrs.get("salary") or {}

    def _midpoint(band) -> float | None:
        if isinstance(band, (list, tuple)) and len(band) == 2:
            try:
                return (float(band[0]) + float(band[1])) / 2
            except (TypeError, ValueError):
                return None
        return None

    money = _midpoint(salary.get("median")) or _midpoint(salary.get("entry"))
    if money is not None:
        if money < 40_000:
            signal["values.compensation"] = 3.0
        elif money < 60_000:
            signal["values.compensation"] = 5.0
        elif money < 90_000:
            signal["values.compensation"] = 7.0
        elif money < 130_000:
            signal["values.compensation"] = 8.5
        else:
            signal["values.compensation"] = 10.0
    if environments:
        variety = 4 + 2 * (len(environments) - 1)
        if int(work_style.get("pace") or 3) >= 4:
            variety += 1
        signal["values.variety"] = float(min(10, variety))
    if work_style.get("pace"):
        signal["values.work_life_balance"] = float(12 - 2 * int(work_style["pace"]))
    if {"clinic", "classroom"} & set(environments):
        signal["values.altruism"] = 7.0
    # Typed benefit kinds as derivation hints: a pension IS a
    # security signal — grounded inputs may ground a value on their own;
    # multiple hints take the strongest.
    benefits = set(attrs.get("benefits_kinds") or [])
    if benefits & {"pension", "healthcare"}:
        signal["values.security"] = max(signal.get("values.security", 0.0), 7.0)
    if "leave" in benefits:
        signal["values.work_life_balance"] = max(
            signal.get("values.work_life_balance", 0.0), 7.0
        )
    if "remote_budget" in benefits:
        signal["values.autonomy"] = max(signal.get("values.autonomy", 0.0), 8.0)
    if "equity" in benefits:
        signal["values.compensation"] = max(signal.get("values.compensation", 0.0), 8.0)
    if benefits & {"meals", "transport"}:
        signal["values.compensation"] = max(signal.get("values.compensation", 0.0), 6.0)
    return signal


def values_dimension(
    *,
    job_values: dict[str, float],
    user_values: dict[str, float],
) -> tuple[float, str, bool]:
    """Work-values similarity: mean absolute distance over the
    values BOTH sides signal → `10 − (10/9)·distance` (identical 10,
    maximal disagreement 0). One-sided or no signal ⇒ neutral."""
    shared = sorted(set(job_values) & set(user_values))
    if not shared:
        return NEUTRAL, "no values signal on one side", False
    distance = sum(
        abs(float(user_values[key]) - float(job_values[key])) for key in shared
    ) / len(shared)
    score = max(0.0, 10.0 - (10.0 / 9.0) * distance)
    return round(score, 2), f"values fit across {len(shared)} signals", True


def evaluate_gates(
    *,
    job_physical_requirements: list[str],
    job_education_level: str | None,
    user_physical_conditions: list[str],
    user_max_education_years: int | None,
    job_salary_entry_max: float | None = None,
    user_salary_min: float | None = None,
    user_salary_negotiable: bool = False,
) -> list[str]:
    """Hard-constraint gates — the job leaves the default feed (never deleted).

    Returns a list of gate reasons (empty ⇒ job is feed-eligible).
    Lifestyle gates fire only when the job side actually
    carries the signal — unknown job data never excludes.
    """
    gates: list[str] = []
    conditions = {c.strip().lower() for c in user_physical_conditions or []}
    requirements = {r.strip().lower() for r in job_physical_requirements or []}
    if "mobility_limited" in conditions and requirements & {
        "heavy-lifting",
        "standing-long",
        "physical-labor",
        "fieldwork",
    }:
        gates.append("physical")
    if user_max_education_years is not None and job_education_level:
        needed = EDUCATION_YEARS.get(job_education_level)
        if needed is not None and needed > user_max_education_years:
            gates.append("education_years")
    if (
        user_salary_min is not None
        and not user_salary_negotiable
        and job_salary_entry_max is not None
        and job_salary_entry_max < user_salary_min
    ):
        gates.append("salary_min")
    return gates


def compute_fit(
    *,
    job: dict,
    user: dict,
    weights: dict[str, int] | None = None,
) -> FitResult:
    """Fit score for one user×job pair.

    `job` keys: skill_links [{skill_id, required_level, importance}],
    education_level, experience_band, job_city, job_country, job_remote,
    interest_ids, work_style, physical_requirements, riasec_letters,
    salary_entry_max, values_signal {values.key: 1–10}.
    `user` keys: skill_levels {skill_id: level}, education_level,
    skill_months {skill_id: derived evidence months}, city,
    country, remote_ok, willing_to_relocate, physical_conditions,
    max_education_years, interest_ids, work_style, riasec
    {letter: value}, values {values.key: 1–10}, salary_min,
    salary_negotiable.
    """
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    breakdown: dict = {}
    effective: dict[str, float] = {}
    gates = evaluate_gates(
        job_physical_requirements=job.get("physical_requirements") or [],
        job_education_level=job.get("education_level"),
        user_physical_conditions=user.get("physical_conditions") or [],
        user_max_education_years=user.get("max_education_years"),
        job_salary_entry_max=job.get("salary_entry_max"),
        user_salary_min=user.get("salary_min"),
        user_salary_negotiable=bool(user.get("salary_negotiable", False)),
    )

    skills_score, skills_detail = skills_dimension(
        job.get("skill_links") or [], user.get("skill_levels") or {}
    )
    breakdown["skills"] = {"score": skills_score, "detail": skills_detail}
    effective["skills"] = weights["skills"] * DIMENSION_CONFIDENCE["skills"]

    edu_score, edu_detail = education_dimension(
        job.get("education_level"), user.get("education_level")
    )
    breakdown["education"] = {"score": edu_score, "detail": edu_detail}
    effective["education"] = weights["education"] * DIMENSION_CONFIDENCE["education"]

    exp_score, exp_detail, exp_signalled = experience_dimension(
        job.get("experience_band"),
        job.get("skill_links") or [],
        user.get("skill_months") or {},
    )
    breakdown["experience"] = {"score": exp_score, "detail": exp_detail}
    if exp_signalled:
        effective["experience"] = (
            weights["experience"] * DIMENSION_CONFIDENCE["experience"]
        )

    loc_score, loc_detail, loc_signalled = location_dimension(
        job_city=job.get("job_city"),
        job_country=job.get("job_country"),
        job_remote=bool(job.get("job_remote")),
        user_city=user.get("city"),
        user_country=user.get("country"),
        remote_ok=bool(user.get("remote_ok")),
        willing_to_relocate=bool(user.get("willing_to_relocate")),
    )
    breakdown["location"] = {"score": loc_score, "detail": loc_detail}
    if loc_signalled:
        effective["location"] = weights["location"] * DIMENSION_CONFIDENCE["location"]

    int_score, int_detail, int_signalled = interests_dimension(
        job_interest_ids=job.get("interest_ids") or set(),
        user_interest_ids=user.get("interest_ids") or set(),
        user_work_style=user.get("work_style"),
        job_work_style=job.get("work_style"),
        user_riasec=user.get("riasec"),
        job_riasec_letters=job.get("riasec_letters"),
    )
    breakdown["interests"] = {"score": int_score, "detail": int_detail}
    if int_signalled:
        effective["interests"] = (
            weights["interests"] * DIMENSION_CONFIDENCE["interests"]
        )

    values_score, values_detail, values_signalled = values_dimension(
        job_values=job.get("values_signal") or {},
        user_values=user.get("values") or {},
    )
    breakdown["values"] = {"score": values_score, "detail": values_detail}
    if values_signalled:
        effective["values"] = weights["values"] * DIMENSION_CONFIDENCE["values"]

    for dim, entry in breakdown.items():
        entry["weight"] = weights.get(dim, 3)
        if dim not in effective:
            entry["neutral"] = True

    total_weight = sum(effective.values())
    if total_weight <= 0:
        score = NEUTRAL
    else:
        score = (
            sum(effective[dim] * breakdown[dim]["score"] for dim in effective)
            / total_weight
        )
    score = round(score, 2)

    specialist = None
    if score < 6.0:
        strongest = max(breakdown.items(), key=lambda kv: kv[1]["score"])
        if strongest[1]["score"] >= 9.0:
            specialist = strongest[0]

    return FitResult(
        score=score,
        breakdown=breakdown,
        gates=gates,
        specialist_dimension=specialist,
    )
