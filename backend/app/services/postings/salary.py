"""Salary normalization: put posted figures on one comparable basis.

The annualized number is the posted amount scaled to a year on its OWN
basis — no FX, no gross/net conversion. A monthly and a yearly gross
become comparable; a gross and a net never silently mix (the basis is
carried alongside, and unknown stays unknown: an unknown period or a
missing amount annualizes to NULL, never a guess).
"""

from typing import Literal

SalaryBasis = Literal["gross", "net"]

#: Posted-period → per-year multiplier (40 h week, 5-day week, 52 weeks).
ANNUAL_FACTORS: dict[str, float] = {
    "hour": 2080.0,
    "day": 260.0,
    "week": 52.0,
    "month": 12.0,
    "year": 1.0,
}

BASIS_VALUES: tuple[str, ...] = ("gross", "net")


def annualized(
    low: float | None, high: float | None, period: str | None
) -> tuple[float | None, float | None]:
    """The posted range scaled to a year, or ``(None, None)`` when the
    period is unknown — unknown never silently matches a known basis.

    Accepts whatever the ORM returns for a NUMERIC column (``Decimal`` on
    both dialects) and normalizes to floats — mixing the two in arithmetic
    is the 2026-10-30 desktop crash (``Decimal * float``)."""
    factor = ANNUAL_FACTORS.get(period or "")
    if factor is None:
        return (None, None)
    low_year = float(low) * factor if low is not None else None
    high_year = float(high) * factor if high is not None else None
    if low_year is None and high_year is None:
        return (None, None)
    return (low_year, high_year)
