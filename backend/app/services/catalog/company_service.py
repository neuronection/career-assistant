"""Company section: reviewed profiles + derived hiring stats (plan 129).

Reads derive everything the postings prove — open counts, seniority and
onsite splits, top locations — at query time, never stored. Writes are
the admin-reviewed facts (``CompanyProfileIn``). Unknown stays None, on
the same clarity doctrine as the posting extract.
"""

from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.company_model import CompanyProfile
from app.models.enums import CompanyProfileSource
from app.models.experience_model import Organization
from app.models.posting_model import JobPosting
from app.schemas.company import (
    CompanyDerivedStats,
    CompanyDetailOut,
    CompanyLink,
    CompanyOut,
    CompanyPostingOut,
    CompanyProfileIn,
    FinancialClaim,
    LocationCount,
)
from app.services.postings.explore_service import OPEN_STATUSES


class CompanyService:
    """The company section over the normalized org entity (1:1 profiles)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_companies(self, *, q: str | None = None, limit: int = 200) -> list[CompanyOut]:
        """Companies with open postings, busiest first (catalog scale)."""
        counts = (
            select(JobPosting.org_id, func.count().label("open_postings"))
            .where(JobPosting.org_id.is_not(None), JobPosting.status.in_(OPEN_STATUSES))
            .group_by(JobPosting.org_id)
            .subquery()
        )
        query = (
            select(Organization, CompanyProfile, func.coalesce(counts.c.open_postings, 0))
            .outerjoin(CompanyProfile, CompanyProfile.organization_id == Organization.id)
            .outerjoin(counts, counts.c.org_id == Organization.id)
            .where(
                Organization.status.in_(["active", "proposed"]),
                counts.c.open_postings.is_not(None),
            )
            .order_by(desc(func.coalesce(counts.c.open_postings, 0)), Organization.name.asc())
            .limit(max(1, min(limit, 500)))
        )
        if q and q.strip():
            query = query.where(Organization.name.ilike(f"%{q.strip()}%"))
        rows = (await self.db.execute(query)).all()
        return [self._to_out(org, profile, int(count)) for org, profile, count in rows]

    async def get_company(self, key: str) -> CompanyDetailOut:
        """One company: reviewed facts plus the derived hiring stats."""
        org, profile, open_count = await self._load(key)
        return await self._to_detail(org, profile, open_count)

    async def postings(self, key: str, *, limit: int = 50) -> list[CompanyPostingOut]:
        """The company's open postings, freshest first."""
        org = await self._org_by_key(key)
        rows = (
            (
                await self.db.execute(
                    select(JobPosting)
                    .where(
                        JobPosting.org_id == org.id,
                        JobPosting.status.in_(OPEN_STATUSES),
                    )
                    .order_by(desc(JobPosting.posted_at), desc(JobPosting.created_at))
                    .limit(max(1, min(limit, 200)))
                )
            )
            .scalars()
            .all()
        )
        return [CompanyPostingOut.model_validate(p) for p in rows]

    async def upsert_profile(self, key: str, data: CompanyProfileIn) -> CompanyDetailOut:
        """Admin write: replace the reviewed facts wholesale (omit = clear)."""
        org = await self._org_by_key(key)
        profile = (
            await self.db.execute(
                select(CompanyProfile).where(CompanyProfile.organization_id == org.id)
            )
        ).scalar_one_or_none()
        if profile is None:
            profile = CompanyProfile(organization_id=org.id)
            self.db.add(profile)
        profile.company_type = data.company_type.value if data.company_type else None
        profile.industry_tags = [t.strip() for t in data.industry_tags]
        profile.employees_min = data.employees_min
        profile.employees_max = data.employees_max
        profile.hq_city = data.hq_city
        profile.hq_country = data.hq_country
        profile.founded_year = data.founded_year
        profile.description = data.description
        profile.financials = [claim.model_dump(mode="json") for claim in data.financials]
        profile.links = [link.model_dump(mode="json") for link in data.links]
        profile.source = CompanyProfileSource.MANUAL.value
        profile.needs_review = data.needs_review
        await self.db.commit()
        return await self.get_company(key)

    async def _org_by_key(self, key: str) -> Organization:
        org = (
            await self.db.execute(select(Organization).where(Organization.key == key))
        ).scalar_one_or_none()
        if org is None:
            raise NotFoundError(f"Company not found: {key}")
        return org

    async def _load(self, key: str) -> tuple[Organization, CompanyProfile | None, int]:
        org = await self._org_by_key(key)
        profile = (
            await self.db.execute(
                select(CompanyProfile).where(CompanyProfile.organization_id == org.id)
            )
        ).scalar_one_or_none()
        open_count = int(
            (
                await self.db.execute(
                    select(func.count()).where(
                        JobPosting.org_id == org.id, JobPosting.status.in_(OPEN_STATUSES)
                    )
                )
            ).scalar_one()
        )
        return org, profile, open_count

    async def _to_detail(
        self, org: Organization, profile: CompanyProfile | None, open_count: int
    ) -> CompanyDetailOut:
        out = self._to_out(org, profile, open_count)
        derived = CompanyDerivedStats(open_postings=open_count)
        from app.services.catalog.organization_service import OrganizationService

        aliases = await OrganizationService(self.db).alias_strings([org.id])
        rows = (
            await self.db.execute(
                select(
                    JobPosting.seniority,
                    JobPosting.onsite_policy,
                    JobPosting.location,
                    JobPosting.posted_at,
                ).where(JobPosting.org_id == org.id, JobPosting.status.in_(OPEN_STATUSES))
            )
        ).all()
        seniority: dict[str, int] = {}
        onsite: dict[str, int] = {}
        locations: dict[tuple[str | None, str | None], int] = {}
        latest: datetime | None = None
        for seniority_value, onsite_value, location, posted_at in rows:
            if seniority_value:
                seniority[seniority_value] = seniority.get(seniority_value, 0) + 1
            if onsite_value:
                onsite[onsite_value] = onsite.get(onsite_value, 0) + 1
            if isinstance(location, dict) and (location.get("city") or location.get("country")):
                spot = (location.get("city"), location.get("country"))
                locations[spot] = locations.get(spot, 0) + 1
            if posted_at is not None and (latest is None or posted_at > latest):
                latest = posted_at
        derived.by_seniority = seniority
        derived.by_onsite_policy = onsite
        derived.top_locations = [
            LocationCount(city=city, country=country, count=count)
            for (city, country), count in sorted(locations.items(), key=lambda item: -item[1])[:8]
        ]
        derived.latest_posted_at = latest
        return CompanyDetailOut(
            **out.model_dump(),
            description=(profile.description if profile else "") or "",
            aliases=aliases.get(org.id, []),
            financials=(
                [FinancialClaim.model_validate(claim) for claim in profile.financials]
                if profile
                else []
            ),
            links=[CompanyLink.model_validate(link) for link in (profile.links if profile else [])],
            needs_review=bool(profile.needs_review) if profile else False,
            derived=derived,
        )

    def _to_out(
        self, org: Organization, profile: CompanyProfile | None, open_count: int
    ) -> CompanyOut:
        return CompanyOut(
            key=org.key,
            name=org.name,
            domain=org.domain,
            status=org.status,
            company_type=(profile.company_type if profile and profile.company_type else None),
            industry_tags=list(profile.industry_tags) if profile else [],
            employees_min=profile.employees_min if profile else None,
            employees_max=profile.employees_max if profile else None,
            hq_city=profile.hq_city if profile else None,
            hq_country=profile.hq_country if profile else None,
            founded_year=profile.founded_year if profile else None,
            open_postings=open_count,
            has_profile=profile is not None,
        )
