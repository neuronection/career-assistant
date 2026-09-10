"""Career stages (Phase 25): derivation, weight presets, feature flags.

One first-class concept — the career stage — hangs every audience
adaptation off it: fit weight *presets* (suggested, user-overridable,
never hidden scoring branches), stage-gated modules, assessment content.
The stage lives on `profile.basics.career_stage`; an unset value is
derived from age/education/experience heuristics and always
user-correctable.
"""

from datetime import datetime

from app.models.enums import CareerStage

# Evidence weight per experience kind for the stage heuristic — the
# calibration (projects count fractionally); 'job' is full-strength.
STAGE_KIND_WEIGHT = {
    "job": 1.0,
    "internship": 0.75,
    "freelance": 0.75,
    "volunteer": 0.5,
    "project": 0.4,
}

# Birth-year ceiling for profile validation: nobody younger than 14.
MIN_AGE = 14

STUDENT_EDUCATION_LEVELS = {"middle_school", "high_school"}

STAGE_WEIGHT_PRESETS: dict[CareerStage, dict[str, int]] = {
    # Students: education matters most, experience evidence barely exists.
    CareerStage.STUDENT: {
        "skills": 3,
        "location": 3,
        "experience": 1,
        "education": 5,
        "interests": 4,
        "values": 2,
    },
    # Early career: skills + interests lead, education fades into evidence.
    CareerStage.EARLY_CAREER: {
        "skills": 4,
        "location": 3,
        "experience": 3,
        "education": 2,
        "interests": 3,
        "values": 3,
    },
    # Experienced: the inverse of the student preset.
    CareerStage.EXPERIENCED: {
        "skills": 4,
        "location": 3,
        "experience": 5,
        "education": 1,
        "interests": 2,
        "values": 3,
    },
    # Switchers: curiosity for the new domain outweighs history in the old.
    CareerStage.SWITCHING: {
        "skills": 3,
        "location": 3,
        "experience": 2,
        "education": 2,
        "interests": 5,
        "values": 4,
    },
    # Returners: re-entry paths, location constrains, gaps don't punish.
    CareerStage.RETURNING: {
        "skills": 3,
        "location": 4,
        "experience": 3,
        "education": 2,
        "interests": 4,
        "values": 3,
    },
}


def max_birth_year() -> int:
    """Youngest legal birth year (computed constant)."""
    return datetime.now().year - MIN_AGE


def _experience_years(experience: list[dict]) -> float:
    """Kind-weighted evidence years over the `stage_dicts` dict shape.

    Items are {kind, start_year, end_year?, hours_per_week?}; spans sum
    (evidence, not a timeline) with STAGE_KIND_WEIGHT and part-time
    intensity capped at the 40h full-time reference.
    """
    years = 0.0
    for item in experience or []:
        start = item.get("start_year")
        if not start:
            continue
        end = item.get("end_year") or datetime.now().year
        span = max(0, int(end) - int(start))
        if span <= 0:
            continue
        hours = item.get("hours_per_week")
        intensity = min(1.0, float(hours) / 40.0) if hours else 1.0
        kind = str(item.get("kind") or "project")
        years += span * STAGE_KIND_WEIGHT.get(kind, 0.4) * intensity
    return round(years, 2)


def _experience_gap_years(experience: list[dict]) -> float:
    """Years since the most recent experience item ended (0 if none)."""
    now = datetime.now().year
    ends = [int(item.get("end_year") or now) for item in experience or []]
    return max(0.0, float(now - max(ends))) if ends else 0.0


def derive_career_stage(
    basics: dict, experience: list[dict], education_level: str | None = None
) -> CareerStage:
    """Age/education/experience heuristic — always overridable.

    ``education_level`` wins
    over the raw basics select when provided.
    """
    basics = basics or {}
    birth_year = basics.get("birth_year")
    age = datetime.now().year - int(birth_year) if birth_year else None
    education = str(education_level or basics.get("education_level") or "high_school")
    years = _experience_years(experience or [])

    if age is not None and age < 23 and education in STUDENT_EDUCATION_LEVELS:
        return CareerStage.STUDENT
    if years >= 3:
        gap = _experience_gap_years(experience or [])
        if gap >= 2:
            return CareerStage.RETURNING
        return CareerStage.EXPERIENCED
    if 0 < years < 3:
        return CareerStage.EARLY_CAREER
    if age is not None and age >= 25:
        return CareerStage.RETURNING
    return CareerStage.STUDENT


def effective_stage(
    basics: dict, experience: list[dict], education_level: str | None = None
) -> tuple[CareerStage, str]:
    """(stage, source) — explicit value wins, else the derivation."""
    basics = basics or {}
    explicit = basics.get("career_stage")
    if explicit:
        try:
            return CareerStage(explicit), "explicit"
        except ValueError:
            pass
    return (
        derive_career_stage(basics, experience or [], education_level),
        "derived",
    )


def stage_preset(stage: CareerStage) -> dict[str, int]:
    """Suggested fit-weight sliders for a stage (never forced)."""
    return dict(
        STAGE_WEIGHT_PRESETS.get(stage, STAGE_WEIGHT_PRESETS[CareerStage.STUDENT])
    )


def feature_flags(stage: CareerStage) -> dict[str, bool]:
    """Per-feature UI flags for the bootstrap payload."""
    return {
        "universities": stage == CareerStage.STUDENT,
        "grade_fields": stage == CareerStage.STUDENT,
        "education_step": stage == CareerStage.STUDENT,
    }


# Required completeness checks per onboarding path — nagging
# scopes to what the chosen start actually needs; everything else stays
# optional and only feeds the raw percent.
REQUIRED_BY_PATH: dict[str, frozenset[str]] = {
    "explore": frozenset({"basics", "interests"}),
    "target": frozenset({"basics"}),
    "cv_import": frozenset({"basics"}),
    "browse": frozenset(),
}


def required_sections(
    path: str | None, flags: dict[str, bool] | None = None
) -> set[str]:
    """Required profile checks for a start path.

    `explore` students also owe academics (the education mini-step's
    signal); every other path keeps the minimum. Unknown/None paths get
    the `browse` treatment (nothing required).
    """
    required = set(REQUIRED_BY_PATH.get(path or "", REQUIRED_BY_PATH["browse"]))
    if path == "explore" and flags and flags.get("education_step"):
        required.add("academics")
    return required


def is_student_stage(stage: CareerStage) -> bool:
    return stage == CareerStage.STUDENT


async def stage_for_user(db, user_id) -> tuple[CareerStage, str]:
    """Effective stage; years derive from active experience items only
    and education from the derived
    effective level."""
    from app.services.experience_service import ExperienceService
    from app.services.profile_entities_service import effective_education_level
    from app.services.profile_service import ProfileService

    profile = await ProfileService(db).get(user_id)
    basics = profile.basics or {}
    experience = await ExperienceService(db).stage_dicts(user_id)
    level = await effective_education_level(db, user_id, basics.get("education_level"))
    return effective_stage(basics, experience, education_level=level)
