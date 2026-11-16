"""Posting trust signals and cross-source dedupe (plan 212 S2.2).

Deterministic, explainable, reversible. A posting is only auto-collapsed
when the evidence is strong (same canonical URL, or same organisation +
near-identical title and a compatible location); weaker pairs stay
proposals in ``trust_flags.duplicate_candidate`` until an admin merges or
clears them. Nothing here calls a model, and nothing labels a posting a
scam — the signals are factual counts and dates.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.posting_model import JobPosting

AUTO_MERGE_SCORE = 0.85
CANDIDATE_SCORE = 0.6
MAX_CANDIDATES = 3
MAX_GROUP_SIZE = 500

_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "for",
    "of",
    "to",
    "in",
    "at",
    "on",
    "with",
    "m",
    "f",
    "d",
    "all",
    "genders",
    "w",
    "x",
    "remote",
    "hybrid",
    "onsite",
}
_NON_WORD = re.compile(r"[^a-z0-9]+")


def _normalise(text: str | None) -> str:
    return " ".join(_NON_WORD.sub(" ", (text or "").lower()).split())


def _tokens(title: str) -> set[str]:
    return {
        token for token in _normalise(title).split() if token not in _STOPWORDS and len(token) > 1
    }


def _url_key(url: str | None) -> str:
    raw = (url or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"^https?://", "", raw)
    raw = re.sub(r"^www\.", "", raw)
    raw = raw.split("#", 1)[0].split("?", 1)[0]
    return raw.rstrip("/")


def _location(posting: JobPosting) -> tuple[str, str] | None:
    location = posting.location or {}
    city = _normalise(str(location.get("city") or ""))
    country = _normalise(str(location.get("country") or ""))
    if city:
        return ("city", f"{city}|{country}")
    if country:
        return ("country", country)
    if location.get("remote"):
        return ("remote", "")
    return None


def _location_state(a: JobPosting, b: JobPosting) -> str:
    left, right = _location(a), _location(b)
    if left is None or right is None:
        return "unknown"
    if left == right:
        return "same"
    if left[0] == right[0] == "remote":
        return "same"
    return "conflict"


def _title_similarity(a: JobPosting, b: JobPosting) -> float:
    left, right = _tokens(a.title), _tokens(b.title)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _org_match(a: JobPosting, b: JobPosting) -> bool:
    if a.org_id is not None and b.org_id is not None:
        return a.org_id == b.org_id
    left, right = _normalise(a.org), _normalise(b.org)
    return bool(left) and left == right


def _salary_state(a: JobPosting, b: JobPosting) -> str:
    """Salary-range overlap ≥ 0.8 (plan §3.7), only when comparable."""
    if a.salary_currency and b.salary_currency and a.salary_currency != b.salary_currency:
        return "unknown"
    a_low = a.salary_normalized_min if a.salary_normalized_min is not None else a.salary_min
    a_high = a.salary_normalized_max if a.salary_normalized_max is not None else a.salary_max
    b_low = b.salary_normalized_min if b.salary_normalized_min is not None else b.salary_min
    b_high = b.salary_normalized_max if b.salary_normalized_max is not None else b.salary_max
    if (a_low is None and a_high is None) or (b_low is None and b_high is None):
        return "unknown"
    if a_low is None:
        a_low = a_high
    if a_high is None:
        a_high = a_low
    if b_low is None:
        b_low = b_high
    if b_high is None:
        b_high = b_low
    assert a_low is not None and a_high is not None
    assert b_low is not None and b_high is not None
    a_low = float(a_low)
    a_high = float(a_high)
    b_low = float(b_low)
    b_high = float(b_high)
    union = max(a_high, b_high) - min(a_low, b_low)
    if union <= 0:
        return "same"
    overlap = max(0.0, min(a_high, b_high) - max(a_low, b_low))
    return "same" if overlap / union >= 0.8 else "conflict"


def duplicate_score(a: JobPosting, b: JobPosting) -> tuple[float, str] | None:
    """Return ``(score, reason)`` for a possible duplicate pair, else None.

    Conservative by design: a conflicting city/country or a different
    organisation drops the pair instead of producing a low-confidence guess.
    """
    if a.id == b.id:
        return None
    left_url, right_url = _url_key(a.url), _url_key(b.url)
    if left_url and left_url == right_url and "/" in left_url:
        # The canonical URL is the strongest signal and crosses organisations
        # and geo labels (aggregators often rewrite one of them).
        return (0.97, "same_url")
    if not _org_match(a, b):
        return None
    location = _location_state(a, b)
    if location == "conflict":
        return None
    if _salary_state(a, b) == "conflict":
        return None
    title = _title_similarity(a, b)
    if title >= 0.9 and location == "same":
        return (0.9, "title_location")
    if title >= 0.75 and location == "same":
        return (0.78, "title_location_loose")
    if title >= 0.9 and location == "unknown":
        return (0.72, "title_org")
    if title >= 0.6 and location == "same":
        return (0.62, "title_loose")
    return None


def _candidate_payload(posting: JobPosting, score: float, reason: str) -> dict[str, Any]:
    return {
        "posting_id": str(posting.id),
        "ref": posting.ref or "",
        "title": posting.title,
        "org": posting.org,
        "score": round(score, 3),
        "reason": reason,
    }


async def _clear_candidates(db: AsyncSession, postings: list[JobPosting]) -> None:
    for posting in postings:
        flags = dict(posting.trust_flags or {})
        if "duplicate_candidate" in flags:
            flags.pop("duplicate_candidate")
            posting.trust_flags = flags
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(posting, "trust_flags")


async def _loaded_postings(db: AsyncSession) -> list[JobPosting]:
    rows = await db.execute(
        select(JobPosting)
        .where(JobPosting.status != "hidden")
        .order_by(JobPosting.created_at.asc(), JobPosting.id.asc())
    )
    return list(rows.scalars().all())


def _collapse_chains(postings: list[JobPosting]) -> None:
    by_id = {posting.id: posting for posting in postings}
    for posting in postings:
        root = posting
        seen: set[uuid.UUID] = set()
        while root.duplicate_of_id is not None and root.id not in seen:
            seen.add(root.id)
            parent = by_id.get(root.duplicate_of_id)
            if parent is None:
                break
            root = parent
        if root is not posting and root.id != posting.duplicate_of_id:
            posting.duplicate_of_id = root.id


async def scan_duplicates(db: AsyncSession, *, dry_run: bool = False) -> dict:
    """Recompute cross-source duplicate proposals and auto-merges.

    Idempotent: candidate lists are rebuilt from scratch and an existing
    ``duplicate_of_id`` is never cleared here (manual merges survive).
    """
    postings = await _loaded_postings(db)
    candidates = [posting for posting in postings if posting.duplicate_of_id is None]
    await _clear_candidates(db, candidates)

    groups: dict[tuple[str, str], list[JobPosting]] = defaultdict(list)
    url_groups: dict[str, list[JobPosting]] = defaultdict(list)
    for posting in candidates:
        if posting.org_id is not None:
            groups[("org_id", str(posting.org_id))].append(posting)
        elif _normalise(posting.org):
            groups[("org", _normalise(posting.org))].append(posting)
        url_key = _url_key(posting.url)
        if url_key:
            url_groups[url_key].append(posting)

    processed: set[tuple[uuid.UUID, uuid.UUID]] = set()

    def consider(canonical: JobPosting, other: JobPosting) -> None:
        pair = (min(canonical.id, other.id), max(canonical.id, other.id))
        if pair in processed:
            return
        processed.add(pair)
        if canonical.duplicate_of_id is not None or other.duplicate_of_id is not None:
            return
        scored = duplicate_score(canonical, other)
        if scored is None:
            return
        score, reason = scored
        if score >= AUTO_MERGE_SCORE:
            if str(canonical.id) in (other.trust_flags or {}).get("duplicate_suppressed", []):
                return
            other.duplicate_of_id = canonical.id
            return
        if score >= CANDIDATE_SCORE:
            flags = dict(other.trust_flags or {})
            existing = flags.get("duplicate_candidate", [])
            if len(existing) >= MAX_CANDIDATES:
                return
            flags["duplicate_candidate"] = [
                *existing,
                _candidate_payload(canonical, score, reason),
            ]
            other.trust_flags = flags
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(other, "trust_flags")

    skipped_groups = 0
    bounded_groups: list[list[JobPosting]] = []
    for group in list(url_groups.values()) + list(groups.values()):
        if len(group) > MAX_GROUP_SIZE:
            skipped_groups += 1
            group = group[:MAX_GROUP_SIZE]
        bounded_groups.append(group)
    for group in bounded_groups:
        for index, canonical in enumerate(group):
            if canonical.duplicate_of_id is not None:
                continue
            for other in group[index + 1 :]:
                consider(canonical, other)
    _collapse_chains(postings)
    merged = sum(1 for posting in postings if posting.duplicate_of_id is not None)
    proposed = sum(
        len((posting.trust_flags or {}).get("duplicate_candidate", []))
        for posting in postings
        if posting.duplicate_of_id is None
    )
    if dry_run:
        await db.rollback()
        return {"merged": merged, "proposed": proposed, "dry_run": True}
    await db.flush()
    await db.commit()
    return {
        "merged": merged,
        "proposed": proposed,
        "skipped_groups": skipped_groups,
        "dry_run": False,
    }


async def overview(db: AsyncSession, *, limit: int = 100) -> dict:
    postings = await _loaded_postings(db)
    candidates: list[dict] = []
    duplicates: list[dict] = []
    canonical: list[dict] = []
    for posting in postings:
        if posting.duplicate_of_id is not None:
            duplicates.append(
                {
                    "id": str(posting.id),
                    "ref": posting.ref or "",
                    "title": posting.title,
                    "org": posting.org,
                    "duplicate_of_id": str(posting.duplicate_of_id),
                }
            )
            continue
        if posting.repost_count > 0:
            canonical.append(
                {
                    "id": str(posting.id),
                    "ref": posting.ref or "",
                    "title": posting.title,
                    "org": posting.org,
                    "repost_count": posting.repost_count,
                    "last_verified_at": posting.last_verified_at.isoformat()
                    if posting.last_verified_at
                    else None,
                }
            )
        for hint in (posting.trust_flags or {}).get("duplicate_candidate", []):
            candidates.append(
                {
                    "id": str(posting.id),
                    "ref": posting.ref or "",
                    "title": posting.title,
                    "org": posting.org,
                    "candidates": [hint],
                }
            )
    return {
        "canonical": canonical[:limit],
        "duplicates": duplicates[:limit],
        "candidates": candidates[:limit],
        "counts": {
            "canonical": len(canonical),
            "duplicates": len(duplicates),
            "candidates": len(candidates),
        },
    }


async def merge_duplicate(
    db: AsyncSession, duplicate_id: uuid.UUID, canonical_id: uuid.UUID
) -> JobPosting:
    duplicate = await db.get(JobPosting, duplicate_id)
    canonical = await db.get(JobPosting, canonical_id)
    if duplicate is None:
        raise NotFoundError("Posting not found")
    if canonical is None:
        raise NotFoundError("Canonical posting not found")
    if duplicate.id == canonical.id:
        raise ValidationError("A posting cannot duplicate itself")
    root = canonical
    seen: set[uuid.UUID] = set()
    while root.duplicate_of_id is not None:
        if root.id in seen:
            break
        seen.add(root.id)
        next_root = await db.get(JobPosting, root.duplicate_of_id)
        if next_root is None:
            break
        root = next_root
    if root.id == duplicate.id:
        raise ValidationError("That merge would create a duplicate cycle")
    previous = duplicate.duplicate_of_id
    duplicate.duplicate_of_id = root.id
    flags = dict(duplicate.trust_flags or {})
    flags.pop("duplicate_candidate", None)
    flags["duplicate_suppressed"] = [
        value for value in flags.get("duplicate_suppressed", []) if value != str(root.id)
    ]
    if not flags["duplicate_suppressed"]:
        flags.pop("duplicate_suppressed")
    duplicate.trust_flags = flags
    from sqlalchemy.orm.attributes import flag_modified

    from app.services.postings.change_journal import PostingChangeJournal

    PostingChangeJournal.record(
        db,
        duplicate.id,
        "manual",
        operation={"action": "merge_duplicate"},
        before={"duplicate_of_id": str(previous) if previous else None},
        after={"duplicate_of_id": str(root.id)},
    )
    flag_modified(duplicate, "trust_flags")
    await db.flush()
    await db.commit()
    await db.refresh(duplicate)
    return duplicate


async def clear_duplicate(db: AsyncSession, posting_id: uuid.UUID) -> JobPosting:
    posting = await db.get(JobPosting, posting_id)
    if posting is None:
        raise NotFoundError("Posting not found")
    previous = posting.duplicate_of_id
    posting.duplicate_of_id = None
    if previous is not None:
        flags = dict(posting.trust_flags or {})
        suppressed = [
            value for value in flags.get("duplicate_suppressed", []) if value != str(previous)
        ]
        suppressed.append(str(previous))
        flags["duplicate_suppressed"] = suppressed[-10:]
        posting.trust_flags = flags
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(posting, "trust_flags")
    from app.services.postings.change_journal import PostingChangeJournal

    PostingChangeJournal.record(
        db,
        posting.id,
        "manual",
        operation={"action": "clear_duplicate"},
        before={"duplicate_of_id": str(previous) if previous else None},
        after={"duplicate_of_id": None},
    )
    await db.flush()
    await db.commit()
    await db.refresh(posting)
    return posting
