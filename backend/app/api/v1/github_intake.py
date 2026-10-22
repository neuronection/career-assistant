"""GitHub intake API (plan 122 Phase 3): preview → create drafts.

Both endpoints are user-scoped; nothing is written until `/apply`, and
everything `/apply` writes is a draft (the review-first guarantee).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user_model import User
from app.services.deps import get_current_user

router = APIRouter(prefix="/me/intake/github", tags=["intake"])


class GithubApplyIn(BaseModel):
    login: str = Field(min_length=1, max_length=39)
    selections: list[int] = Field(min_length=1, max_length=30)


@router.get("/preview")
async def preview_github(
    login: str = Query(min_length=1, max_length=39),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Draft candidates for one public GitHub profile (no writes)."""
    from app.services.github_intake_service import preview

    return await preview(db, login)


@router.post("/apply", status_code=201)
async def apply_github(
    data: GithubApplyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create draft projects/achievements for the selected repositories."""
    from app.services.github_intake_service import apply

    return await apply(db, user.id, data.login, data.selections)
