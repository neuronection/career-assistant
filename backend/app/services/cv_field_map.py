"""CV field map: extraction field → profile target, declared
once.

The extraction prompt is generated from this map, so the AI contract and
the apply targets cannot drift. Unmapped extracted data is still returned
and stored — inert until a row exists (39's inert-unmapped rule).
"""

from app.models.enums import ExperienceKind
from app.schemas.cv_extract import CvExtract

# (field_path, target, prompt_hint, review_kind)
CV_FIELD_MAP: list[tuple[str, str, str, str]] = [
    ("basics.full_name", "profile.basics", "The CV owner's full name.", "text"),
    ("basics.headline", "profile.basics", "Professional headline if present.", "text"),
    ("basics.email", "profile.basics", "Primary contact email.", "text"),
    ("basics.phone", "profile.basics", "Primary contact phone.", "text"),
    ("basics.location", "profile.basics", "City/country of residence.", "text"),
    ("basics.links", "profile.basics", "Portfolio/LinkedIn/GitHub URLs.", "links"),
    ("summary", "draft.report", "Profile/objective summary text.", "text"),
    ("education[]", "education_items", "Each school/program with period.", "items"),
    (
        "experience[]",
        "experience_items",
        "Each role/project with org, period, description, skills used, and metric-bearing achievements.",
        "items",
    ),
    (
        "skills[]",
        "user_skills",
        "Every named skill; level_claim only when stated.",
        "skills",
    ),
    ("languages[]", "profile.academics", "Spoken languages with level.", "items"),
    (
        "certifications[]",
        "certifications",
        "Certificates/licenses with issuer.",
        "items",
    ),
    (
        "awards[]",
        "profile_achievements",
        "Awards, honors, publications, extracurriculars.",
        "items",
    ),
    ("interests[]", "profile.interests", "Listed interests/hobbies.", "items"),
]

FIELD_BY_PATH = {
    path: (target, hint, kind) for path, target, hint, kind in CV_FIELD_MAP
}

# Targets that write profile-facing data on apply; others are report-only.
APPLYABLE_TARGETS = {
    "profile.basics",
    "education_items",
    "experience_items",
    "user_skills",
    "profile.academics",
    "certifications",
    "profile_achievements",
    "profile.interests",
}


def source_kind_values() -> list[str]:
    return [k.value for k in ExperienceKind]


def build_extraction_prompt() -> str:
    """The AI extraction prompt, generated from the map (never drifts)."""
    lines = [
        "Extract the CV into the schema fields below.",
        "Rules: quote evidence verbatim per field; set confidence honestly; "
        "omit fields that are absent — never guess. Dates as YYYY-MM when "
        "month known, YYYY otherwise.",
        "Field guidance:",
    ]
    for path, target, hint, _kind in CV_FIELD_MAP:
        lines.append(f"- {path} (→ {target}): {hint}")
    lines.append(f"Experience kinds: {', '.join(source_kind_values())}.")
    return "\n".join(lines)


def summarize_targets(extract: CvExtract) -> dict[str, int]:
    """How many extracted items map to each target (review screen header)."""
    counts = {
        "profile.basics": 1
        if (extract.basics.email or extract.basics.phone or extract.basics.links)
        else 0,
        "education_items": len(extract.education),
        "experience_items": len(extract.experience),
        "user_skills": len(extract.skills),
        "profile.academics": len(extract.languages),
        "certifications": len(extract.certifications),
        "profile_achievements": len(extract.awards),
        "profile.interests": len(extract.interests),
    }
    return {k: v for k, v in counts.items() if v}
