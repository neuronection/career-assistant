"""Career stages (Phase 25): derivation, weight presets, feature flags.

One first-class concept — the career stage — hangs every audience
adaptation off it: fit weight *presets* (suggested, user-overridable,
never hidden scoring branches), stage-gated modules, assessment content.
The stage lives on `profile.basics.career_stage`; an unset value is
derived from age/education/experience heuristics and always
user-correctable.
"""

from datetime import datetime

from sqlalchemy import select

from app.models.enums import CareerStage

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
    },
    # Early career: skills + interests lead, education fades into evidence.
    CareerStage.EARLY_CAREER: {
        "skills": 4,
        "location": 3,
        "experience": 3,
        "education": 2,
        "interests": 3,
    },
    # Experienced: the inverse of the student preset.
    CareerStage.EXPERIENCED: {
        "skills": 4,
        "location": 3,
        "experience": 5,
        "education": 1,
        "interests": 2,
    },
    # Switchers: curiosity for the new domain outweighs history in the old.
    CareerStage.SWITCHING: {
        "skills": 3,
        "location": 3,
        "experience": 2,
        "education": 2,
        "interests": 5,
    },
    # Returners: re-entry paths, location constrains, gaps don't punish.
    CareerStage.RETURNING: {
        "skills": 3,
        "location": 4,
        "experience": 3,
        "education": 2,
        "interests": 4,
    },
}


def max_birth_year() -> int:
    """Youngest legal birth year (computed constant, plan 25)."""
    return datetime.now().year - MIN_AGE


def _experience_years(experience: list[dict]) -> float:
    """Kind-weighted evidence years (shared formula with the fit engine)."""
    from app.services.fit.dimensions import evidence_years_from_experience

    years, _instances = evidence_years_from_experience(experience or [])
    return years


def _experience_gap_years(experience: list[dict]) -> float:
    """Years since the most recent experience item ended (0 if none)."""
    now = datetime.now().year
    ends = [int(item.get("end_year") or now) for item in experience or []]
    return max(0.0, float(now - max(ends))) if ends else 0.0


def derive_career_stage(basics: dict, experience: list[dict]) -> CareerStage:
    """Age/education/experience heuristic — always overridable."""
    basics = basics or {}
    birth_year = basics.get("birth_year")
    age = datetime.now().year - int(birth_year) if birth_year else None
    education = str(basics.get("education_level") or "high_school")
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


def effective_stage(basics: dict, experience: list[dict]) -> tuple[CareerStage, str]:
    """(stage, source) — explicit value wins, else the derivation."""
    basics = basics or {}
    explicit = basics.get("career_stage")
    if explicit:
        try:
            return CareerStage(explicit), "explicit"
        except ValueError:
            pass
    return derive_career_stage(basics, experience or []), "derived"


def stage_preset(stage: CareerStage) -> dict[str, int]:
    """Suggested fit-weight sliders for a stage (never forced)."""
    return dict(
        STAGE_WEIGHT_PRESETS.get(stage, STAGE_WEIGHT_PRESETS[CareerStage.STUDENT])
    )


def feature_flags(stage: CareerStage) -> dict[str, bool]:
    """Per-feature UI flags for the bootstrap payload (plan 25)."""
    return {
        "universities": stage == CareerStage.STUDENT,
        "grade_fields": stage == CareerStage.STUDENT,
    }


def is_student_stage(stage: CareerStage) -> bool:
    return stage == CareerStage.STUDENT


async def stage_for_user(db, user_id) -> tuple[CareerStage, str]:
    """Effective stage for a user; years derive from active experience
    items when they exist (plan 40 — never self-typed), else the legacy
    JSONB list."""
    from app.models.experience_model import ExperienceItem

    from app.services.profile_service import ProfileService

    profile = await ProfileService(db).get(user_id)
    rows = await db.execute(
        select(ExperienceItem).where(
            ExperienceItem.user_id == user_id,
            ExperienceItem.status == "active",
        )
    )
    items = rows.scalars().all()
    if items:
        experience = [
            {
                "kind": item.kind,
                "start_year": item.start.year,
                "end_year": item.end.year if item.end else None,
                "hours_per_week": item.hours_per_week,
            }
            for item in items
        ]
    else:
        experience = profile.experience or []
    return effective_stage(profile.basics or {}, experience)
