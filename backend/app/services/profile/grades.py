"""Grade model helpers (plan 212 S1.4c).

Grades are scale-scoped: a UK class, a 4.0/10 GPA, a German Note and a
percentage are never converted into one another. `grade_ordinal` maps a
raw value to a 0-100 ordinal *within its own scale* for comparison; an
unknown scale or an out-of-range value returns None (never a guess).
"""

from decimal import Decimal

GRADE_SCALES = ("uk_honours", "gpa_4", "gpa_10", "de_note", "percentage", "other")

_UK_ORDINALS = {
    1.0: 85.0,
    2.1: 75.0,
    2.2: 65.0,
    3.0: 55.0,
    4.0: 45.0,
}


def grade_ordinal(scale: str | None, value: float | None) -> Decimal | None:
    """Normalized 0-100 ordinal on the grade's own scale, or None."""
    if scale is None or value is None:
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    ordinal: float | None
    if scale == "uk_honours":
        ordinal = _UK_ORDINALS.get(round(raw, 1))
    elif scale == "gpa_4":
        ordinal = raw * 25.0 if 0.0 <= raw <= 4.0 else None
    elif scale == "gpa_10":
        ordinal = raw * 10.0 if 0.0 <= raw <= 10.0 else None
    elif scale == "de_note":
        ordinal = (5.0 - raw) * 25.0 if 1.0 <= raw <= 5.0 else None
    elif scale == "percentage":
        ordinal = raw if 0.0 <= raw <= 100.0 else None
    else:
        ordinal = None
    return Decimal(str(round(ordinal, 2))) if ordinal is not None else None
