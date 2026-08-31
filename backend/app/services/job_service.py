from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.models.job_model import Job, JobFamily, JobRelation, JobSkill, JobTag
from app.models.taxonomy_model import InterestTag, Skill
from app.models.user_model import User
from app.schemas.job import JobAttributes, JobCreate, JobSkillIn, JobUpdate

# Every Job → JobOut conversion needs these loaded (async: no lazy loads).
JOB_LOAD_OPTIONS = (
    selectinload(Job.family),
    selectinload(Job.tag_links).selectinload(JobTag.tag),
    selectinload(Job.skill_links).selectinload(JobSkill.skill),
)


class JobService:
    """Catalog CRUD, tree/graph queries and filtering."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def families(self) -> list[JobFamily]:
        """All families ordered by path."""
        rows = await self.db.execute(select(JobFamily).order_by(JobFamily.path))
        return list(rows.scalars().all())

    async def family_tree(self) -> list[dict]:
        """Families as a nested tree with published job counts."""
        families = await self.families()
        counts_rows = await self.db.execute(
            select(Job.family_id, func.count(Job.id))
            .where(Job.status == "published")
            .group_by(Job.family_id)
        )
        counts = {fid: n for fid, n in counts_rows.all()}
        nodes = {
            f.id: {
                **self._family_out(f),
                "job_count": counts.get(f.id, 0),
                "children": [],
            }
            for f in families
        }
        roots: list[dict] = []
        for f in families:
            node = nodes[f.id]
            if f.parent_id and f.parent_id in nodes:
                nodes[f.parent_id]["children"].append(node)
            else:
                roots.append(node)
        return roots

    @staticmethod
    def _family_out(f: JobFamily) -> dict:
        return {
            "id": f.id,
            "key": f.key,
            "label": f.label,
            "parent_id": f.parent_id,
            "path": f.path,
            "level": f.level,
            "description": f.description,
        }

    async def get_by_code_or_id(self, ref: str | UUID) -> Job | None:
        """Fetch a job by UUID or code slug."""
        query = select(Job).options(*JOB_LOAD_OPTIONS)
        if isinstance(ref, UUID):
            query = query.where(Job.id == ref)
        else:
            query = query.where(Job.code == ref)
        rows = await self.db.execute(query)
        return rows.scalars().first()

    async def require_job(self, ref: str | UUID) -> Job:
        """Fetch a job or raise NotFoundError."""
        job = await self.get_by_code_or_id(ref)
        if job is None:
            raise NotFoundError("Job not found")
        return job

    async def list_jobs(
        self,
        *,
        q: str | None = None,
        family_key: str | None = None,
        interest_keys: list[str] | None = None,
        demand: str | None = None,
        education_level: str | None = None,
        environment: str | None = None,
        source: str | None = None,
        status: str | None = "published",
        min_salary: int | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[Job], int]:
        """Filtered, paginated job listing."""
        conditions = []
        if status:
            conditions.append(Job.status == status)
        if source:
            conditions.append(Job.source == source)
        if q:
            pattern = f"%{q.strip()}%"
            conditions.append(
                or_(
                    Job.title.ilike(pattern),
                    Job.short_description.ilike(pattern),
                    Job.code.ilike(pattern),
                )
            )
        if family_key:
            families = await self.families()
            family = next((f for f in families if f.key == family_key), None)
            if family is None:
                raise NotFoundError("Family not found")
            descendant_ids = [f.id for f in families if f.path.startswith(family.path)]
            conditions.append(Job.family_id.in_(descendant_ids))
        if interest_keys:
            conditions.append(
                Job.id.in_(
                    select(JobTag.job_id)
                    .join(InterestTag, InterestTag.id == JobTag.interest_tag_id)
                    .where(InterestTag.key.in_(interest_keys))
                )
            )

        # JSON-path predicates run Python-side so the query stays portable
        # across PostgreSQL and SQLite (the catalog is small at self-host
        # scale; see dev/plans/10-desktop-shell.md).
        predicates: list = []
        if demand:
            predicates.append(
                lambda a: (a.get("demand") or {}).get("outlook") == demand
            )
        if education_level:
            predicates.append(
                lambda a: (a.get("education") or {}).get("level") == education_level
            )
        if environment:
            predicates.append(lambda a: environment in (a.get("environments") or []))
        if min_salary is not None:

            def salary_ok(attrs: dict, floor: int = min_salary) -> bool:
                median = (attrs.get("salary") or {}).get("median")
                try:
                    return len(median) > 1 and int(median[1]) >= floor
                except (TypeError, ValueError):
                    return False

            predicates.append(salary_ok)

        query = select(Job).options(*JOB_LOAD_OPTIONS).order_by(Job.title)
        if conditions:
            query = query.where(*conditions)

        if not predicates:
            count_query = select(func.count(Job.id))
            if conditions:
                count_query = count_query.where(*conditions)
            total = (await self.db.execute(count_query)).scalar() or 0
            rows = await self.db.execute(
                query.offset((page - 1) * page_size).limit(page_size)
            )
            return list(rows.scalars().unique().all()), total

        rows = await self.db.execute(query)
        matches = [
            job
            for job in rows.scalars().unique().all()
            if all(p(job.attributes or {}) for p in predicates)
        ]
        total = len(matches)
        start = (page - 1) * page_size
        return matches[start : start + page_size], total

    async def _get_with_family(self, job_id) -> Job:
        """Re-fetch a job with links eagerly loaded."""
        rows = await self.db.execute(
            select(Job).options(*JOB_LOAD_OPTIONS).where(Job.id == job_id)
        )
        return rows.scalars().unique().one()

    async def create(
        self,
        data: JobCreate,
        user: User | None,
        source: str = "user",
        status: str = "draft",
    ) -> Job:
        """Create a job; validates family/taxonomy keys and writes links.

        New entries land as drafts (human review before publishing, whether
        hand-written or AI-generated); publishing is an explicit step.
        """
        family = await self._require_family(data.family_key)
        job = Job(
            code=data.code,
            title=data.title,
            family_id=family.id,
            short_description=data.short_description,
            status=status,
            source=source,
            created_by=user.id if user else None,
            attributes=data.attributes.model_dump(mode="json"),
            links=[link.model_dump(mode="json") for link in data.links],
        )
        self.db.add(job)
        await self.db.flush()
        link_source = "ai" if source == "ai" else "admin"
        await self._write_links(
            job.id,
            data.interest_keys,
            data.skills,
            source=link_source,
        )
        await self.db.commit()
        return await self._get_with_family(job.id)

    async def _write_links(
        self,
        job_id: UUID,
        interest_keys: list[str] | None,
        skills: list[JobSkillIn] | None,
        *,
        source: str,
    ) -> None:
        """Replace the job's interest/skill links (validated keys)."""
        if interest_keys is not None:
            tags = {
                t.key: t
                for t in (
                    await self.db.execute(
                        select(InterestTag).where(InterestTag.key.in_(interest_keys))
                    )
                )
                .scalars()
                .all()
            }
            missing = [k for k in interest_keys if k not in tags]
            if missing:
                raise ValidationError(f"Unknown interest keys: {', '.join(missing)}")
            await self.db.execute(
                JobTag.__table__.delete().where(JobTag.job_id == job_id)
            )
            for key in interest_keys:
                self.db.add(
                    JobTag(job_id=job_id, interest_tag_id=tags[key].id, source=source)
                )
        if skills is not None:
            skill_rows = {
                s.key: s
                for s in (
                    await self.db.execute(
                        select(Skill).where(
                            Skill.key.in_([s.skill_key for s in skills])
                        )
                    )
                )
                .scalars()
                .all()
            }
            missing = [s.skill_key for s in skills if s.skill_key not in skill_rows]
            if missing:
                raise ValidationError(f"Unknown skill keys: {', '.join(missing)}")
            await self.db.execute(
                JobSkill.__table__.delete().where(JobSkill.job_id == job_id)
            )
            for requirement in skills:
                self.db.add(
                    JobSkill(
                        job_id=job_id,
                        skill_id=skill_rows[requirement.skill_key].id,
                        required_level=requirement.required_level,
                        importance=requirement.importance.value,
                        rationale=requirement.rationale,
                        source=source,
                    )
                )
        await self.db.flush()

    async def update(self, ref: str | UUID, data: JobUpdate, user: User) -> Job:
        """Update a job the user owns (AI/user sourced) or any field allowed."""
        job = await self.require_job(ref)
        if job.source == "seed" and not user.is_active:
            raise PermissionDeniedError("Cannot edit seeded jobs")
        was_published = job.status == "published"
        payload = data.model_dump(exclude_none=True)
        if "family_key" in payload:
            family = await self._require_family(payload.pop("family_key"))
            job.family_id = family.id
        if "attributes" in payload:
            attrs = payload.pop("attributes")
            job.attributes = JobAttributes.model_validate(attrs).model_dump(mode="json")
        if "links" in payload:
            job.links = payload.pop("links")
        interest_keys = payload.pop("interest_keys", None)
        skills = payload.pop("skills", None)
        if interest_keys is not None or skills is not None:
            await self._write_links(
                job.id,
                interest_keys if interest_keys is not None else None,
                [JobSkillIn.model_validate(s) for s in skills]
                if skills is not None
                else None,
                source="admin",
            )
        for field, value in payload.items():
            setattr(job, field, value.value if hasattr(value, "value") else value)
        self.db.add(job)
        await self.db.commit()
        job = await self._get_with_family(job.id)
        if job.status == "published":
            if not was_published:
                await self.notify_published(job)
            await self._refit_job(job.id)
        return job

    async def notify_published(self, job: Job) -> None:
        """Family-follow rules fire on the draft → published transition."""
        from app.services.engagement_service import EngagementService

        await EngagementService(self.db).on_job_published(job)

    async def _refit_job(self, job_id) -> None:
        """Catalog changed ⇒ deterministic fit rows refresh for every user."""
        from app.services.fit.service import FitService

        await FitService(self.db).refit_job(job_id)

    async def delete(self, ref: str | UUID, user: User) -> None:
        """Delete a non-seed job owned by the caller."""
        job = await self.require_job(ref)
        if job.source == "seed":
            raise PermissionDeniedError("Seeded jobs cannot be deleted")
        if job.created_by and job.created_by != user.id:
            raise PermissionDeniedError("Not your job")
        await self.db.delete(job)
        await self.db.commit()

    async def relations(self, ref: str | UUID) -> list[JobRelation]:
        """All relations touching a job."""
        job = await self.require_job(ref)
        rows = await self.db.execute(
            select(JobRelation)
            .options(
                selectinload(JobRelation.from_job).selectinload(Job.family),
                selectinload(JobRelation.to_job).selectinload(Job.family),
            )
            .where(
                or_(JobRelation.from_job_id == job.id, JobRelation.to_job_id == job.id)
            )
        )
        return list(rows.scalars().unique().all())

    async def graph(
        self, root: str | None, depth: int = 2, family_key: str | None = None
    ) -> dict:
        """Nodes+edges payload centred on root (or a family subset)."""
        nodes: dict[str, Job] = {}
        edges: list[JobRelation] = []
        if root:
            center = await self.require_job(root)
            frontier = [center]
            nodes[center.code] = center
            for _ in range(max(1, depth)):
                next_frontier = []
                for node in frontier:
                    rows = await self.db.execute(
                        select(JobRelation)
                        .options(
                            selectinload(JobRelation.from_job).selectinload(Job.family),
                            selectinload(JobRelation.to_job).selectinload(Job.family),
                        )
                        .where(
                            or_(
                                JobRelation.from_job_id == node.id,
                                JobRelation.to_job_id == node.id,
                            )
                        )
                    )
                    rels = list(rows.scalars().unique().all())
                    edges.extend(rels)
                    for rel in rels:
                        other = (
                            rel.to_job if rel.from_job_id == node.id else rel.from_job
                        )
                        if other.code not in nodes:
                            nodes[other.code] = other
                            next_frontier.append(other)
                frontier = next_frontier
        else:
            query = (
                select(Job)
                .options(selectinload(Job.family))
                .where(Job.status == "published")
            )
            if family_key:
                families = await self.families()
                family = next((f for f in families if f.key == family_key), None)
                if family is None:
                    raise NotFoundError("Family not found")
                descendant_ids = [
                    f.id for f in families if f.path.startswith(family.path)
                ]
                query = query.where(Job.family_id.in_(descendant_ids))
            jobs = list(
                (await self.db.execute(query.limit(200))).scalars().unique().all()
            )
            for job in jobs:
                nodes[job.code] = job
            if jobs:
                job_ids = [j.id for j in jobs]
                rows = await self.db.execute(
                    select(JobRelation)
                    .options(
                        selectinload(JobRelation.from_job).selectinload(Job.family),
                        selectinload(JobRelation.to_job).selectinload(Job.family),
                    )
                    .where(
                        JobRelation.from_job_id.in_(job_ids),
                        JobRelation.to_job_id.in_(job_ids),
                    )
                )
                edges = list(rows.scalars().unique().all())
        seen = set()
        unique_edges = []
        for edge in edges:
            key = (edge.from_job.code, edge.to_job.code, edge.relation_type)
            if key not in seen:
                seen.add(key)
                unique_edges.append(edge)
        return {
            "nodes": [
                {
                    "id": job.code,
                    "code": job.code,
                    "title": job.title,
                    "family_key": job.family.key if job.family else "",
                    "demand": (job.attributes or {}).get("demand", {}).get("outlook"),
                }
                for job in nodes.values()
            ],
            "edges": [
                {
                    "from_code": e.from_job.code,
                    "to_code": e.to_job.code,
                    "relation_type": e.relation_type,
                    "weight": e.weight,
                }
                for e in unique_edges
            ],
        }

    async def _require_family(self, key: str) -> JobFamily:
        rows = await self.db.execute(select(JobFamily).where(JobFamily.key == key))
        family = rows.scalars().first()
        if family is None:
            raise ValidationError(f"Unknown family key: {key}")
        return family

    @staticmethod
    def job_snapshot(job: Job) -> dict:
        """Compact prompt-ready snapshot of a job."""
        return {
            "code": job.code,
            "title": job.title,
            "family": job.family.key if job.family else "",
            "description": job.short_description,
            "attributes": job.attributes or {},
            "interests": [link.tag.key for link in job.tag_links],
            "skills": [
                {
                    "key": link.skill.key,
                    "required_level": link.required_level,
                    "importance": link.importance,
                }
                for link in job.skill_links
            ],
        }

    @staticmethod
    def tag_overlap(
        profile_weights: dict[str, int], job_interest_keys: list[str]
    ) -> tuple[float, list[str]]:
        """Interest-overlap base score (0..10) + overlapping keys."""
        overlap = [k for k in job_interest_keys if k in profile_weights]
        if not overlap:
            return 0.0, []
        total_weight = sum(profile_weights[k] for k in overlap)
        max_possible = 5 * len(job_interest_keys or [1])
        return min(10.0, total_weight / max(1, max_possible) * 10), overlap
