"""Seeded CV template bank: five starter layouts.

Bank rows carry author_key='bank', source='bank' and are read-only for
users (duplicate to edit). Idempotent by (key, version=1).
"""

from sqlalchemy import select

from app.models.cv_template_model import CvTemplate
from app.models.enums import CvTemplateSource, CvTemplateStatus
from app.schemas.cv_template import TemplateContent
from app.services.engagement_service import canonical_hash

DESIGN_A4_SANS = {}


def _content(
    blocks: list[dict],
    *,
    accent: str = "#1d4ed8",
    font: str = "sans",
    density: str = "normal",
    header: str = "left",
    max_pages: int = 1,
    overflow: str = "warn",
    field_prompts: dict | None = None,
) -> dict:
    return {
        "blocks": blocks,
        "design": {
            "accent_color": accent,
            "font_stack": font,
            "density": density,
            "header_style": header,
        },
        "pages": {"default_max_pages": max_pages, "overflow_policy": overflow},
        "prompts": {"field_prompts": field_prompts or {}, "field_handling": ""},
    }


def _items(title: str, source: str, **props) -> dict:
    return {
        "kind": "items",
        "props": {"title": title, "source_key": source, **props},
    }


BANK_TEMPLATES: list[dict] = [
    {
        "key": "ats-classic",
        "title": "ATS-Safe Classic",
        "description": "Single-column, standard headings, maximal parser compatibility.",
        "page_size": "a4",
        "ats_safe": True,
        "content": _content(
            [
                {
                    "kind": "header",
                    "props": {"show_links": True, "show_location": True},
                },
                {"kind": "summary", "props": {}},
                _items("Experience", "experience", max_items=10),
                _items(
                    "Education",
                    "education",
                    max_items=5,
                    show_skills=False,
                    show_achievements=False,
                ),
                {"kind": "skills", "props": {"display": "list", "max_items": 20}},
                {"kind": "languages", "props": {}},
            ],
            font="serif",
        ),
    },
    {
        "key": "modern-two-column",
        "title": "Modern Two-Column",
        "description": "Accent-colored headings with chips and a compact feel.",
        "page_size": "a4",
        "ats_safe": False,
        "content": _content(
            [
                {
                    "kind": "header",
                    "props": {"show_links": True, "show_location": True},
                },
                {"kind": "summary", "props": {}},
                _items("Experience", "experience", max_items=8),
                {"kind": "skills", "props": {"display": "chips", "max_items": 18}},
                _items(
                    "Education",
                    "education",
                    max_items=4,
                    show_skills=False,
                    show_achievements=False,
                ),
                {"kind": "languages", "props": {}},
                {"kind": "interests", "props": {"max_items": 6}},
            ],
            accent="#0f766e",
            density="compact",
        ),
    },
    {
        "key": "compact-onepage",
        "title": "Compact One-Page",
        "description": "Tight spacing that squeezes a full profile onto one page.",
        "page_size": "a4",
        "ats_safe": True,
        "content": _content(
            [
                {
                    "kind": "header",
                    "props": {"show_links": True, "show_location": True},
                },
                {"kind": "summary", "props": {"max_chars": 400}},
                _items("Experience", "experience", max_items=6),
                _items(
                    "Projects",
                    "projects",
                    max_items=4,
                    show_skills=True,
                    show_achievements=False,
                ),
                {"kind": "skills", "props": {"display": "chips", "max_items": 14}},
                _items(
                    "Education",
                    "education",
                    max_items=3,
                    show_skills=False,
                    show_achievements=False,
                ),
            ],
            density="compact",
            overflow="shrink",
        ),
    },
    {
        "key": "academic",
        "title": "Academic",
        "description": "Serif typography with publications and achievements up front.",
        "page_size": "a4",
        "ats_safe": True,
        "content": _content(
            [
                {
                    "kind": "header",
                    "props": {"show_links": True, "show_location": True},
                },
                _items(
                    "Education",
                    "education",
                    max_items=6,
                    show_skills=False,
                    show_achievements=False,
                ),
                {"kind": "achievements", "props": {"title": "Publications & Awards"}},
                _items("Experience", "experience", max_items=8),
                {"kind": "languages", "props": {}},
            ],
            accent="#111827",
            font="serif",
            density="roomy",
            max_pages=2,
        ),
    },
    {
        "key": "student-first",
        "title": "Student First",
        "description": "Leads with projects and skills — built for light work history.",
        "page_size": "a4",
        "ats_safe": True,
        "content": _content(
            [
                {
                    "kind": "header",
                    "props": {"show_links": True, "show_location": True},
                },
                {"kind": "summary", "props": {}},
                _items(
                    "Projects",
                    "projects",
                    max_items=6,
                    show_skills=True,
                    show_achievements=True,
                ),
                {
                    "kind": "skills",
                    "props": {"display": "chips", "max_items": 16, "show_levels": True},
                },
                _items("Experience", "experience", max_items=4),
                _items(
                    "Education",
                    "education",
                    max_items=3,
                    show_skills=False,
                    show_achievements=False,
                ),
                {"kind": "interests", "props": {"max_items": 6}},
            ],
            accent="#7c3aed",
            density="normal",
            field_prompts={
                "summary": "Students: lead with what you have built and learned.",
            },
        ),
    },
]


async def seed_cv_template_bank(db) -> int:
    """Insert missing bank templates (idempotent, by author_key+key+v1)."""
    existing = {
        (row[0], row[1])
        for row in (
            await db.execute(
                select(CvTemplate.author_key, CvTemplate.key).where(
                    CvTemplate.author_key == "bank", CvTemplate.version == 1
                )
            )
        ).all()
    }
    added = 0
    for spec in BANK_TEMPLATES:
        if ("bank", spec["key"]) in existing:
            continue
        content = TemplateContent.model_validate(spec["content"])
        db.add(
            CvTemplate(
                key=spec["key"],
                version=1,
                title=spec["title"],
                description=spec["description"],
                author_user_id=None,
                author_key="bank",
                source=CvTemplateSource.BANK.value,
                visibility="private",
                language="en",
                page_size=spec.get("page_size", "a4"),
                ats_safe=spec.get("ats_safe", False),
                schema_version=1,
                content_hash=canonical_hash(content.model_dump(mode="json")),
                status=CvTemplateStatus.PUBLISHED.value,
                content=content.model_dump(mode="json"),
            )
        )
        added += 1
    await db.commit()
    return added


def _sidebar_content(
    *,
    sidebar_color: str,
    accent: str,
    heading_color: str,
    font: str = "sans",
    sidebar_side: str = "left",
) -> dict:
    """Two-column layout: sidebar (contact, education, skills, languages)
    + main column (profile, experience) — the modern magazine pattern."""
    return {
        "blocks": [
            {"kind": "header"},
            {"kind": "summary", "column": "main"},
            {
                "kind": "items",
                "column": "main",
                "props": {
                    "title": "Experience",
                    "source_key": "experience",
                    "date_format": "mon_yyyy",
                },
            },
            {
                "kind": "items",
                "column": "sidebar",
                "props": {
                    "title": "Education",
                    "source_key": "education",
                    "show_description": False,
                },
            },
            {"kind": "skills", "column": "sidebar"},
            {"kind": "languages", "column": "sidebar"},
            {"kind": "interests", "column": "sidebar"},
        ],
        "design": {
            "accent_color": accent,
            "heading_color": heading_color,
            "font_stack": font,
            "layout": "sidebar",
            "sidebar_side": sidebar_side,
            "sidebar_color": sidebar_color,
            "sidebar_text_color": "#ffffff",
            "sidebar_width_pct": 34,
            "corner_radius": 2,
        },
        "pages": {"default_max_pages": 1, "overflow_policy": "warn"},
        "prompts": {"field_prompts": {}, "field_handling": ""},
    }


BANK_TEMPLATES.extend(
    [
        {
            "key": "navy-sidebar",
            "title": "Navy Sidebar",
            "description": "Two-column magazine layout: dark navy sidebar for contact, education and skills; main column for profile and experience.",
            "page_size": "a4",
            "ats_safe": False,
            "content": _sidebar_content(
                sidebar_color="#16324f", accent="#1e3a8a", heading_color="#16324f"
            ),
        },
        {
            "key": "teal-sidebar",
            "title": "Teal Sidebar",
            "description": "Modern teal two-column layout with rounded sidebar.",
            "page_size": "a4",
            "ats_safe": False,
            "content": _sidebar_content(
                sidebar_color="#0f766e",
                accent="#0f766e",
                heading_color="#134e4a",
                sidebar_side="left",
            ),
        },
    ]
)
