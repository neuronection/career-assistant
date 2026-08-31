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
FIT_VERSION = 1

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

DEFAULT_WEIGHTS = {
    "skills": 3,
    "location": 3,
    "experience": 3,
    "education": 3,
    "interests": 3,
}

# Per-dimension confidence (user slider × confidence = effective weight).
# All 1.0 today; the hook exists for future registry-driven confidence.
DIMENSION_CONFIDENCE = {k: 1.0 for k in DEFAULT_WEIGHTS}

DIMENSIONS = tuple(DEFAULT_WEIGHTS)


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
    evidence_years: float,
    evidence_instances: int,
) -> tuple[float, str]:
    """Relevance-weighted evidence vs the job's typical-years band.

    `band` is `attributes.experience_typical_years` (min, max). No band or
    no evidence ⇒ neutral 7 ("no signal") — experience is never punished
    for being absent from a student profile.
    """
    if band is None:
        return NEUTRAL, "no typical-experience band on this job"
    if evidence_years <= 0 and evidence_instances <= 0:
        return NEUTRAL, "no experience recorded yet — that's fine for students"
    low, high = band
    if evidence_years >= low:
        return (
            10.0,
            f"~{evidence_years:.1f}y of relevant experience meets the typical band",
        )
    ratio = evidence_years / max(low, 1.0)
    score = 4.0 + 6.0 * ratio
    return round(score, 2), (
        f"~{evidence_years:.1f}y relevant (typical: {low:g}–{high:g}y)"
        + (f" across {evidence_instances} item(s)" if evidence_instances else "")
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
) -> tuple[float, str, bool]:
    """Interest-tag overlap (60%) + work-style distance (40%).

    Overlap = |shared| / |job interests|. Work-style distance = mean
    absolute difference over the five 1–5 sliders → `10 − 2.5·distance`.
    No user interests ⇒ the interest half is neutral (no signal); no
    work-style on either side ⇒ the style half is neutral.
    """
    if job_interest_ids and user_interest_ids:
        overlap = len(job_interest_ids & user_interest_ids) / len(job_interest_ids)
        interest_part: float | None = 10.0 * overlap
    else:
        interest_part = None
    if user_work_style and job_work_style:
        deltas = [
            abs(float(user_work_style.get(k, 3)) - float(job_work_style.get(k, 3)))
            for k in WORK_STYLE_KEYS
        ]
        distance = sum(deltas) / len(deltas)
        style_part = max(0.0, 10.0 - 2.5 * distance)
    else:
        style_part = None
    parts = [p for p in (interest_part, style_part) if p is not None]
    if not parts:
        return NEUTRAL, "no interest or work-style signal", False
    score = sum(parts) / len(parts)
    bits = []
    if interest_part is not None:
        bits.append("interest overlap")
    if style_part is not None:
        bits.append("work-style fit")
    return round(score, 2), " + ".join(bits), True


def evaluate_gates(
    *,
    job_physical_requirements: list[str],
    job_education_level: str | None,
    user_physical_conditions: list[str],
    user_max_education_years: int | None,
) -> list[str]:
    """Hard-constraint gates — the job leaves the default feed (never deleted).

    Returns a list of gate reasons (empty ⇒ job is feed-eligible).
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
    interest_ids, work_style, physical_requirements.
    `user` keys: skill_levels {skill_id: level}, education_level,
    experience_years, experience_instances, city, country, remote_ok,
    willing_to_relocate, physical_conditions, max_education_years,
    interest_ids, work_style.
    """
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    breakdown: dict = {}
    effective: dict[str, float] = {}
    gates = evaluate_gates(
        job_physical_requirements=job.get("physical_requirements") or [],
        job_education_level=job.get("education_level"),
        user_physical_conditions=user.get("physical_conditions") or [],
        user_max_education_years=user.get("max_education_years"),
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

    exp_score, exp_detail = experience_dimension(
        job.get("experience_band"),
        float(user.get("experience_years") or 0.0),
        int(user.get("experience_instances") or 0),
    )
    breakdown["experience"] = {"score": exp_score, "detail": exp_detail}
    experience_signalled = job.get("experience_band") is not None and (
        float(user.get("experience_years") or 0.0) > 0
        or int(user.get("experience_instances") or 0) > 0
    )
    if experience_signalled:
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
    )
    breakdown["interests"] = {"score": int_score, "detail": int_detail}
    if int_signalled:
        effective["interests"] = (
            weights["interests"] * DIMENSION_CONFIDENCE["interests"]
        )

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


def evidence_years_from_experience(items: list[dict]) -> tuple[float, int]:
    """Derived experience years (kind-weighted) + instance count.

    Each item: {kind, start_year, end_year?, hours_per_week?, skill_keys[]}.
    Relevance weighting (per-skill matching against a job) happens in the
    service layer; this is the kind-weighted raw derivation. Overlapping
    items are summed — evidence, not a timeline.
    """
    years = 0.0
    instances = 0
    for item in items or []:
        start = item.get("start_year")
        if not start:
            continue
        end = item.get("end_year") or 2026
        span = max(0, int(end) - int(start))
        if span <= 0:
            continue
        kind = str(item.get("kind") or "project")
        kind_weight = EXPERIENCE_KIND_WEIGHT.get(kind, 0.4)
        hours = item.get("hours_per_week")
        intensity = min(1.0, float(hours) / 40.0) if hours else 1.0
        years += span * kind_weight * intensity
        instances += 1
    return round(years, 2), instances
