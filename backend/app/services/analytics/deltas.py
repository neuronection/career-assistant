"""Delta math for the market-statistics surfaces (plan 170).

One count with its equal-length predecessor: percent change against the
window that came immediately before, honest about zero baselines —
``delta_pct`` is ``None`` when the predecessor counted zero (the UI
renders "new", never a divide-by-zero).
"""

from __future__ import annotations

from app.schemas.stats import DeltaOut, TrendDir


def trend_dir(count: int, prev: int) -> TrendDir:
    """The trend vocabulary for one count against its predecessor."""
    if count > prev:
        return "up"
    if count < prev:
        return "down"
    return "flat"


def delta(count: int, prev: int) -> DeltaOut:
    """One count against its equal-length predecessor."""
    pct = round((count - prev) / prev * 100, 1) if prev else None
    return DeltaOut(count=count, prev=prev, delta_pct=pct, trend=trend_dir(count, prev))
