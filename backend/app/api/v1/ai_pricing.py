"""System-scoped model price overrides (plan 58 P2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.model_pricing import resolve_price
from app.ai.model_pricing_data import MODEL_PRICING_COMPILED, MODEL_PRICING_ROWS
from app.core.database import get_db
from app.models.ai_model import AIGeneration, AIPriceOverride
from app.models.ai_provider_model import AIModel, AIProvider
from app.models.user_model import User
from app.services.deps import get_current_user

router = APIRouter(prefix="/ai", tags=["ai"])


class PriceOverrideIn(BaseModel):
    provider_key: str | None = Field(default=None, max_length=40)
    provider_ref: str | None = Field(default=None, max_length=40)
    model: str = Field(min_length=1, max_length=200)
    match: Literal["exact", "prefix"] = "exact"
    input_micros_per_million: int = Field(ge=0)
    output_micros_per_million: int = Field(ge=0)
    metering: Literal["tokens", "input_only", "output_only"] = "tokens"


class PriceOverrideOut(PriceOverrideIn):
    id: str
    updated_at: str


class EffectivePriceOut(BaseModel):
    provider: str | None
    provider_id: str | None
    model: str
    source: str
    input_micros_per_million: int
    output_micros_per_million: int
    metering: str
    reviewed_at: str | None = None
    price_version: str | None = None


class PricesOut(BaseModel):
    overrides: list[PriceOverrideOut]
    effective: list[EffectivePriceOut]


class CostRow(BaseModel):
    provider: str
    model: str
    calls: int
    tokens_in: int
    tokens_out: int
    cost_micros: int | None
    priced_calls: int
    unpriced_calls: int


class CostsOut(BaseModel):
    window: str
    rows: list[CostRow]


def _is_local(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")


def _out(row: AIPriceOverride) -> PriceOverrideOut:
    return PriceOverrideOut(
        id=str(row.id),
        provider_key=row.provider_key,
        provider_ref=str(row.provider_ref) if row.provider_ref else None,
        model=row.model,
        match=cast(Literal["exact", "prefix"], row.match),
        input_micros_per_million=int(row.input_micros_per_million),
        output_micros_per_million=int(row.output_micros_per_million),
        metering=cast(Literal["tokens", "input_only", "output_only"], row.metering),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("/prices", response_model=PricesOut)
async def list_prices(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> PricesOut:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    overrides = (await db.execute(select(AIPriceOverride))).scalars().all()
    user_rows = [
        {
            "providerRef": str(row.provider_ref) if row.provider_ref else None,
            "provider": row.provider_key,
            "model": row.model,
            "match": row.match,
            "inputMicrosPerMillion": int(row.input_micros_per_million),
            "outputMicrosPerMillion": int(row.output_micros_per_million),
            "metering": row.metering,
            "id": str(row.id),
            "updatedAt": row.updated_at.isoformat(),
        }
        for row in overrides
    ]
    effective: list[EffectivePriceOut] = []
    rows = await db.execute(
        select(AIModel, AIProvider)
        .join(AIProvider, AIModel.provider_id == AIProvider.id)
        .where(AIModel.is_active.is_(True), AIProvider.is_active.is_(True))
    )
    for model, provider in rows.all():
        is_local = (
            bool(provider.is_local)
            if provider.is_local is not None
            else _is_local(provider.api_base)
        )
        resolution = resolve_price(
            rows=MODEL_PRICING_ROWS,
            compiled=MODEL_PRICING_COMPILED,
            model=model.model_name,
            provider_key=provider.preset_key,
            provider_row_id=str(provider.id),
            is_local=is_local,
            user_rows=user_rows,
        )
        effective.append(
            EffectivePriceOut(
                provider=provider.preset_key or provider.name,
                provider_id=str(provider.id),
                model=model.model_name,
                source=resolution.source if resolution else "unknown",
                input_micros_per_million=resolution.input_micros_per_million if resolution else 0,
                output_micros_per_million=resolution.output_micros_per_million if resolution else 0,
                metering=resolution.metering if resolution else "tokens",
                reviewed_at=resolution.reviewed_at if resolution else None,
                price_version=resolution.price_version if resolution else None,
            )
        )
    return PricesOut(overrides=[_out(row) for row in overrides], effective=effective)


@router.get("/usage/costs", response_model=CostsOut)
async def usage_costs(
    window: str = "30d",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CostsOut:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    days = {"24h": 1, "7d": 7, "30d": 30}.get(window, 30)
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await db.execute(
        select(
            AIGeneration.provider,
            AIGeneration.model,
            func.count(AIGeneration.id),
            func.coalesce(func.sum(AIGeneration.tokens_in), 0),
            func.coalesce(func.sum(AIGeneration.tokens_out), 0),
            func.sum(AIGeneration.cost_micros),
            func.count(AIGeneration.cost_micros),
        )
        .where(AIGeneration.created_at >= since)
        .group_by(AIGeneration.provider, AIGeneration.model)
        .order_by(func.count(AIGeneration.id).desc())
    )
    out: list[CostRow] = []
    for provider, model, calls, tokens_in, tokens_out, cost, priced in rows.all():
        out.append(
            CostRow(
                provider=provider,
                model=model,
                calls=int(calls),
                tokens_in=int(tokens_in or 0),
                tokens_out=int(tokens_out or 0),
                cost_micros=int(cost) if cost is not None else None,
                priced_calls=int(priced),
                unpriced_calls=int(calls) - int(priced),
            )
        )
    return CostsOut(window=window, rows=out)


@router.put("/prices", response_model=PriceOverrideOut)
async def put_price(
    body: PriceOverrideIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PriceOverrideOut:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    if body.provider_key and body.provider_ref:
        raise HTTPException(status_code=422, detail="bind provider_key or provider_ref, not both")
    provider_ref = UUID(body.provider_ref) if body.provider_ref else None
    if provider_ref is not None and await db.get(AIProvider, provider_ref) is None:
        raise HTTPException(status_code=422, detail="unknown provider_ref")
    query = select(AIPriceOverride).where(AIPriceOverride.model == body.model)
    query = query.where(
        AIPriceOverride.provider_key.is_(None)
        if body.provider_key is None
        else AIPriceOverride.provider_key == body.provider_key
    )
    query = query.where(
        AIPriceOverride.provider_ref.is_(None)
        if provider_ref is None
        else AIPriceOverride.provider_ref == provider_ref
    )
    query = query.where(AIPriceOverride.match == body.match)
    row = (await db.execute(query)).scalars().first()
    if row is None:
        row = AIPriceOverride(
            provider_key=body.provider_key,
            provider_ref=provider_ref,
            model=body.model,
            match=body.match,
            input_micros_per_million=body.input_micros_per_million,
            output_micros_per_million=body.output_micros_per_million,
            metering=body.metering,
        )
        db.add(row)
    else:
        row.input_micros_per_million = body.input_micros_per_million
        row.output_micros_per_million = body.output_micros_per_million
        row.metering = body.metering
        row.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.delete("/prices/{override_id}", status_code=204)
async def delete_price(
    override_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    row = await db.get(AIPriceOverride, UUID(override_id))
    if row is None:
        raise HTTPException(status_code=404, detail="price override not found")
    await db.delete(row)
    await db.commit()
