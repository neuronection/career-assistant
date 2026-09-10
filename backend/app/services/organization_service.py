"""Organizations service: matcher, lifecycle, merge.

Postings and experience items create/propose organizations on ingest;
this module owns the matcher that keeps the entity deduplicated — exact
slug, then case-insensitive name/alias, then dialect-safe pure-Python
trigram similarity (the target-mode precedent, never pg_trgm so
desktop SQLite behaves identically). Lifecycle mirrors skills (21):
proposed → active via admin promotion, duplicates merged (references
re-pointed, aliases folded, loser deprecated — never deleted).
"""

import re
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.experience_model import Organization
from app.models.posting_model import JobPosting

TRIGRAM = re.compile(r"[a-z0-9]+")
# Corporate/legal suffixes dropped before comparison — "Acme Cloud GmbH"
# and "Acme Cloud" are the same employer everywhere.
LEGAL_SUFFIXES = {
    "gmbh",
    "mbh",
    "ag",
    "kg",
    "ohg",
    "ltd",
    "limited",
    "llc",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "sa",
    "sas",
    "srl",
    "spa",
    "bv",
    "nv",
    "plc",
    "oy",
    "ab",
    "as",
    "pty",
}
# Jaccard overlap on padded token trigrams; above this, names merge.
MATCH_THRESHOLD = 0.82


def _canonical(name: str) -> str:
    tokens = [
        token for token in TRIGRAM.findall(name.lower()) if token not in LEGAL_SUFFIXES
    ]
    return " ".join(tokens)


def _trigrams(text: str) -> set[str]:
    grams: set[str] = set()
    for token in TRIGRAM.findall(text.lower()):
        padded = f"  {token} "
        grams.update(padded[i : i + 3] for i in range(len(padded) - 2))
    return grams


def trigram_similarity(a: str, b: str) -> float:
    ga, gb = _trigrams(a), _trigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


class OrganizationService:
    """Matcher + lifecycle over one shared organizations table."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _candidates(self) -> list[Organization]:
        rows = await self.db.execute(
            select(Organization).where(Organization.status != "deprecated")
        )
        return list(rows.scalars().all())

    def _best_match(
        self, name: str, candidates: list[Organization]
    ) -> Optional[tuple[Organization, float]]:
        """Exact slug → canonical name/alias equality → best trigram ≥
        threshold, all compared on the legal-suffix-stripped form."""
        from app.services.experience_service import slugify_org

        key = slugify_org(name)
        canonical = _canonical(name)
        best: Optional[tuple[Organization, float]] = None
        for candidate in candidates:
            names = [candidate.name, *(candidate.aliases or [])]
            if candidate.key == key:
                return candidate, 1.0
            if any(_canonical(alias) == canonical for alias in names):
                return candidate, 1.0
            score = max(
                trigram_similarity(canonical, _canonical(alias)) for alias in names
            )
            if score >= MATCH_THRESHOLD and (best is None or score > best[1]):
                best = (candidate, score)
        return best

    async def resolve(self, name: str) -> Optional[Organization]:
        """The org a raw label belongs to (None when nothing matches)."""
        name = (name or "").strip()
        if not name:
            return None
        match = self._best_match(name, await self._candidates())
        return match[0] if match else None

    async def find_or_propose(
        self, name: str, *, provenance: Optional[dict] = None
    ) -> tuple[Organization, bool]:
        """Matcher-first find-or-propose (never duplicates on ingest)."""
        name = (name or "").strip()
        if not name:
            raise ValidationError("Organization name is required")
        match = self._best_match(name, await self._candidates())
        if match is not None:
            org = match[0]
            if (
                name.strip().lower()
                not in {alias.strip().lower() for alias in (org.aliases or [])}
                and name.strip().lower() != (org.name or "").strip().lower()
            ):
                org.aliases = [*(org.aliases or []), name.strip()[:200]]
            return org, False
        from app.services.experience_service import slugify_org

        org = Organization(
            key=slugify_org(name),
            name=name[:200],
            status="proposed",
            provenance=provenance or {},
        )
        self.db.add(org)
        await self.db.flush()
        return org, True

    async def attach_to_posting(self, posting: JobPosting) -> None:
        """Match the raw label → org_id (ingest hook; raw kept for audit)."""
        if not (posting.org or "").strip():
            return
        org, _created = await self.find_or_propose(
            posting.org, provenance={"source": "posting", "posting_id": str(posting.id)}
        )
        posting.org_id = org.id

    async def backfill_postings(self) -> dict:
        """Attach orgs to postings ingested before the matcher existed."""
        rows = await self.db.execute(
            select(JobPosting).where(
                JobPosting.org_id.is_(None),
                func.length(func.trim(JobPosting.org)) > 0,
            )
        )
        postings = list(rows.scalars().all())
        matched = proposed = 0
        for posting in postings:
            org, created = await self.find_or_propose(
                posting.org,
                provenance={"source": "backfill", "posting_id": str(posting.id)},
            )
            posting.org_id = org.id
            matched += 1
            proposed += int(created)
        await self.db.commit()
        return {"matched": matched, "proposed": proposed}

    async def list_orgs(
        self,
        *,
        status: Optional[str] = None,
        q: Optional[str] = None,
    ) -> list[dict]:
        """Admin listing with live posting counts (top-hiring visibility)."""
        query = select(Organization).order_by(Organization.created_at.desc())
        if status:
            query = query.where(Organization.status == status)
        if q:
            query = query.where(Organization.name.ilike(f"%{q}%"))
        rows = list((await self.db.execute(query)).scalars().all())
        counts = dict(
            (
                await self.db.execute(
                    select(JobPosting.org_id, func.count())
                    .where(JobPosting.org_id.is_not(None))
                    .group_by(JobPosting.org_id)
                )
            ).all()
        )
        return [
            {
                "id": str(org.id),
                "key": org.key,
                "name": org.name,
                "domain": org.domain,
                "aliases": org.aliases or [],
                "status": org.status,
                "posting_count": int(counts.get(org.id, 0)),
            }
            for org in rows
        ]

    async def get_org(self, org_id: UUID) -> Organization:
        org = (
            (
                await self.db.execute(
                    select(Organization).where(Organization.id == org_id)
                )
            )
            .scalars()
            .first()
        )
        if org is None:
            raise NotFoundError("Organization not found")
        return org

    async def promote(self, org_id: UUID) -> Organization:
        """proposed → active (the only promotion path, like skills)."""
        org = await self.get_org(org_id)
        if org.status != "proposed":
            raise ValidationError("Only proposed organizations can be promoted")
        org.status = "active"
        self.db.add(org)
        await self.db.commit()
        await self.db.refresh(org)
        return org

    async def add_alias(self, org_id: UUID, alias: str) -> Organization:
        org = await self.get_org(org_id)
        alias = (alias or "").strip()[:200]
        if not alias:
            raise ValidationError("Alias is required")
        aliases = [*(org.aliases or [])]
        if alias.lower() not in {a.strip().lower() for a in aliases}:
            aliases.append(alias)
            org.aliases = aliases
            self.db.add(org)
            await self.db.commit()
            await self.db.refresh(org)
        return org

    async def merge(self, org_id: UUID, target_id: UUID) -> Organization:
        """Re-point references to the target and deprecate the duplicate."""
        if org_id == target_id:
            raise ValidationError("Cannot merge an organization into itself")
        source = await self.get_org(org_id)
        target = await self.get_org(target_id)
        if target.status == "deprecated":
            raise ValidationError("Cannot merge into a deprecated organization")
        rows = await self.db.execute(
            select(JobPosting).where(JobPosting.org_id == source.id)
        )
        moved = 0
        for posting in rows.scalars().all():
            posting.org_id = target.id
            moved += 1
        aliases = [*(target.aliases or [])]
        for alias in [source.name, *(source.aliases or [])]:
            if alias and alias.lower() not in {a.lower() for a in aliases}:
                aliases.append(alias)
        target.aliases = aliases
        source.status = "deprecated"
        provenance = dict(source.provenance or {})
        provenance["merged_into"] = str(target.id)
        source.provenance = provenance
        self.db.add(target)
        self.db.add(source)
        await self.db.commit()
        await self.db.refresh(target)
        return target
