"""Bounded rich-text normalization for CV prose fields.

Storage format is markdown — never raw HTML. The accepted subset is the
one the renderer already parses (``inline_md``): **bold**, *italic*,
[text](url) with safe http(s)/mailto URLs, and hard line breaks. A single
``normalize_rich_text`` gate runs on every write path — user API input
and untrusted LLM output alike — stripping everything else (headings,
images, raw tags, exotic emphasis) so downstream HTML/DOCX/ATS exports
stay consistent and injection-proof.
"""

import re
from typing import Optional

_ALLOWED_URL = re.compile(r"^(https?://|mailto:|tel:)", re.IGNORECASE)
_TAG = re.compile(r"<[^>]*>")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((.+)\)")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BLOCK_MARKS = re.compile(r"^(\s*[-*+]\s+|\s*\d+[.)]\s+|>\s?)", re.MULTILINE)
_CODE_FENCE = re.compile(r"```|~~~")
_EMPHASIS_STRICT = re.compile(r"(\*\*\*+|___+)")
_MULTI_UNDERSCORE = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")


def normalize_rich_text(value: Optional[str], max_length: int) -> str:
    """Clamp prose to the renderer's inline-markdown subset.

    Empty/None → "". Applies, in order: strip block constructs (code
    fences, headings, list/quote markers), drop images and raw tags,
    unwrap unsupported emphasis, keep only safe links, collapse runs of
    newlines to a single break (max one newline), hard-trim to
    ``max_length``. Never raises — the input is untrusted by definition.
    """
    text = str(value or "")
    if not text.strip():
        return ""
    text = _CODE_FENCE.sub("", text)
    text = _HEADING.sub("", text)
    text = _BLOCK_MARKS.sub("", text)
    text = _IMAGE.sub("", text)
    text = _TAG.sub("", text)
    text = _EMPHASIS_STRICT.sub(lambda m: m.group(0)[0] * 2, text)
    text = _MULTI_UNDERSCORE.sub(r"\1", text)
    text = _MD_LINK.sub(_safe_link, text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    return text[:max_length]


def _safe_link(match: re.Match) -> str:
    label, url = match.group(1), match.group(2).strip()
    if url and _ALLOWED_URL.match(url):
        return f"[{label}]({url})"
    return label


def validate_rich_text(value: Optional[str], max_length: int) -> str:
    """Pydantic-shaped wrapper: normalize then enforce the length bound.

    Raises ``ValidationError``-style ``ValueError`` only when the
    normalized text still exceeds the bound (it can't otherwise fail —
    normalization strips, never invents).
    """
    normalized = normalize_rich_text(value, max_length)
    if len(normalized) > max_length:
        raise ValueError(f"ensure this value has at most {max_length} characters")
    return normalized
