"""Bookmarklet capture (plan 212 S2.3).

One URL in, one ordinary posting out. The manual-URL connector's JSON-LD
parser is reused, the fetch goes through the same SSRF-guarded transport,
and the canonical URL is the idempotency key — capturing the same page
again returns the existing posting instead of a second row.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.extensions.builtin import parse_jsonld_payload
from app.extensions.sdk import RawPosting
from app.models.posting_model import JobPosting, JobSource
from app.services.integrations.webfetch import fetch_html
from app.services.postings.postings_service import upsert_posting

CAPTURE_SOURCE_KEY = "captures"
_TRACKING_PREFIXES = ("utm_", "mc_")
_TRACKING_KEYS = {"gclid", "fbclid", "ref", "source", "campaign"}
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)


def canonical_url(raw: str) -> str:
    """Normalize tracking noise away without changing the target page."""
    parsed = urlparse((raw or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValidationError("Capture needs an absolute http(s) posting URL")
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES) and key.lower() not in _TRACKING_KEYS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", urlencode(query), ""))


async def find_by_canonical_url(db: AsyncSession, canonical: str) -> JobPosting | None:
    """Exact first, then a bounded same-host probe for pre-capture rows."""
    exact = (
        (await db.execute(select(JobPosting).where(JobPosting.url == canonical).limit(1)))
        .scalars()
        .first()
    )
    if exact is not None:
        return exact
    host = urlparse(canonical).netloc
    if not host:
        return None
    rows = (
        (
            await db.execute(
                select(JobPosting)
                .where(JobPosting.url.ilike(f"%{host}%"))
                .order_by(JobPosting.created_at.desc())
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    for posting in rows:
        try:
            if canonical_url(posting.url or "") == canonical:
                return posting
        except ValidationError:
            continue
    return None


async def _capture_source(db: AsyncSession, canonical: str) -> JobSource:
    source = (
        (await db.execute(select(JobSource).where(JobSource.key == CAPTURE_SOURCE_KEY)))
        .scalars()
        .first()
    )
    if source is not None:
        return source
    source = JobSource(
        key=CAPTURE_SOURCE_KEY,
        connector_key="manual_url",
        title="Captured postings",
        kind="posting",
        config={"url": canonical},
        query_mode="static",
        # The capture path writes posts directly; the source is a home for
        # them, not a scheduled fetch of the first URL.
        enabled=False,
    )
    db.add(source)
    await db.flush()
    return source


async def capture_posting(db: AsyncSession, url: str) -> tuple[JobPosting, bool]:
    """Return ``(posting, created)``; never a duplicate canonical URL."""
    canonical = canonical_url(url)
    existing = await find_by_canonical_url(db, canonical)
    if existing is not None:
        return existing, False

    final_url, html = await fetch_html(canonical)
    canonical = canonical_url(final_url or canonical)
    existing = await find_by_canonical_url(db, canonical)
    if existing is not None:
        return existing, False

    try:
        items = parse_jsonld_payload(html)
    except Exception:  # malformed JSON-LD must fall through to the title
        items = []
    if items:
        raw = items[0].model_copy(update={"external_id": canonical[:300], "url": canonical})
    else:
        title = _TITLE.search(html)
        title_text = title.group(1).strip()[:300] if title else ""
        raw = RawPosting(
            external_id=canonical[:300],
            title=title_text or canonical[:300],
            url=canonical,
        )

    source = await _capture_source(db, canonical)
    posting = await upsert_posting(db, source, raw)
    if posting is None:
        posting = await find_by_canonical_url(db, canonical)
    if posting is None:
        raise ValidationError("The page did not produce a posting")
    await db.commit()
    await db.refresh(posting)
    return posting, True
