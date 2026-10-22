"""Feed API (plan 117.3/117.4): token lifecycle, `.ics` and Atom feeds.

Token management requires a session; the two feeds themselves authenticate
with the URL token (calendar clients cannot send cookies or headers). The
plaintext token is returned once at mint/rotation and never stored.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ValidationError
from app.models.engagement_model import SearchHistory
from app.models.enums import FeedTokenKind
from app.models.user_model import User
from app.schemas.engagement import FeedTokenIn, FeedTokenMintedOut, FeedTokenOut
from app.services import calendar_feed, feed_tokens, rss_feed
from app.services.deps import get_current_user

router = APIRouter(prefix="/me", tags=["feeds"])


def _default_host(request: Request) -> str:
    return request.url.hostname or "careerassistant.local"


async def _validate_scope(db: AsyncSession, user_id: UUID, kind: str, scope: dict) -> dict:
    if kind == FeedTokenKind.ICS.value and scope:
        raise ValidationError("Calendar tokens are account-wide")
    search_id = scope.get("saved_search_id")
    if search_id:
        record = (
            (
                await db.execute(
                    select(SearchHistory).where(
                        SearchHistory.id == UUID(str(search_id)),
                        SearchHistory.user_id == user_id,
                        SearchHistory.scope == "postings",
                        SearchHistory.saved.is_(True),
                    )
                )
            )
            .scalars()
            .first()
        )
        if record is None:
            raise ValidationError("Saved search not found")
    return scope


@router.get("/feed-tokens", response_model=list[FeedTokenOut])
async def list_feed_tokens(
    kind: str | None = Query(default=None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FeedTokenOut]:
    """Token metadata (never the hash or plaintext), newest first."""
    rows = await feed_tokens.list_tokens(db, user.id, kind=kind)
    return [FeedTokenOut.model_validate(feed_tokens.public_token(row)) for row in rows]


@router.post("/feed-tokens", response_model=FeedTokenMintedOut, status_code=201)
async def mint_feed_token(
    data: FeedTokenIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedTokenMintedOut:
    """Mint a token; the plaintext is in this response only, once."""
    scope = await _validate_scope(
        db, user.id, data.kind.value, feed_tokens.normalize_scope(data.scope)
    )
    row, plaintext = await feed_tokens.mint(db, user.id, kind=data.kind, scope=scope)
    await db.commit()
    return FeedTokenMintedOut(
        **FeedTokenOut.model_validate(feed_tokens.public_token(row)).model_dump(),
        token=plaintext,
    )


@router.post("/feed-tokens/{token_id}/rotate", response_model=FeedTokenMintedOut)
async def rotate_feed_token(
    token_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedTokenMintedOut:
    """Revoke one token and return its successor's one-time plaintext."""
    row, plaintext = await feed_tokens.rotate(db, user.id, token_id)
    await db.commit()
    return FeedTokenMintedOut(
        **FeedTokenOut.model_validate(feed_tokens.public_token(row)).model_dump(),
        token=plaintext,
    )


@router.delete("/feed-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_feed_token(
    token_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke a token (a revoked or unknown token answers 404 on the feed)."""
    await feed_tokens.revoke(db, user.id, token_id)
    await db.commit()


@router.get("/calendar.ics")
async def calendar_feed_endpoint(
    request: Request,
    token: str = Query(min_length=16, max_length=200),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The account-wide calendar feed (authenticated by the URL token)."""
    row = await feed_tokens.resolve(db, token, FeedTokenKind.ICS)
    body = await calendar_feed.build_calendar(db, row.user_id, host=_default_host(request))
    await db.commit()
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="career-assistant.ics"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/feeds/rss")
async def rss_feed_endpoint(
    request: Request,
    token: str = Query(min_length=16, max_length=200),
    cursor: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The Atom feed for a saved-search token (authenticated by the token)."""
    row = await feed_tokens.resolve(db, token, FeedTokenKind.RSS)
    user = await db.get(User, row.user_id)
    if user is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("Feed not found")
    base_url = str(request.base_url).rstrip("/")
    body = await rss_feed.build_atom(
        db,
        user=user,
        scope=dict(row.scope or {}),
        base_url=base_url,
        cursor=cursor,
        token=token,
    )
    await db.commit()
    return Response(
        content=body,
        media_type="application/atom+xml; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )
