from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError
from app.schemas.company import CompanyDetailOut, CompanyOut
from app.services.catalog.company_service import CompanyService
from app.services.deps import get_current_user

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyOut])
async def list_companies(
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CompanyOut]:
    """Companies with open postings, busiest first."""
    return await CompanyService(db).list_companies(q=q, limit=limit)


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
