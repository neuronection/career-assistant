"""Inline SVG icon registry: CSP-safe, print-safe, self-contained.

Feather-style 24x24 stroke icons rendered inline — no icon fonts, no
external assets, colorable via `currentColor`. Static, trusted data
(never user input).
"""

from typing import Optional

_STROKE = (
    '<svg class="icn" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true">{paths}</svg>'
)

PATHS: dict[str, str] = {
    "phone": (
        '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 '
        "19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 "
        "2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l"
        '1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>'
    ),
    "mail": (
        '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>'
        '<polyline points="22,6 12,13 2,6"/>'
    ),
    "location": (
        '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>'
        '<circle cx="12" cy="10" r="3"/>'
    ),
    "link": (
        '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
        '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
    ),
    "linkedin": (
        '<path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4V9h4v1.5"/>'
        '<rect x="2" y="9" width="4" height="12"/>'
        '<circle cx="4" cy="4" r="2"/>'
    ),
    "github": (
        '<path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 '
        "6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 "
        "2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 "
        '5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/>'
    ),
    "globe": (
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="2" y1="12" x2="22" y2="12"/>'
        '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 '
        '15.3 15.3 0 0 1 4-10z"/>'
    ),
    "user": (
        '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>'
        '<circle cx="12" cy="7" r="4"/>'
    ),
    "briefcase": (
        '<rect x="2" y="7" width="20" height="14" rx="2"/>'
        '<path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>'
    ),
    "gradcap": (
        '<path d="M22 10 12 5 2 10l10 5 10-5z"/>'
        '<path d="M6 12v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5"/>'
    ),
    "wrench": (
        '<path d="M14.7 6.3a4.5 4.5 0 0 0 5.7 5.7l2-2a7 7 0 1 1-9.3-9.3l-2 2a4 4 0 '
        '0 0 3.6 3.6z"/>'
        '<path d="M13.5 10.5 2 22l4 2L17.5 12.5z"/>'
    ),
    "award": (
        '<circle cx="12" cy="8" r="6"/><path d="M15.5 13 17 22l-5-3-5 3 1.5-9"/>'
    ),
    "heart": (
        '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 19l6.6-6.4 1-1a5.5 5.5 0 0 0 0-7.8z"/>'
    ),
    "chat": (
        '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'
    ),
    "flag": (
        '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/>'
        '<line x1="4" y1="22" x2="4" y2="15"/>'
    ),
}

# Default section-heading glyph per block kind (heading-icons feature);
# plain, print-safe Feather geometry keyed off the same stroke template.
SECTION_KIND_ICONS: dict[str, str] = {
    "summary": "chat",
    "items": "briefcase",
    "skills": "wrench",
    "languages": "globe",
    "achievements": "award",
    "interests": "heart",
    "custom_text": "chat",
    "synth_items": "award",
}

LINK_KIND_ICONS = {"linkedin": "linkedin", "github": "github"}


def icon(name: Optional[str]) -> str:
    """Inline SVG for a registered icon name (empty string when unknown)."""
    paths = PATHS.get(name or "")
    return _STROKE.format(paths=paths) if paths else ""
