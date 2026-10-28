"""The posting history read (plan 142 D6): the journal rendered newest
first, `get_current_user`-scoped exactly like `/postings/{ref}` — one
new router module so the endpoint lives beside its domain without
touching the postings router itself. No write API: the journal is
append-only through the service seam."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.posting_model import PostingChange
from app.schemas.posting import PostingChangeOut, PostingsHistoryOut
from app.services.deps import get_current_user
from app.services.postings.postings_service import resolve_posting

router = APIRouter(tags=["postings"])


@router.get("/postings/{posting_ref}/history", response_model=PostingsHistoryOut)
async def posting_history(
    posting_ref: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PostingsHistoryOut:
    """One posting's change journal, newest first — actor kind, links,
    operation knobs, duration and the capped field diff per row."""
    posting = await resolve_posting(db, posting_ref)
    if posting is None:
        raise NotFoundError("Posting not found")
    total = (
        await db.execute(
            select(func.count())
            .select_from(PostingChange)
            .where(PostingChange.posting_id == posting.id)
        )
    ).scalar_one()
    rows = await db.execute(
        select(PostingChange)
        .where(PostingChange.posting_id == posting.id)
        .order_by(PostingChange.occurred_at.desc(), PostingChange.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        PostingChangeOut(
            id=row.id,
            occurred_at=row.occurred_at,
            actor_kind=row.actor_kind,
            actor_ref=row.actor_ref or {},
            operation=row.operation or {},
            duration_ms=row.duration_ms,
            diff=row.diff or {},
            outcome=row.outcome,
        )
        for row in rows.scalars().all()
    ]
    return PostingsHistoryOut(
        items=items, total=total, limit=limit, offset=offset, posting_id=posting.id
    )
