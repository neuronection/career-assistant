"""Job-type text utilities (plan 202 S1).

A catalog job type is an occupation archetype: generic, level-agnostic and
employer/team/product/platform/territory-agnostic. The pure normalization
lives in :mod:`app.core.job_titles`; this module derives containment/trigram
signals for the near-duplicate warning and implements the deterministic
naming guard that backs the proposer (the model is never the only gate).
"""

from __future__ import annotations

import re

from app.core import job_titles
from app.services.catalog.organization_service import trigram_similarity

#: Near-duplicate warning bar (a warning, never a block). Pinned in tests.
JOB_TYPE_NEAR_DUPLICATE_TRIGRAM = 0.72

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


def contains_title_tokens(candidate_title: str, posting_title: str) -> bool:
    """True when all candidate tokens occur in the posting title.

    A one-word catalog type is never a containment match: the containment
    signal requires at least two candidate-title tokens (plan 202 AD2).
    """
    candidate = job_titles.title_tokens(candidate_title)
    if len(candidate) < 2:
        return False
    posting = set(job_titles.title_tokens(posting_title))
    return all(token in posting for token in candidate)


def job_type_title_issue(title: str) -> str | None:
    """The deterministic naming-guard verdict, ``None`` when acceptable.

    Records a reason the admin must fix: empty/too-short titles, a bare
    level word, a department-only token, or a bare role head carrying only a
    qualifier ("Engineer - Identity & Privacy"). This is a guard, not a
    substitute for the model; the admin still sees the proposal.
    """
    normalized = job_titles.normalize_job_type_title(title)
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
    "job_type_title_issue",
    "strip_level_prefix",
    "trigram_similarity",
]
