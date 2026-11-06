"""Composite market dashboard (plan 195).

One request resolves the window once, compiles Explore's filters once and
runs only the requested cards against the same population. Each card is
isolated: a failure or an eight-second timeout becomes a typed entry in
``errors`` and the rest of the tab renders. The single ``as_of`` is one
timestamp, not a cross-statement snapshot — Postgres READ COMMITTED may
see ingestion land between two card queries.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.schemas.stats import (
    CardErrorOut,
    DashboardOut,
    DashboardQuery,
)
from app.services.catalog import company_stats_service
from app.services.postings import stats_service
from app.services.postings.explore_service import compile_explore_filters

logger = logging.getLogger(__name__)

DASHBOARD_CARDS = (
    "summary",
    "overview",
    "timeseries",
    "breakdown",
    "skills",
    "salary",
    "companies_summary",
    "companies_overview",
    "clockwork",
)
CARD_TIMEOUT_SECONDS = 8.0

CardFactory = Callable[[], Awaitable[Any]]


def resolve_cards(cards: Sequence[str] | None) -> tuple[str, ...]:
    """Validate the ``cards`` selection — unknown names are a 400."""
    if not cards:
        return DASHBOARD_CARDS
    selected: list[str] = []
    for raw in cards:
        for name in str(raw).split(","):
            card = name.strip()
            if not card:
                continue
            if card not in DASHBOARD_CARDS:
                raise ValidationError(
                    "unknown dashboard card: "
                    + card
                    + " (allowed: "
                    + ", ".join(DASHBOARD_CARDS)
                    + ")"
                )
            if card not in selected:
                selected.append(card)
    return tuple(selected) or DASHBOARD_CARDS


def _validate(query: DashboardQuery) -> None:
    if query.basis not in stats_service.BASES:
        raise ValidationError("basis must be one of: " + ", ".join(stats_service.BASES))
    if query.split is not None and query.split not in stats_service.SPLITS:
        raise ValidationError("split must be one of: " + ", ".join(stats_service.SPLITS))
    if query.dimension not in stats_service.DIMENSIONS:
        raise ValidationError("dimension must be one of: " + ", ".join(stats_service.DIMENSIONS))
    if query.bucket is not None and query.bucket not in stats_service.TIMESERIES_BUCKETS:
        raise ValidationError(
            "bucket must be one of: " + ", ".join(stats_service.TIMESERIES_BUCKETS)
        )


async def _run_card(
    db: AsyncSession, name: str, factory: CardFactory
) -> tuple[Any, CardErrorOut | None]:
    """Run one card inside its own savepoint so a cancellation cannot
    poison the shared session; a timeout is a typed card error."""
    try:
        async with db.begin_nested():
            value = await asyncio.wait_for(factory(), CARD_TIMEOUT_SECONDS)
        return value, None
    except TimeoutError:
        logger.warning("market dashboard card %s timed out after %ss", name, CARD_TIMEOUT_SECONDS)
        return None, CardErrorOut(
            code="timeout",
            message=f"{name} took longer than {CARD_TIMEOUT_SECONDS:.0f}s",
        )
    except Exception as exc:
        logger.exception("market dashboard card %s failed", name)
        return None, CardErrorOut(code="error", message=str(exc)[:200] or "card failed")


def _factories(
    db: AsyncSession,
    query: DashboardQuery,
    ctx: stats_service.WindowContext,
    conditions: list,
) -> dict[str, CardFactory]:
    extra = conditions
    return {
        "summary": lambda: stats_service.summary(
            db, status_basis=query.basis, now=ctx.as_of, extra=extra
        ),
        "overview": lambda: stats_service.overview(
            db, status_basis=query.basis, ctx=ctx, extra=extra
        ),
        "timeseries": lambda: stats_service.timeseries(
            db,
            status_basis=query.basis,
            ctx=ctx,
            bucket=query.bucket,
            split=query.split,
            extra=extra,
        ),
        "breakdown": lambda: stats_service.breakdown(
            db,
            dimension=query.dimension,
            status_basis=query.basis,
            ctx=ctx,
            extra=extra,
        ),
        "skills": lambda: stats_service.skills(db, status_basis=query.basis, ctx=ctx, extra=extra),
        "salary": lambda: stats_service.salary(db, status_basis=query.basis, ctx=ctx, extra=extra),
        "companies_summary": lambda: company_stats_service.summary(
            db, status_basis=query.basis, ctx=ctx, extra=extra
        ),
        "companies_overview": lambda: company_stats_service.overview(
            db, status_basis=query.basis, ctx=ctx, extra=extra
        ),
        "clockwork": lambda: stats_service.clockwork(
            db, status_basis=query.basis, ctx=ctx, extra=extra
        ),
    }


async def dashboard(
    db: AsyncSession,
    user_id: UUID,
    query: DashboardQuery,
    raw_filters: dict,
    *,
    now: datetime | None = None,
) -> DashboardOut:
    """Run the requested cards on one window, one basis and one compiled
    filter set. ``applied_filters`` echoes the normalized Explore filters
    so the UI can render its active chips without re-deriving them."""
    _validate(query)
    cards = resolve_cards(query.cards)
    ctx = stats_service.window_context(query.window, query.date_from, query.date_to, now)
    filters, conditions = await compile_explore_filters(db, raw_filters, user_id)
    factories = _factories(db, query, ctx, conditions)

    results: dict[str, Any] = {}
    errors: dict[str, CardErrorOut] = {}
    for name in cards:
        value, error = await _run_card(db, name, factories[name])
        results[name] = value
        if error is not None:
            errors[name] = error

    timeseries = results.get("timeseries")
    return DashboardOut(
        as_of=ctx.as_of,
        window=ctx.window,
        basis=query.basis,
        bucket=timeseries.bucket if timeseries is not None else query.bucket,
        applied_filters=filters,
        errors=errors,
        **results,
    )
