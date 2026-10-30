from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.schemas.company import CompaniesOut, CompanyDetailOut
from app.services.catalog.company_service import CompanyService
from app.services.deps import get_current_user

router = APIRouter(prefix="/companies", tags=["companies"])


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return parts[:10] or None


@router.get("", response_model=CompaniesOut)
async def list_companies(
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    work_mode: str | None = Query(
        default=None, description="CSV match-any over open postings' work mode"
    ),
    seniority: str | None = Query(
        default=None, description="CSV match-any over open postings' seniority"
    ),
    employment: str | None = Query(
        default=None, description="CSV match-any over open postings' employment type"
    ),
    work_mode_exclude: str | None = Query(
        default=None, description="CSV exclude companies whose open postings carry any"
    ),
    seniority_exclude: str | None = Query(
        default=None, description="CSV exclude companies whose open postings carry any"
    ),
    employment_exclude: str | None = Query(
        default=None, description="CSV exclude companies whose open postings carry any"
    ),
    min_open: int | None = Query(default=None, ge=1, description="At least N open postings"),
    industry: str | None = Query(
        default=None, description="CSV match-any over profile industry tags"
    ),
    industry_exclude: str | None = Query(
        default=None, description="CSV exclude companies carrying any of these industry tags"
    ),
    location: str | None = Query(default=None, description="Matches open-posting city or country"),
    sort: str = Query(
        default="open_postings",
        pattern="^(open_postings|name|recent)$",
        description="open_postings (busiest first) | name (A-Z) | recent (latest open posting)",
    ),
    facets: bool = Query(default=False, description="Include the per-axis company-count facets"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompaniesOut:
    """Companies with open postings, busiest first — filterable by the
    hiring those postings prove (plan 154)."""
    result = await CompanyService(db).list_companies(
        q=q,
        limit=limit,
        work_mode=_csv(work_mode),
        seniority=_csv(seniority),
        employment=_csv(employment),
        work_mode_exclude=_csv(work_mode_exclude),
        seniority_exclude=_csv(seniority_exclude),
        employment_exclude=_csv(employment_exclude),
        min_open=min_open,
        industry=_csv(industry),
        industry_exclude=_csv(industry_exclude),
        location=location,
        sort=sort,
        facets=facets,
    )
    return CompaniesOut.model_validate(result)


@router.get("/{key}", response_model=CompanyDetailOut)
async def get_company(
    key: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyDetailOut:
    """One company: reviewed facts plus derived hiring stats."""
    try:
        return await CompanyService(db).get_company(key)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
