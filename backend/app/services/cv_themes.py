"""Predefined CV color/layout themes: curated DesignTokens.

Themes are data — a swatch the UI can render and a partial DesignTokens
override the editor applies on top of its current tokens. Custom themes
are just the editor's free-token mode; nothing here is special-cased in
the renderer.
"""

from dataclasses import dataclass

from app.schemas.cv_template import DesignTokens


@dataclass(frozen=True)
class CvTheme:
    key: str
    label: str
    description: str
    design: DesignTokens


CV_THEMES: list[CvTheme] = [
    CvTheme(
        "classic_navy",
        "Classic Navy",
        "Serif headings, restrained navy accent — traditional and safe.",
        DesignTokens(accent_color="#1e3a8a", font_stack="mixed", header_style="left"),
    ),
    CvTheme(
        "teal_modern",
        "Teal Modern",
        "Clean sans, centered header, teal accent.",
        DesignTokens(
            accent_color="#0f766e", heading_color="#134e4a", header_style="centered"
        ),
    ),
    CvTheme(
        "graphite_minimal",
        "Graphite Minimal",
        "Near-monochrome, compact — the most ATS-friendly.",
        DesignTokens(
            accent_color="#374151",
            heading_color="#111827",
            density="compact",
            heading_case="none",
            heading_weight=700,
        ),
    ),
    CvTheme(
        "burgundy_elegant",
        "Burgundy Elegant",
        "Serif accents with roomy spacing for narrative CVs.",
        DesignTokens(
            accent_color="#881337",
            heading_color="#4c0519",
            font_stack="serif",
            density="roomy",
            line_height=1.5,
        ),
    ),
    CvTheme(
        "forest_green",
        "Forest Green",
        "Calm green accents, banner header.",
        DesignTokens(
            accent_color="#166534",
            heading_color="#14532d",
            header_style="banner",
        ),
    ),
    CvTheme(
        "cobalt_cards",
        "Cobalt Cards",
        "Modern card containers with rounded corners.",
        DesignTokens(
            accent_color="#1d4ed8",
            section_style="card",
            corner_radius=3,
            heading_case="title",
        ),
    ),
    CvTheme(
        "amber_warm",
        "Amber Warm",
        "Geometric headings, warm amber accent.",
        DesignTokens(
            accent_color="#b45309",
            heading_color="#7c2d12",
            font_stack="geometric",
            header_style="centered",
        ),
    ),
    CvTheme(
        "slate_banner",
        "Slate Banner",
        "Full-width slate banner header, crisp and neutral.",
        DesignTokens(
            accent_color="#334155",
            heading_color="#0f172a",
            header_style="banner",
            heading_case="none",
            heading_weight=700,
        ),
    ),
]

THEMES_BY_KEY = {theme.key: theme for theme in CV_THEMES}
