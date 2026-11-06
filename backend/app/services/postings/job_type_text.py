"""Job-type text utilities (plan 202 S1).

A catalog job type is an occupation archetype: generic, level-agnostic and
employer/team/product/platform/territory-agnostic. These helpers normalize a
title for catalog comparison, derive containment/trigram signals for the
near-duplicate warning, and implement the deterministic naming guard that
backs the proposer (the model is never the only gate).
"""

from __future__ import annotations

import re

from app.services.catalog.organization_service import trigram_similarity

#: Near-duplicate warning bar (a warning, never a block). Pinned in tests.
JOB_TYPE_NEAR_DUPLICATE_TRIGRAM = 0.72

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

_BARE_LEVEL_WORDS = {
    "senior",
    "junior",
    "lead",
    "principal",
    "staff",
    "intern",
    "trainee",
    "graduate",
    "entry",
    "mid",
    "sr",
    "jr",
}

_DEPARTMENT_TOKENS = {
    "marketing",
    "engineering",
    "operations",
    "sales",
    "support",
    "support delivery",
    "business development",
    "finance",
    "product",
    "design",
    "people",
    "hr",
    "human resources",
    "customer success",
    "it",
}

_ROLE_HEADS = (
    "engineer",
    "manager",
    "analyst",
    "developer",
    "consultant",
    "specialist",
    "director",
    "architect",
    "designer",
    "administrator",
    "coordinator",
    "lead",
    "scientist",
    "officer",
)

_BARE_HEAD_WITH_QUALIFIER = re.compile(
    r"^(?:" + "|".join(_ROLE_HEADS) + r")\s*[-\u2013\u2014,:]\s*\S+",
    re.IGNORECASE,
)

#: Residual level prefixes the guard strips from a submitted title.
_LEVEL_PREFIX = re.compile(
    r"^(?:(?:senior|junior|lead|principal|staff|intern|trainee|graduate|mid|sr|jr)\.?\s+)+",
    re.IGNORECASE,
)


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


def contains_title_tokens(candidate_title: str, posting_title: str) -> bool:
    """True when all candidate tokens occur in the posting title.

    A one-word catalog type is never a containment match: the containment
    signal requires at least two candidate-title tokens (plan 202 AD2).
    """
    candidate = title_tokens(candidate_title)
    if len(candidate) < 2:
        return False
    posting = set(title_tokens(posting_title))
    return all(token in posting for token in candidate)


def job_type_title_issue(title: str) -> str | None:
    """The deterministic naming-guard verdict, ``None`` when acceptable.

    Records a reason the admin must fix: empty/too-short titles, a bare
    level word, a department-only token, or a bare role head carrying only a
    qualifier ("Engineer - Identity & Privacy"). This is a guard, not a
    substitute for the model; the admin still sees the proposal.
    """
    normalized = normalize_job_type_title(title)
    if len(normalized) < 3:
        return "too_short"
    if normalized in _BARE_LEVEL_WORDS:
        return "bare_level"
    if normalized in _DEPARTMENT_TOKENS:
        return "department_only"
    if _BARE_HEAD_WITH_QUALIFIER.match(str(title or "").strip()):
        return "bare_role_qualifier"
    return None


def strip_level_prefix(title: str) -> str:
    """Strip leading level qualifiers; keep the original when empty/short."""
    stripped = _LEVEL_PREFIX.sub("", str(title or "")).strip()
    return stripped if len(stripped) >= 3 else str(title or "").strip()


__all__ = [
    "JOB_TYPE_NEAR_DUPLICATE_TRIGRAM",
    "contains_title_tokens",
    "job_type_key",
    "job_type_title_issue",
    "normalize_job_type_title",
    "strip_level_prefix",
    "title_tokens",
    "trigram_similarity",
]
