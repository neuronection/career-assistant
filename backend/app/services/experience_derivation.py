"""Experience evidence derivation (plan 40) — pure, deterministic math.

Same discipline as the fit engine: no DB, no LLM, every formula documented
and tested. The unit of evidence is the (item, skill) pair:

    effective months = calendar months × kind weight × role weight
                       × hours intensity × recency factor

Overlap dedup: per skill, a month is counted once at the *max* rate of the
items covering it — "3 years of Python" is computed, never stored, and
parallel items never double-count the same calendar time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

# Evidence weight per experience kind (plan 40 §Evidence derivation).
KIND_WEIGHT = {
    "job": 1.0,
    "internship": 0.6,
    "freelance": 0.7,
    "project": 0.3,
    "volunteer": 0.4,
}

# The skill's role inside one item.
ROLE_WEIGHT = {
    "primary": 1.0,
    "secondary": 0.6,
    "exposure": 0.3,
}

# Full-time reference; part-time work counts proportionally (capped at 1).
HOURS_REFERENCE = 40.0

# Evidence older than this many years decays (half credit).
RECENCY_YEARS = 3.0
RECENCY_FACTOR = 0.5

# Months of (weighted) evidence → level curve: level = 1 + 9·(1−e^(−m/48)).
# Anchors: 12mo ≈ 3.0, 24mo ≈ 4.5, 36mo ≈ 5.8, 48mo ≈ 6.7, 72mo ≈ 8.0.
LEVEL_TAU = 48.0

# Confidence saturates at this many weighted months of evidence.
CONFIDENCE_MONTHS = 36.0


@dataclass
class DerivedSkill:
    """Derived evidence for one skill across all matching items."""

    skill_id: str
    months: float
    level: float
    confidence: float
    supporting_items: list[str] = field(default_factory=list)


def _month_index(d: date) -> int:
    return d.year * 12 + (d.month - 1)


def _month_date(index: int) -> date:
    return date(index // 12, index % 12 + 1, 1)


def _span_months(start: date, end: date, today: date) -> int:
    """Inclusive month count between two month boundaries."""
    last = end if end <= today else today
    return max(0, _month_index(last) - _month_index(start) + 1)


def _recency_factor(item_end: date | None, today: date) -> float:
    reference = item_end or today
    years_ago = (today - reference).days / 365.25
    if years_ago > RECENCY_YEARS:
        return RECENCY_FACTOR
    return 1.0


def _hours_factor(hours_per_week: int | None) -> float:
    if not hours_per_week:
        return 1.0
    return min(1.0, float(hours_per_week) / HOURS_REFERENCE)


def _item_rate(item, role: str) -> float:
    """Weighted monthly rate for one (item, skill) participation."""
    return (
        KIND_WEIGHT.get(item.kind, 0.3)
        * ROLE_WEIGHT.get(role, 0.3)
        * _hours_factor(item.hours_per_week)
        * _recency_factor(item.end, date.today())
    )


def item_span(item, today: date | None = None) -> tuple[date, date]:
    """Effective [start, end] of an item (open-ended runs to today)."""
    today = today or date.today()
    end = item.end or (today if item.open_ended else item.start)
    if end > today:
        end = today
    return item.start, max(item.start, end)


def months_per_item(item, today: date | None = None) -> int:
    start, end = item_span(item, today)
    return _span_months(start, end, today or date.today())


def years_of_experience(items, today: date | None = None) -> float:
    """Person-level union of active item calendar months (unweighted).

    Overlapping items never double-count the same calendar month — the
    union of [start, end] spans is the honest total.
    """
    today = today or date.today()
    spans = sorted(item_span(item, today) for item in items or [])
    total = 0
    current_start: int | None = None
    current_end: int | None = None
    for start, end in spans:
        s, e = _month_index(start), _month_index(end)
        if current_start is None:
            current_start, current_end = s, e
        elif s <= current_end + 1:
            current_end = max(current_end, e)
        else:
            total += current_end - current_start + 1
            current_start, current_end = s, e
    if current_start is not None:
        total += current_end - current_start + 1
    return round(total / 12.0, 2)


def months_to_level(months: float) -> float:
    """Weighted months → anchored 1–10 level (monotonic, documented)."""
    if months <= 0:
        return 1.0
    return round(min(10.0, 1.0 + 9.0 * (1.0 - math.exp(-months / LEVEL_TAU))), 1)


def months_to_confidence(months: float) -> float:
    """Confidence saturates at CONFIDENCE_MONTHS of weighted evidence."""
    return round(min(1.0, months / CONFIDENCE_MONTHS), 2)


def derive_skill_months(
    participations: list[dict],
    today: date | None = None,
) -> dict[str, DerivedSkill]:
    """Overlap-deduped weighted months per skill.

    `participations`: [{item, skill_id, role_in_item}] where `item` is an
    object with kind/start/end/open_ended/hours_per_week/id. Per skill, a
    calendar month counts once at the max rate covering it.
    """
    today = today or date.today()
    month_maps: dict[str, dict[int, float]] = {}
    supporters: dict[str, set[str]] = {}
    for part in participations or []:
        item = part["item"]
        skill_id = str(part["skill_id"])
        role = part.get("role_in_item") or "primary"
        rate = _item_rate(item, role)
        if rate <= 0:
            continue
        start, end = item_span(item, today)
        month_map = month_maps.setdefault(skill_id, {})
        for index in range(_month_index(start), _month_index(end) + 1):
            if rate > month_map.get(index, 0.0):
                month_map[index] = rate
        supporters.setdefault(skill_id, set()).add(str(item.id))
    derived: dict[str, DerivedSkill] = {}
    for skill_id, month_map in month_maps.items():
        months = round(sum(month_map.values()), 2)
        derived[skill_id] = DerivedSkill(
            skill_id=skill_id,
            months=months,
            level=months_to_level(months),
            confidence=months_to_confidence(months),
            supporting_items=sorted(supporters.get(skill_id, set())),
        )
    return derived


def derivation_summary(derived: DerivedSkill, skill_label: str = "") -> dict:
    """Human-readable derivation line ("≈ level 5 from 36 months primary use")."""
    return {
        "skill_id": derived.skill_id,
        "skill_label": skill_label,
        "months": derived.months,
        "level": derived.level,
        "confidence": derived.confidence,
        "supporting_items": derived.supporting_items,
    }


def recency_date(last_used: date | None, item_end: date | None) -> date:
    """The staleness reference for a skill's evidence."""
    return last_used or item_end or date.today()


def stale_since(last_used: date | None, item_end: date | None) -> bool:
    """True when the most recent use is older than the recency window."""
    reference = recency_date(last_used, item_end)
    return (date.today() - reference).days > RECENCY_YEARS * 365.25


def default_last_used(item_end: date | None, open_ended: bool) -> date | None:
    """Evidence recency default: open items are current; ended items use end."""
    if open_ended:
        return date.today()
    return item_end


__all__ = [
    "DerivedSkill",
    "KIND_WEIGHT",
    "ROLE_WEIGHT",
    "RECENCY_YEARS",
    "derive_skill_months",
    "derivation_summary",
    "months_per_item",
    "months_to_confidence",
    "months_to_level",
    "years_of_experience",
    "stale_since",
    "default_last_used",
]
