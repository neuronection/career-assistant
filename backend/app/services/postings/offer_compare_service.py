"""Offer comparison math (plan 212 S3.6).

Pure deterministic normalization over the JSON stored in
`applications.offer`. Amounts are never FX-converted: mixed currencies are
flagged and compared only within their own currency. Cost of living is a
monthly amount in the offer currency, so the annual figure is `* 12`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application_model import Application
from app.models.posting_model import JobPosting

PERIOD_FACTOR = {"year": 1.0, "month": 12.0, "hour": 2080.0}
MAX_COMPARED = 4


def normalize_offer(offer: dict) -> dict | None:
    """One offer's annual/monthly/net figures, or None when unusable."""
    if not isinstance(offer, dict):
        return None
    try:
        amount = float(offer.get("amount") or 0)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    currency = str(offer.get("currency") or "").strip().upper()
    period = str(offer.get("period") or "year")
    if len(currency) != 3 or period not in PERIOD_FACTOR:
        return None
    annual = round(amount * PERIOD_FACTOR[period], 2)
    monthly = round(annual / 12.0, 2)
    cost = offer.get("cost_of_living")
    annual_cost: float | None
    net: float | None
    if cost is None or cost == "":
        annual_cost = None
        net = None
    else:
        try:
            monthly_cost = float(cost)
        except (TypeError, ValueError):
            annual_cost = None
            net = None
        else:
            if monthly_cost < 0:
                annual_cost = None
                net = None
            else:
                annual_cost = round(monthly_cost * 12.0, 2)
                net = round(annual - annual_cost, 2)
    benefits = offer.get("benefits") or []
    if not isinstance(benefits, list):
        benefits = []
    return {
        "currency": currency,
        "amount": amount,
        "period": period,
        "annual_amount": annual,
        "monthly_amount": monthly,
        "cost_of_living": cost if annual_cost is not None else None,
        "annual_cost_of_living": annual_cost,
        "net_annual_after_col": net,
        "benefits": [str(item)[:120] for item in benefits if str(item).strip()],
        "location": str(offer.get("location") or "")[:200],
        "deadline": offer.get("deadline"),
    }


async def offer_comparison(db: AsyncSession, user_id: uuid.UUID) -> tuple[list[dict], int, bool]:
    """Up to four newest offers, the total offer count, mixed-currency flag."""
    rows = (
        await db.execute(
            select(Application, JobPosting)
            .join(JobPosting, JobPosting.id == Application.posting_id)
            .where(Application.user_id == user_id)
            .order_by(Application.updated_at.desc(), Application.id)
        )
    ).all()
    normalized: list[dict] = []
    total = 0
    for application, posting in rows:
        item = normalize_offer(application.offer or {})
        if item is None:
            continue
        total += 1
        if len(normalized) >= MAX_COMPARED:
            continue
        item.update(
            {
                "application_id": application.id,
                "posting_title": posting.title,
                "posting_org": posting.org,
                "deadline": item["deadline"],
            }
        )
        normalized.append(item)
    currencies = {item["currency"] for item in normalized}
    return normalized, total, len(currencies) > 1
