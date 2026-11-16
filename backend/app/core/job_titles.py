"""Pure job-type title normalization (plan 210 AD6).

No service imports: the model's derivation event, the catalog services and
the seed all use this module. Containment, trigram and the naming guard stay
in :mod:`app.services.postings.job_type_text`.
"""

from __future__ import annotations

import re

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_job_type_title(title: str) -> str:
    """Normalize a job-type title for catalog comparison.

    Casefolds, turns ``&`` into ``and``, replaces punctuation with spaces and
    collapses whitespace. The output is stable across diacritics-insensitive
    case folding and cosmetic punctuation.
    """
    text = str(title or "").replace("&", " and ")
    text = _PUNCTUATION.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip().casefold()


def job_type_key(title: str) -> str:
    """A stable key for a normalized title (spaces become hyphens)."""
    normalized = normalize_job_type_title(title)
    return re.sub(r"[\s_]+", "-", normalized).strip("-")


def title_tokens(title: str) -> tuple[str, ...]:
    """The normalized tokens of a job-type or posting title."""
    normalized = normalize_job_type_title(title)
    return tuple(token for token in normalized.split(" ") if token)


__all__ = [
    "job_type_key",
    "normalize_job_type_title",
    "title_tokens",
]
