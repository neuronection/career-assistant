"""Pinned identity for the assessment-question bank (plan 225 S0).

A question's body is a stable slug, never its prompt: editing the prompt text
keeps the identity, while an unmatched/edited prompt simply stays unkeyed and
is never adopted. Migration ``0022`` embeds a copy of this map because
migrations must not import app code; a parity test keeps the two copies and
today's ``BANK_QUESTIONS`` in lockstep until the bank becomes a pack.
"""

from __future__ import annotations

from typing import Final

QUESTION_KEYS: Final[dict[str, str]] = {
    "A friend asks you to help organize a big local charity event. "
    "Which role do you quietly hope for?": "charity-event-role",
    "Your class gets a free-form project month. Which project pulls you in first?": (
        "free-form-project"
    ),
    "Something breaks on a group trip and everyone looks at each other. "
    "What happens next, realistically?": "group-trip-breakdown",
    "A company offers you a Saturday shadowing one of its teams. "
    "Which team do you pick?": "saturday-shadowing",
    "A week in your dream job — how would the tasks split?": "dream-job-week",
    "You get a free learning year, split across these tracks:": "learning-year-tracks",
    "Rank these workday realities from 'sounds great' to 'no thanks'.": (
        "workday-realities-ranking"
    ),
    "Which compliments would you actually want to earn?": "wanted-compliments",
}


def question_seed_key(prompt: str) -> str | None:
    """The pinned ``seed_key`` for a bank prompt, or ``None`` when unmatched."""
    key = QUESTION_KEYS.get(prompt)
    return f"assessment-question:{key}" if key else None


__all__ = ["QUESTION_KEYS", "question_seed_key"]
