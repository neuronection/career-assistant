"""Embedded CV fonts: OFL-licensed WOFF2 subsets vendored beside this module
(`OFL.txt` holds the license text; network is never fetched).

`font_face_css(stack)` returns the inline `@font-face` rules for a stack
(byte-equal output, cached) or "" when the stack is not embedded / files
are missing — capability detection, callers fall back to their system
stack. Used only by the `cv_renderer.FONT_STACKS` emission."""

import base64
from functools import lru_cache
from pathlib import Path

_FONT_DIR = Path(__file__).resolve().parent / "cv_fonts"

_SUBSET_NAMES = ("greek", "latin-ext", "latin")

_SUBSET_RANGES = {
    "greek": "U+0370-03FF",
    "latin-ext": (
        "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, "
        "U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, "
        "U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF"
    ),
    "latin": (
        "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, "
        "U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, "
        "U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD"
    ),
}

_FAMILIES: dict[str, tuple[str, str, str]] = {
    "embedded-sans": ("Inter Embedded", "inter-", "400 700"),
    "embedded-serif": ("Source Serif 4 Embedded", "sourceserif-", "400 700"),
}


@lru_cache(maxsize=None)
def _data_uri(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:font/woff2;base64,{payload}"


def font_face_css(font_stack: str) -> str:
    """Inline @font-face rules for an embedded stack ('' when unavailable)."""
    entry = _FAMILIES.get(font_stack)
    if entry is None:
        return ""
    family, prefix, weight = entry
    rules: list[str] = []
    for subset in _SUBSET_NAMES:
        path = _FONT_DIR / f"{prefix}{subset}.woff2"
        if not path.exists():
            return ""
        rules.append(
            "@font-face { font-family: '%s'; font-style: normal; "
            "font-weight: %s; font-display: swap; "
            "src: url('%s') format('woff2'); unicode-range: %s; }"
            % (family, weight, _data_uri(path), _SUBSET_RANGES[subset])
        )
    return " ".join(rules)


def has_fonts(font_stack: str) -> bool:
    entry = _FAMILIES.get(font_stack)
    return entry is not None and (_FONT_DIR / f"{entry[1]}latin.woff2").exists()
