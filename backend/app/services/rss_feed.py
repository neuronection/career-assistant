"""Saved-search Atom feed (plan 117.4).

The feed runs its own narrow keyset query over `job_postings`
(`created_at` cursor) — deliberately independent of the explore read path so
the two can evolve without coupling. Matching is a small, documented subset
of the saved search's filters: title/org text, seniority, employment type,
contract, remote policy and freshness.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
from xml.sax.saxutils import escape, quoteattr

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.engagement_model import SearchHistory
from app.models.posting_model import JobPosting
from app.models.user_model import User
from app.services.notification_channels import utcnow

FEED_LIMIT = 50
MAX_LIMIT = 100
POSTS_PATH = "/postings"
SEARCH_PATH = "/postings/search?q="
_POSTED_WINDOWS = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}


def encode_cursor(posting: JobPosting) -> str:
    """Stable keyset cursor: the posting's `created_at` plus its id."""
    return f"{posting.created_at.isoformat()}|{posting.id}"


def decode_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    stamp, _, raw_id = cursor.partition("|")
    try:
        created = datetime.fromisoformat(stamp)
        identifier = UUID(raw_id)
    except ValueError:
        return None
    return (created if created.tzinfo else created.replace(tzinfo=UTC)), identifier


def matching_filters(filters: dict, *, now: datetime | None = None) -> list:
    """The supported subset of a saved search's explore filters, as SQL."""
    moment = now or utcnow()
    clauses: list = []
    query = str(filters.get("q") or "").strip()
    if query:
        needle = f"%{query.lower()}%"
        clauses.append(
            or_(
                func.lower(JobPosting.title).like(needle),
                func.lower(JobPosting.org).like(needle),
            )
        )
    org = str(filters.get("org") or "").strip()
    if org:
        clauses.append(func.lower(JobPosting.org).like(f"%{org.lower()}%"))
    for key, column in (
        ("seniority", JobPosting.seniority),
        ("employment_type", JobPosting.employment_type),
        ("contract", JobPosting.contract_type),
        ("remote_policy", JobPosting.onsite_policy),
        ("schedule", JobPosting.work_hours),
        ("travel", JobPosting.travel_class),
    ):
        value = filters.get(key)
        if isinstance(value, str) and value.strip():
            clauses.append(column == value.strip())
        elif isinstance(value, list) and value:
            clauses.append(column.in_([str(item) for item in value]))
    posted = filters.get("posted_within")
    if isinstance(posted, str) and posted in _POSTED_WINDOWS:
        clauses.append(JobPosting.posted_at >= moment - timedelta(days=_POSTED_WINDOWS[posted]))
    return clauses


async def _scope_filters(db: AsyncSession, user_id: UUID, scope: dict | None) -> tuple[dict, str]:
    """The saved search's filters and a human feed title."""
    search_id = (scope or {}).get("saved_search_id")
    if not search_id:
        return {}, "New postings"
    record = (
        (
            await db.execute(
                select(SearchHistory).where(
                    SearchHistory.id == UUID(str(search_id)),
                    SearchHistory.user_id == user_id,
                    SearchHistory.scope == "postings",
                )
            )
        )
        .scalars()
        .first()
    )
    if record is None:
        raise NotFoundError("Saved search not found")
    title = (record.query or "").strip() or "Saved search"
    return dict(record.filters or {}), title


async def page(
    db: AsyncSession,
    *,
    user_id: UUID,
    scope: dict | None,
    cursor: str | None = None,
    limit: int = FEED_LIMIT,
    now: datetime | None = None,
) -> list[JobPosting]:
    """One keyset page of new postings for the token's scope."""
    filters, _title = await _scope_filters(db, user_id, scope)
    stmt = select(JobPosting).where(
        JobPosting.status == "mapped",
        JobPosting.catalog_job_id.is_not(None),
    )
    clauses = matching_filters(filters, now=now)
    if clauses:
        stmt = stmt.where(and_(*clauses))
    decoded = decode_cursor(cursor)
    if decoded is not None:
        created, identifier = decoded
        stmt = stmt.where(
            or_(
                JobPosting.created_at < created,
                and_(JobPosting.created_at == created, JobPosting.id < identifier),
            )
        )
    stmt = stmt.order_by(JobPosting.created_at.desc(), JobPosting.id.desc()).limit(
        min(limit, MAX_LIMIT)
    )
    rows = await db.execute(stmt)
    return list(rows.scalars().all())


def _link(base_url: str, posting: JobPosting) -> str:
    return f"{base_url.rstrip('/')}{POSTS_PATH}?posting={posting.ref}"


def render_atom(
    postings: list[JobPosting],
    *,
    title: str,
    feed_id: str,
    base_url: str,
    now: datetime | None = None,
    next_cursor: str | None = None,
    token: str | None = None,
) -> str:
    """Render the Atom document (escaped, absolute links)."""
    moment = (now or utcnow()).astimezone(UTC)
    updated = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"<title>{escape(title)}</title>",
        f"<id>{escape(feed_id)}</id>",
        f"<updated>{updated}</updated>",
        f'<link rel="alternate" href={quoteattr(base_url.rstrip("/") + POSTS_PATH)}/>',
    ]
    if next_cursor and token:
        href = f"{base_url.rstrip('/')}/api/v1/me/feeds/rss?token={token}&cursor={next_cursor}"
        lines.append(f'<link rel="next" href={quoteattr(href)}/>')
    lines.append("<author><name>Career Assistant</name></author>")
    for posting in postings:
        stamp = posting.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        summary = " · ".join(part for part in (posting.org, posting.title) if part)
        lines.extend(
            [
                "<entry>",
                f"<title>{escape(posting.title)}</title>",
                f"<id>urn:career:posting:{posting.id}</id>",
                f"<updated>{stamp}</updated>",
                f"<published>{stamp}</published>",
                f'<link rel="alternate" href={quoteattr(_link(base_url, posting))}/>',
                f"<summary>{escape(summary)}</summary>",
                "</entry>",
            ]
        )
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


async def build_atom(
    db: AsyncSession,
    *,
    user: User,
    scope: dict | None,
    base_url: str,
    cursor: str | None = None,
    now: datetime | None = None,
    token: str | None = None,
) -> str:
    """The user's Atom feed for one token scope."""
    _filters, title = await _scope_filters(db, user.id, scope)
    postings = await page(db, user_id=user.id, scope=scope, cursor=cursor, now=now)
    next_cursor = encode_cursor(postings[-1]) if len(postings) >= FEED_LIMIT else None
    scoped = UUID(str((scope or {}).get("saved_search_id") or user.id))
    return render_atom(
        postings,
        title=title,
        feed_id=f"urn:career:feed:{user.id}:{scoped}",
        base_url=base_url,
        now=now,
        next_cursor=next_cursor,
        token=token,
    )
