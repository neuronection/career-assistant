"""CV block-kind registry: pluggable layout units, like
connectors (26) / triggers (29) / question kinds (37).

Each kind binds a pydantic props schema, sample data for gallery previews,
and renderer behavior (implemented in `cv_renderer`). New kinds register
via `register_block_kind` (entry-point extensible later) and must pass the
contract kit: props round-trip + sample renders + renderer parity.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.errors import ValidationError

HEX_COLOR = "^#[0-9a-fA-F]{6}$"


class BlockContainer(BaseModel):
    """Per-block container override; every field optional = inherit design."""

    model_config = {"extra": "forbid"}

    container: Literal["inherit", "flat", "tinted", "card", "outline", "accent-bar"] = (
        "inherit"
    )
    background: Optional[str] = Field(default=None, pattern=HEX_COLOR)
    border_color: Optional[str] = Field(default=None, pattern=HEX_COLOR)
    radius: Optional[int] = Field(default=None, ge=0, le=8)
    padding_mm: Optional[int] = Field(default=None, ge=1, le=10)


GLOBAL_FIELD_PROMPTS: dict[str, str] = {
    "__handling__": (
        "Use only the facts present in the provided context. Never invent "
        "employers, dates, numbers or skills. Keep dates month-precision."
    ),
    "summary": "2-3 sentences, evidence-based, no first person pronouns.",
    "experience.description": "1-2 tight lines per item; achievements over duties.",
    "experience.achievements": "Start with a strong verb; keep any real metrics.",
    "skills": "Keep taxonomy labels verbatim; group by category when possible.",
    "education": "Most recent first; program before institution.",
    "languages": "Use the CEFR-mapped profile level, never exaggerate.",
    "interests": "Max 6, most role-relevant first.",
}

SAMPLE_SNAPSHOT: dict = {
    "basics": {
        "name": "Alex Sample",
        "headline": "Aspiring software engineer",
        "email": "alex@example.com",
        "phone": "+30 555 0100",
        "location": "Athens, GR",
        "links": [
            {
                "kind": "github",
                "url": "https://github.com/alexsample",
                "label": "github",
            }
        ],
    },
    "summary": (
        "Motivated computer-science student with hands-on internship "
        "experience and a track record of shipping small tools end to end."
    ),
    "experience": [
        {
            "title": "Software Intern",
            "org": "Sample Corp",
            "start": "2024-06",
            "end": "2024-09",
            "description": "Built internal tooling for the QA team.",
            "skills": ["Python", "Git"],
            "achievements": [{"text": "Cut manual test setup from 2h to 20min"}],
        }
    ],
    "education": [
        {
            "program": "BSc Computer Science",
            "institution": "University of Sample",
            "department": "School of Computing",
            "level": "bachelor",
            "start": "2022-09",
            "end": "",
        }
    ],
    "certifications": [],
    "projects": [
        {
            "title": "Campus events app",
            "start": "2023-02",
            "end": "2023-06",
            "description": "Weekend project used by 200 students.",
            "skills": ["React"],
            "achievements": [],
        }
    ],
    "skills": [
        {"label": "Python", "level": 7, "category": "programming"},
        {"label": "SQL", "level": 5, "category": "programming"},
        {"label": "Git", "level": 6, "category": "tooling"},
    ],
    "languages": [{"code": "en", "label": "English", "level": "advanced"}],
    "achievements": [
        {
            "title": "Hackathon winner",
            "issuer": "SampleCon",
            "date": "2025-03",
            "kind": "award",
        }
    ],
    "interests": [{"label": "Open source"}, {"label": "Board games"}],
}


class HeaderProps(BaseModel):
    show_links: bool = True
    show_location: bool = True


class SummaryProps(BaseModel):
    title: str = Field(default="Summary", max_length=60)
    max_chars: int = Field(default=600, ge=200, le=1200)
    container: BlockContainer = Field(default_factory=BlockContainer)


class ItemsBlockProps(BaseModel):
    """Experience / education / certifications style item lists."""

    title: str = Field(default="", max_length=60)
    source_key: str = Field(min_length=1, max_length=60)
    max_items: int = Field(default=10, ge=1, le=30)
    show_skills: bool = True
    show_achievements: bool = True
    show_org: bool = True
    show_description: bool = True
    date_format: Literal["mon_yyyy", "iso", "eu", "year"] = "mon_yyyy"
    style: Literal["list", "timeline"] = "list"
    container: BlockContainer = Field(default_factory=BlockContainer)


class SkillsProps(BaseModel):
    title: str = Field(default="Skills", max_length=60)
    display: Literal["chips", "list", "grouped"] = "chips"
    show_levels: bool = False
    max_items: int = Field(default=18, ge=1, le=40)
    display: Literal["chips", "list", "grouped", "bars"] = "chips"
    show_levels: bool = False
    max_items: int = Field(default=18, ge=1, le=40)
    container: BlockContainer = Field(default_factory=BlockContainer)


class LanguagesProps(BaseModel):
    title: str = Field(default="Languages", max_length=60)
    container: BlockContainer = Field(default_factory=BlockContainer)


class AchievementsProps(BaseModel):
    title: str = Field(default="Achievements", max_length=60)
    kinds: list[Literal["award", "honor", "publication", "extracurricular"]] = Field(
        default_factory=lambda: ["award", "honor", "publication", "extracurricular"],
        max_length=4,
    )
    container: BlockContainer = Field(default_factory=BlockContainer)


class InterestsProps(BaseModel):
    title: str = Field(default="Interests", max_length=60)
    max_items: int = Field(default=6, ge=1, le=20)
    container: BlockContainer = Field(default_factory=BlockContainer)


class CustomTextProps(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    text: str = Field(default="", max_length=2000)
    container: BlockContainer = Field(default_factory=BlockContainer)


class LetterProps(BaseModel):
    """Cover-letter body: recipient block + salutation +
    paragraphs + closing; the sender header rides the `header` block."""

    recipient_name: str = Field(default="", max_length=120)
    recipient_org: str = Field(default="", max_length=120)
    date_label: str = Field(default="", max_length=40)
    subject: str = Field(default="", max_length=200)
    salutation: str = Field(default="Dear Hiring Team,", min_length=1, max_length=80)
    paragraphs: list[str] = Field(default_factory=list, max_length=8)
    closing: str = Field(default="Sincerely,", min_length=1, max_length=80)
    show_signature: bool = True
    container: BlockContainer = Field(default_factory=BlockContainer)


class SpacerProps(BaseModel):
    height_mm: int = Field(default=4, ge=2, le=20)


class BlockSpec:
    """Registry entry: props schema + sample data + renderer contract."""

    def __init__(self, kind: str, props_schema: type[BaseModel], sample: dict):
        self.kind = kind
        self.props_schema = props_schema
        self.sample = sample


BUILTIN_BLOCKS: dict[str, BlockSpec] = {
    "header": BlockSpec("header", HeaderProps, {}),
    "summary": BlockSpec(
        "summary", SummaryProps, {"title": "Summary", "max_chars": 600}
    ),
    "items": BlockSpec(
        "items",
        ItemsBlockProps,
        {
            "title": "Experience",
            "source_key": "experience",
            "max_items": 10,
            "show_skills": True,
            "show_achievements": True,
        },
    ),
    "skills": BlockSpec(
        "skills", SkillsProps, {"title": "Skills", "display": "chips", "max_items": 18}
    ),
    "languages": BlockSpec("languages", LanguagesProps, {"title": "Languages"}),
    "achievements": BlockSpec(
        "achievements", AchievementsProps, {"title": "Achievements"}
    ),
    "interests": BlockSpec(
        "interests", InterestsProps, {"title": "Interests", "max_items": 6}
    ),
    "custom_text": BlockSpec(
        "custom_text",
        CustomTextProps,
        {"title": "Custom", "text": "Custom section text."},
    ),
    "letter": BlockSpec(
        "letter",
        LetterProps,
        {
            "recipient_name": "Alex Sample",
            "recipient_org": "Sample Corp",
            "date_label": "Jun 2024",
            "salutation": "Dear Hiring Team,",
            "paragraphs": [
                "I am applying for the Software Intern role. During my "
                "internship I shipped internal QA tooling end to end.",
                "My coursework and projects gave me the Python and Git "
                "habits your team builds on.",
            ],
            "closing": "Sincerely,",
            "show_signature": True,
        },
    ),
    "spacer": BlockSpec("spacer", SpacerProps, {"height_mm": 4}),
}

REGISTRY: dict[str, BlockSpec] = dict(BUILTIN_BLOCKS)


def register_block_kind(spec: BlockSpec) -> None:
    """Register a new block kind (entry-point extensible later)."""
    if spec.kind in REGISTRY:
        raise ValidationError(f"Block kind already registered: {spec.kind}")
    REGISTRY[spec.kind] = spec


def validate_blocks(blocks: list[dict]) -> list[tuple[str, BaseModel]]:
    """Validate every block against its registry kind (hard-reject unknown).

    Returns (kind, validated_props) pairs; raises ValidationError with a
    per-block report otherwise.
    """
    validated: list[tuple[str, BaseModel]] = []
    problems: list[str] = []
    for index, block in enumerate(blocks):
        kind = block.get("kind")
        spec = REGISTRY.get(kind or "")
        if spec is None:
            problems.append(f"block {index}: unknown kind {kind!r}")
            continue
        try:
            props = spec.props_schema.model_validate(block.get("props") or {})
        except Exception as exc:  # noqa: BLE001 - pydantic errors are report text
            problems.append(f"block {index} ({kind}): {exc}")
            continue
        validated.append((kind, props))
    if problems:
        raise ValidationError("; ".join(problems))
    return validated


def block_contract_kit() -> dict[str, BlockSpec]:
    """Every registered kind (contract-kit test target)."""
    return dict(REGISTRY)
