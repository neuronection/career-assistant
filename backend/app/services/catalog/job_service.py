from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Text, and_, case, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.models.enums import (
    DemandOutlook,
    EducationLevel,
    EducationLevelOrder,
    Environment,
    JobSource,
)
from app.models.job_model import Job, JobFamily, JobRelation, JobSkill, JobTag
from app.models.posting_model import JobPosting
from app.models.taxonomy_model import InterestTag, Skill
from app.models.user_model import User
from app.schemas.job import JobAttributes, JobCreate, JobSkillIn, JobUpdate

# Every Job → JobOut conversion needs these loaded (async: no lazy loads).
JOB_LOAD_OPTIONS = (
    selectinload(Job.family),
    selectinload(Job.tag_links).selectinload(JobTag.tag),
    selectinload(Job.skill_links).selectinload(JobSkill.skill),
)

JOB_SORTS = ("title", "demand", "salary", "open_roles", "family")
OPEN_POSTING_STATUSES = ("new", "mapped")
DEMAND_RANK = {
    DemandOutlook.HOT.value: 0,
    DemandOutlook.GROWING.value: 1,
    DemandOutlook.STABLE.value: 2,
    DemandOutlook.DECLINING.value: 3,
}
SKILL_FACET_SIZE = 15
INTEREST_FACET_SIZE = 20
FACET_AXES = (
    "family",
    "skills",
    "interests",
    "education",
    "demand",
    "contract",
    "schedule",
    "travel",
    "environment",
    "source",
)


async def enqueue_job_index(db: AsyncSession, job: Job) -> None:
    """Queue a ``VECTOR_INDEX`` run for one catalog job (plan 50 P2a).

    Job writes never embed inside the request: the retrieval handler owns
    composing and the gateway call, so a published or edited job reaches the
    semantic rescue on the next worker pass. The nightly reconcile is the
    backstop, never the only path.
    """
    from app.models.enums import BackgroundJobType
    from app.services.job_worker import enqueue

    await enqueue(
        db,
        BackgroundJobType.VECTOR_INDEX.value,
        {"kind": "job", "source_id": str(job.id)},
    )


CONTRACT_VALUES = (
    "permanent",
    "temporary",
    "contract",
    "freelance",
    "b2b",
    "internship",
    "apprenticeship",
)
SCHEDULE_VALUES = ("shift_work", "on_call", "nights", "weekends", "flexible")
TRAVEL_VALUES = ("none", "occasional", "frequent")


def _json_node(*path: str):
    expr: Any = Job.attributes
    for part in path:
        expr = expr[part]
    return expr


def _json_text(*path: str):
    return _json_node(*path).as_string()


def _json_array_text(*path: str):
    return func.coalesce(func.cast(_json_node(*path), Text), "")


def _array_include(values: Sequence[str], *path: str):
    text = _json_array_text(*path)
    return or_(*[text.like(f'%"{value}"%') for value in values])


def _array_exclude(values: Sequence[str], *path: str):
    return not_(_array_include(values, *path))


def _scalar_exclude(expr, values: Sequence[str]):
    return or_(expr.is_(None), expr.not_in(values))


def _skill_exists(key: str, level: int | None):
    condition = (
        select(JobSkill.id)
        .join(Skill, Skill.id == JobSkill.skill_id)
        .where(JobSkill.job_id == Job.id, Skill.key == key)
    )
    if level is not None:
        condition = condition.where(JobSkill.required_level >= level)
    return condition.exists()


def _education_rank():
    level = _json_text("education", "level")
    return case(
        *[(level == entry.value, EducationLevelOrder.ORDER[entry]) for entry in EducationLevel],
        else_=-1,
    )


async def _grouped_scalar(db: AsyncSession, scope, expr) -> dict[object, int]:
    rows = await db.execute(
        select(expr, func.count(Job.id)).where(Job.id.in_(scope)).group_by(expr)
    )
    return {key: int(count) for key, count in rows.all() if key is not None}


async def _array_facet(db: AsyncSession, scope, values: Sequence[str], *path: str):
    text = _json_array_text(*path)
    columns = [
        func.coalesce(func.sum(case((text.like(f'%"{value}"%'), 1), else_=0)), 0)
        for value in values
    ]
    row = (await db.execute(select(*columns).where(Job.id.in_(scope)))).one()
    return {value: int(count) for value, count in zip(values, row, strict=True)}


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
        counts = dict(counts_rows.all())
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
        interest_exclude: list[str] | None = None,
        demand: list[str] | None = None,
        demand_exclude: list[str] | None = None,
        education: list[str] | None = None,
        education_exclude: list[str] | None = None,
        education_min: str | None = None,
        skills: list[tuple[str, int | None]] | None = None,
        skill_exclude: list[str] | None = None,
        skill_mode: str = "all",
        skill_min_level: int | None = None,
        environment: list[str] | None = None,
        environment_exclude: list[str] | None = None,
        source: list[str] | None = None,
        source_exclude: list[str] | None = None,
        contract: list[str] | None = None,
        contract_exclude: list[str] | None = None,
        schedule: list[str] | None = None,
        schedule_exclude: list[str] | None = None,
        travel: list[str] | None = None,
        travel_exclude: list[str] | None = None,
        experience_max_years: float | None = None,
        salary_min: int | None = None,
        salary_max: int | None = None,
        has_roles: bool | None = None,
        status: str | None = "published",
        sort: str = "title",
        page: int = 1,
        page_size: int = 25,
        with_facets: bool = False,
    ) -> tuple[list[Job], int, dict[str, dict[str, int]]]:
        """Filtered, paginated catalog page with optional self-excluding facets."""
        if sort not in JOB_SORTS:
            raise ValidationError("sort must be " + "|".join(JOB_SORTS))
        if skill_mode not in ("all", "any"):
            raise ValidationError("skill_mode must be all|any")

        axis_conditions: dict[str, list] = {}

        def add(axis: str, *conditions) -> None:
            axis_conditions.setdefault(axis, []).extend(conditions)

        families = await self.families()
        if status:
            add("status", Job.status == status)
        if source:
            add("source", Job.source.in_(source))
        if source_exclude:
            add("source", Job.source.not_in(source_exclude))
        if q:
            pattern = f"%{q.strip()}%"
            add(
                "q",
                or_(
                    Job.title.ilike(pattern),
                    Job.short_description.ilike(pattern),
                    Job.code.ilike(pattern),
                ),
            )
        if family_key:
            family = next((f for f in families if f.key == family_key), None)
            if family is None:
                raise NotFoundError("Family not found")
            descendant_ids = [f.id for f in families if f.path.startswith(family.path)]
            add("family", Job.family_id.in_(descendant_ids))
        if interest_keys:
            add(
                "interests",
                Job.id.in_(
                    select(JobTag.job_id)
                    .join(InterestTag, InterestTag.id == JobTag.interest_tag_id)
                    .where(InterestTag.key.in_(interest_keys))
                ),
            )
        if interest_exclude:
            add(
                "interests",
                Job.id.not_in(
                    select(JobTag.job_id)
                    .join(InterestTag, InterestTag.id == JobTag.interest_tag_id)
                    .where(InterestTag.key.in_(interest_exclude))
                ),
            )

        skill_entries = skills or []
        excluded_skills = skill_exclude or []
        skill_keys = [key for key, _level in skill_entries] + excluded_skills
        if skill_keys:
            found = set(
                (
                    await self.db.execute(select(Skill.key).where(Skill.key.in_(skill_keys)))
                ).scalars()
            )
            unknown = sorted(set(skill_keys) - found)
            if unknown:
                raise ValidationError(f"Unknown skills: {', '.join(unknown)}")
        if skill_entries:
            include_conditions = [
                _skill_exists(key, max(level or 0, skill_min_level or 0) or None)
                for key, level in skill_entries
            ]
            add(
                "skills",
                and_(*include_conditions) if skill_mode == "all" else or_(*include_conditions),
            )
        if excluded_skills:
            add(
                "skills",
                not_(or_(*[_skill_exists(key, None) for key in excluded_skills])),
            )

        if demand:
            add("demand", _json_text("demand", "outlook").in_(demand))
        if demand_exclude:
            add("demand", _scalar_exclude(_json_text("demand", "outlook"), demand_exclude))

        if education:
            add("education", _json_text("education", "level").in_(education))
        if education_exclude:
            add(
                "education",
                _scalar_exclude(_json_text("education", "level"), education_exclude),
            )
        if education_min:
            try:
                minimum = EducationLevel(education_min)
            except ValueError as exc:
                raise ValidationError(f"Unknown education level: {education_min}") from exc
            add("education", _education_rank() >= EducationLevelOrder.ORDER[minimum])

        median = _json_node("salary", "median")
        if salary_min is not None:
            add("salary", median[1].as_integer() >= salary_min)
        if salary_max is not None:
            add("salary", median[0].as_integer() <= salary_max)

        if contract:
            add("contract", _json_text("contract_type").in_(contract))
        if contract_exclude:
            add(
                "contract",
                _scalar_exclude(_json_text("contract_type"), contract_exclude),
            )
        if schedule:
            add("schedule", _array_include(schedule, "schedule_cues"))
        if schedule_exclude:
            add("schedule", _array_exclude(schedule_exclude, "schedule_cues"))
        if travel:
            add("travel", _json_text("travel_required", "level").in_(travel))
        if travel_exclude:
            add(
                "travel",
                _scalar_exclude(_json_text("travel_required", "level"), travel_exclude),
            )
        if environment:
            add("environment", _array_include(environment, "environments"))
        if environment_exclude:
            add("environment", _array_exclude(environment_exclude, "environments"))
        if experience_max_years is not None:
            lower = _json_node("experience_typical_years")[0].as_float()
            add("experience", or_(lower.is_(None), lower <= experience_max_years))

        role_job_ids = select(JobPosting.catalog_job_id).where(
            JobPosting.status.in_(OPEN_POSTING_STATUSES)
        )
        if has_roles is True:
            add("has_roles", Job.id.in_(role_job_ids))
        elif has_roles is False:
            add("has_roles", Job.id.not_in(role_job_ids))

        conditions = [condition for group in axis_conditions.values() for condition in group]
        count_query = select(func.count(Job.id))
        if conditions:
            count_query = count_query.where(*conditions)
        total = int((await self.db.execute(count_query)).scalar() or 0)

        query = select(Job).options(*JOB_LOAD_OPTIONS)
        if conditions:
            query = query.where(*conditions)
        query = self._order_jobs(query, sort)
        rows = await self.db.execute(query.offset((page - 1) * page_size).limit(page_size))
        jobs: list[Job] = list(rows.scalars().unique().all())
        facets = await self._facets(axis_conditions, families) if with_facets else {}
        return jobs, total, facets

    @staticmethod
    def _order_jobs(query, sort: str):
        if sort == "family":
            return query.join(JobFamily, JobFamily.id == Job.family_id).order_by(
                JobFamily.path.asc(), Job.title.asc(), Job.code.asc()
            )
        if sort == "demand":
            outlook = _json_text("demand", "outlook")
            rank = case(
                *[(outlook == value, position) for value, position in DEMAND_RANK.items()],
                else_=len(DEMAND_RANK),
            )
            return query.order_by(rank.asc(), Job.code.asc())
        if sort == "salary":
            upper = _json_node("salary", "median")[1].as_integer()
            return query.order_by(upper.desc().nulls_last(), Job.code.asc())
        if sort == "open_roles":
            counts = (
                select(
                    JobPosting.catalog_job_id.label("job_id"),
                    func.count(JobPosting.id).label("open_roles"),
                )
                .where(JobPosting.status.in_(OPEN_POSTING_STATUSES))
                .group_by(JobPosting.catalog_job_id)
                .subquery()
            )
            return query.outerjoin(counts, counts.c.job_id == Job.id).order_by(
                func.coalesce(counts.c.open_roles, 0).desc(), Job.code.asc()
            )
        return query.order_by(Job.title.asc(), Job.code.asc())

    async def _facets(
        self, axis_conditions: dict[str, list], families: Sequence[JobFamily]
    ) -> dict[str, dict[str, int]]:
        """One grouped query per rendered axis, each skipping its own filter."""
        facets: dict[str, dict[str, int]] = {}
        for axis in FACET_AXES:
            scope_conditions = [
                condition
                for name, group in axis_conditions.items()
                if name != axis
                for condition in group
            ]
            scope = select(Job.id)
            if scope_conditions:
                scope = scope.where(*scope_conditions)

            if axis == "family":
                counts = await _grouped_scalar(self.db, scope, Job.family_id)
                facets["family"] = {family.key: counts.get(family.id, 0) for family in families}
            elif axis == "skills":
                rows = await self.db.execute(
                    select(Skill.key, func.count(JobSkill.job_id))
                    .join(JobSkill, JobSkill.skill_id == Skill.id)
                    .where(JobSkill.job_id.in_(scope))
                    .group_by(Skill.key)
                    .order_by(func.count(JobSkill.job_id).desc(), Skill.key.asc())
                    .limit(SKILL_FACET_SIZE)
                )
                facets["skills"] = {key: int(count) for key, count in rows.all()}
            elif axis == "interests":
                rows = await self.db.execute(
                    select(InterestTag.key, func.count(JobTag.job_id))
                    .join(JobTag, JobTag.interest_tag_id == InterestTag.id)
                    .where(JobTag.job_id.in_(scope))
                    .group_by(InterestTag.key)
                    .order_by(func.count(JobTag.job_id).desc(), InterestTag.key.asc())
                    .limit(INTEREST_FACET_SIZE)
                )
                facets["interests"] = {key: int(count) for key, count in rows.all()}
            elif axis == "education":
                counts = await _grouped_scalar(self.db, scope, _json_text("education", "level"))
                facets["education"] = {
                    level.value: counts.get(level.value, 0) for level in EducationLevel
                }
            elif axis == "demand":
                counts = await _grouped_scalar(self.db, scope, _json_text("demand", "outlook"))
                facets["demand"] = {
                    outlook.value: counts.get(outlook.value, 0) for outlook in DemandOutlook
                }
            elif axis == "contract":
                counts = await _grouped_scalar(self.db, scope, _json_text("contract_type"))
                facets["contract"] = {value: counts.get(value, 0) for value in CONTRACT_VALUES}
            elif axis == "schedule":
                facets["schedule"] = await _array_facet(
                    self.db, scope, SCHEDULE_VALUES, "schedule_cues"
                )
            elif axis == "travel":
                counts = await _grouped_scalar(
                    self.db, scope, _json_text("travel_required", "level")
                )
                facets["travel"] = {value: counts.get(value, 0) for value in TRAVEL_VALUES}
            elif axis == "environment":
                facets["environment"] = await _array_facet(
                    self.db, scope, [entry.value for entry in Environment], "environments"
                )
            elif axis == "source":
                counts = await _grouped_scalar(self.db, scope, Job.source)
                facets["source"] = {entry.value: counts.get(entry.value, 0) for entry in JobSource}
        return facets

    async def open_role_counts(self, job_ids: Sequence[UUID]) -> dict[UUID, int]:
        """Open live postings for a page of jobs in one grouped aggregate."""
        ids = list(dict.fromkeys(job_ids))
        if not ids:
            return {}
        rows = await self.db.execute(
            select(JobPosting.catalog_job_id, func.count(JobPosting.id))
            .where(
                JobPosting.catalog_job_id.in_(ids),
                JobPosting.status.in_(OPEN_POSTING_STATUSES),
            )
            .group_by(JobPosting.catalog_job_id)
        )
        counts = {job_id: int(count) for job_id, count in rows.all() if job_id is not None}
        return {job_id: counts.get(job_id, 0) for job_id in ids}

    async def _get_with_family(self, job_id) -> Job:
        """Re-fetch a job with links eagerly loaded."""
        rows = await self.db.execute(select(Job).options(*JOB_LOAD_OPTIONS).where(Job.id == job_id))
        return rows.scalars().unique().one()

    async def create(
        self,
        data: JobCreate,
        user: User | None,
        source: str = "user",
        status: str = "draft",
        *,
        commit: bool = True,
    ) -> Job:
        """Create a job; validates family/taxonomy keys and writes links.

        New entries land as drafts (human review before publishing, whether
        hand-written or AI-generated); publishing is an explicit step.
        ``commit=False`` leaves the transaction to the caller — an apply
        flow that must land job + posting map + proposal clear atomically
        (the ``upsert_embedding`` caller-owned-transaction precedent).
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
        if commit:
            await self.db.commit()
            if status == "published":
                await enqueue_job_index(self.db, job)
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
                JobTag.__table__.delete().where(JobTag.job_id == job_id)  # type: ignore[attr-defined]
            )
            for key in interest_keys:
                self.db.add(JobTag(job_id=job_id, interest_tag_id=tags[key].id, source=source))
        if skills is not None:
            skill_rows = {
                s.key: s
                for s in (
                    await self.db.execute(
                        select(Skill).where(Skill.key.in_([s.skill_key for s in skills]))
                    )
                )
                .scalars()
                .all()
            }
            missing = [s.skill_key for s in skills if s.skill_key not in skill_rows]
            if missing:
                raise ValidationError(f"Unknown skill keys: {', '.join(missing)}")
            await self.db.execute(
                JobSkill.__table__.delete().where(JobSkill.job_id == job_id)  # type: ignore[attr-defined]
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
        if job.status == "retired":
            raise PermissionDeniedError("A retired job type cannot be edited or republished")
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
                [JobSkillIn.model_validate(s) for s in skills] if skills is not None else None,
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
            await enqueue_job_index(self.db, job)
        await self._refresh_transferability()
        return job

    async def notify_published(self, job: Job) -> None:
        """Family-follow rules fire on the draft → published transition."""
        from app.services.postings.engagement_service import EngagementService

        await EngagementService(self.db).on_job_published(job)

    async def _refit_job(self, job_id) -> None:
        """Catalog changed ⇒ deterministic fit rows refresh for every user."""
        from app.services.postings.fit.service import FitService

        await FitService(self.db).refit_job(job_id)

    async def _refresh_transferability(self) -> None:
        """Catalog changed ⇒ derived transferability stats rebuild (38.4)."""
        from app.services.catalog.metric_service import MetricService

        await MetricService(self.db).recompute_skill_transferability()

    async def delete(self, ref: str | UUID, user: User) -> None:
        """Delete a non-seed job owned by the caller."""
        job = await self.require_job(ref)
        if job.status == "retired" or (job.ai_metadata or {}).get("retired_into"):
            raise PermissionDeniedError(
                "A retired job type is retained as a merge record and cannot be deleted"
            )
        if job.source == "seed":
            raise PermissionDeniedError("Seeded jobs cannot be deleted")
        if job.created_by and job.created_by != user.id:
            raise PermissionDeniedError("Not your job")
        await self.db.delete(job)
        await self.db.commit()
        await self._refresh_transferability()

    async def relations(self, ref: str | UUID) -> list[JobRelation]:
        """All relations touching a job."""
        job = await self.require_job(ref)
        rows = await self.db.execute(
            select(JobRelation)
            .options(
                selectinload(JobRelation.from_job).selectinload(Job.family),
                selectinload(JobRelation.to_job).selectinload(Job.family),
            )
            .where(or_(JobRelation.from_job_id == job.id, JobRelation.to_job_id == job.id))
        )
        return list(rows.scalars().unique().all())

    async def graph(self, root: str | None, depth: int = 2, family_key: str | None = None) -> dict:
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
                        other = rel.to_job if rel.from_job_id == node.id else rel.from_job
                        if other.code not in nodes:
                            nodes[other.code] = other
                            next_frontier.append(other)
                frontier = next_frontier
        else:
            query = select(Job).options(selectinload(Job.family)).where(Job.status == "published")
            if family_key:
                families = await self.families()
                family = next((f for f in families if f.key == family_key), None)
                if family is None:
                    raise NotFoundError("Family not found")
                descendant_ids = [f.id for f in families if f.path.startswith(family.path)]
                query = query.where(Job.family_id.in_(descendant_ids))
            jobs = list((await self.db.execute(query.limit(200))).scalars().unique().all())
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
