"""Career paths: curated listing, computed BFS graph, moderation, and the
user-facing explorer (visible paths, detail with marks + skill gaps, and
the user_path_flags marks)."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, ValidationError
from app.models.career_path_model import CareerPath, CareerPathStep, UserPathFlag
from app.models.enums import CareerStage as PathStage
from app.models.enums import PathFlag, PathSource, PathStatus, RelationType
from app.models.job_model import Job, JobRelation, JobSkill
from app.models.user_model import UserSkill
from app.schemas.paths import (
    CareerPathOut,
    GraphEdgeOut,
    GraphNodeOut,
    PathDetailOut,
    PathGraphOut,
    PathStepDetailOut,
    PathStepOut,
    PathStepSkillOut,
)

MAX_GRAPH_NODES = 200


def _experience_first(paths: list[CareerPath]) -> list[CareerPath]:
    """Fewer education steps first, then more experience/certification steps."""

    def sort_key(path: CareerPath) -> tuple[int, int]:
        steps = path.steps or []
        education = sum(1 for s in steps if s.kind == "education")
        experience = sum(1 for s in steps if s.kind in ("experience", "certification"))
        return (education, -experience)

    return sorted(paths, key=sort_key)


class PathService:
    """Published paths for a job + the computed 'roads leading here' graph."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _visible_condition(user_id: UUID):
        """A path is visible when published (curated) or when the caller
        holds the path-level mark that owns it (user copies — the frozen
        schema attributes user paths through their unique path flag)."""
        owned = select(UserPathFlag.path_id).where(
            UserPathFlag.user_id == user_id,
            UserPathFlag.step_id.is_(None),
        )
        return or_(
            CareerPath.status == PathStatus.PUBLISHED.value,
            (CareerPath.source == PathSource.USER.value) & CareerPath.id.in_(owned),
        )

    async def path_flags(self, user_id: UUID, path_id: UUID) -> list[UserPathFlag]:
        rows = await self.db.execute(
            select(UserPathFlag).where(
                UserPathFlag.user_id == user_id,
                UserPathFlag.path_id == path_id,
            )
        )
        return list(rows.scalars().all())

    async def require_visible(self, path_id: UUID, user) -> CareerPath:
        rows = await self.db.execute(
            select(CareerPath)
            .options(
                selectinload(CareerPath.steps).selectinload(CareerPathStep.family),
                selectinload(CareerPath.steps).selectinload(CareerPathStep.skill),
                selectinload(CareerPath.job),
            )
            .execution_options(populate_existing=True)
            .where(CareerPath.id == path_id, self._visible_condition(user.id))
        )
        path = rows.scalars().first()
        if path is None:
            raise NotFoundError("Path not found")
        return path

    async def require_owned(self, path_id: UUID, user) -> CareerPath:
        """A user path the caller owns (their path-level flag exists);
        curated paths are never shared-mutable."""
        path = await self.require_visible(path_id, user)
        if path.source != PathSource.USER.value:
            raise NotFoundError("Path not found")
        return path

    async def _owning_flag(self, path_id: UUID, user_id: UUID) -> UserPathFlag | None:
        rows = await self.db.execute(
            select(UserPathFlag).where(
                UserPathFlag.user_id == user_id,
                UserPathFlag.path_id == path_id,
                UserPathFlag.step_id.is_(None),
            )
        )
        return rows.scalars().first()

    async def _resequence(self, path_id: UUID, positions: dict[UUID, int]) -> None:
        """Two-phase position write (the UNIQUE(path_id, position) guard
        forbids in-place swaps)."""
        rows = await self.db.execute(
            select(CareerPathStep).where(CareerPathStep.path_id == path_id)
        )
        steps = rows.scalars().all()
        for step in steps:
            if step.id in positions:
                step.position = 10_000 + positions[step.id]
        await self.db.flush()
        for step in steps:
            if step.id in positions:
                step.position = positions[step.id]
        await self.db.flush()

    async def _resolve_step_refs(
        self, *, skill_key: str | None, family_key: str | None
    ) -> tuple[UUID | None, UUID | None]:
        from app.models.job_model import JobFamily
        from app.models.taxonomy_model import Skill

        skill_id = None
        if skill_key:
            rows = await self.db.execute(
                select(Skill).where(Skill.key == skill_key, Skill.status == "active")
            )
            skill = rows.scalars().first()
            if skill is None:
                raise ValidationError(f"Unknown skill: {skill_key!r}")
            skill_id = skill.id
        family_id = None
        if family_key:
            rows = await self.db.execute(select(JobFamily).where(JobFamily.key == family_key))
            family = rows.scalars().first()
            if family is None:
                raise ValidationError(f"Unknown family: {family_key!r}")
            family_id = family.id
        return skill_id, family_id

    async def create_user_path(
        self,
        user,
        *,
        job_id: UUID,
        title: str,
        description: str,
        steps: list[dict],
    ) -> CareerPath:
        """Review-first: a draft user path + the creator's owning pin."""
        rows = await self.db.execute(
            select(Job).where(
                Job.status == PathStatus.PUBLISHED.value,
                or_(Job.code == str(job_id), Job.id == job_id),
            )
        )
        job = rows.scalars().first()
        if job is None:
            raise NotFoundError("Target job not found")
        path = CareerPath(
            job_id=job.id,
            title=title,
            description=description,
            source=PathSource.USER.value,
            status=PathStatus.DRAFT.value,
        )
        self.db.add(path)
        await self.db.flush()
        self.db.add(
            UserPathFlag(user_id=user.id, path_id=path.id, step_id=None, flag=PathFlag.PINNED.value)
        )
        await self._insert_steps(path, steps)
        await self.db.commit()
        await self.db.refresh(path)
        return path

    async def _insert_steps(self, path: CareerPath, steps: list[dict]) -> list[CareerPathStep]:
        """Insert the submitted step dicts in list order; `parent` indexes
        the list for branches. Slots start after the existing steps."""
        existing = await self._steps_of(path.id)
        base = (max(step.position for step in existing) + 1) if existing else 0
        created: list[CareerPathStep] = []
        for spec in steps:
            skill_id, family_id = await self._resolve_step_refs(
                skill_key=spec.get("skill_key"), family_key=spec.get("family_key")
            )
            parent_step = created[spec["parent"]] if spec.get("parent") is not None else None
            step = CareerPathStep(
                path_id=path.id,
                position=10_000 + len(created),
                kind=spec["kind"],
                label=spec["label"],
                optional=spec.get("optional", False),
                skill_id=skill_id,
                family_id=family_id,
                education_level=spec.get("education_level"),
                parent_step_id=parent_step.id if parent_step is not None else None,
                edge_label=spec.get("edge_label", "") if parent_step is not None else "",
            )
            self.db.add(step)
            await self.db.flush()
            created.append(step)
        positions = {step.id: base + offset for offset, step in enumerate(created)}
        await self._resequence(path.id, positions)
        return created

    async def _steps_of(self, path_id: UUID) -> list[CareerPathStep]:
        rows = await self.db.execute(
            select(CareerPathStep)
            .where(CareerPathStep.path_id == path_id)
            .order_by(CareerPathStep.position)
        )
        return list(rows.scalars().all())

    async def fork(self, path_id: UUID, user) -> CareerPath:
        """Fork-on-edit: the caller gets their own copy (source=user,
        active); the curated original stays untouched."""
        source = await self.require_visible(path_id, user)
        if source.source == PathSource.USER.value and await self._owning_flag(source.id, user.id):
            return source
        copy = CareerPath(
            job_id=source.job_id,
            title=source.title,
            description=source.description,
            source=PathSource.USER.value,
            status=PathStatus.ACTIVE.value,
        )
        self.db.add(copy)
        await self.db.flush()
        id_map: dict[UUID, UUID] = {}
        for offset, step in enumerate(sorted(source.steps, key=lambda s: s.position)):
            new_step = CareerPathStep(
                path_id=copy.id,
                position=10_000 + offset,
                kind=step.kind,
                label=step.label,
                optional=step.optional,
                skill_id=step.skill_id,
                family_id=step.family_id,
                education_level=step.education_level,
                parent_step_id=id_map.get(step.parent_step_id) if step.parent_step_id else None,
                edge_label=step.edge_label,
            )
            self.db.add(new_step)
            await self.db.flush()
            id_map[step.id] = new_step.id
        await self._resequence(copy.id, {step.id: step.position for step in source.steps})
        self.db.add(
            UserPathFlag(user_id=user.id, path_id=copy.id, step_id=None, flag=PathFlag.PINNED.value)
        )
        await self.db.commit()
        await self.db.refresh(copy)
        return copy

    async def activate(self, path: CareerPath) -> CareerPath:
        """The owner's review action: draft → active. Never automatic."""
        path.status = PathStatus.ACTIVE.value
        await self.db.commit()
        return path

    async def update_path(
        self, path: CareerPath, *, title: str | None, description: str | None
    ) -> CareerPath:
        if title is not None:
            path.title = title
        if description is not None:
            path.description = description
        await self.db.commit()
        return path

    async def delete_path(self, path: CareerPath) -> None:
        await self.db.delete(path)
        await self.db.commit()

    async def add_step(
        self, path: CareerPath, *, parent_step_id: UUID | None, spec: dict, position: int | None
    ) -> CareerPathStep:
        skill_id, family_id = await self._resolve_step_refs(
            skill_key=spec.get("skill_key"), family_key=spec.get("family_key")
        )
        steps = await self._steps_of(path.id)
        if parent_step_id is not None and not any(step.id == parent_step_id for step in steps):
            raise ValidationError("Parent step not found")
        occupied = sorted(step.position for step in steps)
        if position is not None:
            new_position = position
        elif parent_step_id is not None:
            new_position = next(s.position for s in steps if s.id == parent_step_id) + 1
        else:
            new_position = (occupied[-1] + 1) if occupied else 0
        step = CareerPathStep(
            path_id=path.id,
            position=50_000 + len(occupied),
            kind=spec["kind"],
            label=spec["label"],
            optional=spec.get("optional", False),
            skill_id=skill_id,
            family_id=family_id,
            education_level=spec.get("education_level"),
            parent_step_id=parent_step_id,
            edge_label=spec.get("edge_label", "") if parent_step_id is not None else "",
        )
        self.db.add(step)
        await self.db.flush()
        shifted = {s.id: s.position + (1 if s.position >= new_position else 0) for s in steps}
        shifted[step.id] = new_position
        await self._resequence(path.id, shifted)
        await self.db.commit()
        return step

    async def update_step(self, path: CareerPath, step_id: UUID, spec: dict) -> CareerPathStep:
        steps = await self._steps_of(path.id)
        step = next((s for s in steps if s.id == step_id), None)
        if step is None:
            raise NotFoundError("Step not found")
        if "skill_key" in spec or "family_key" in spec:
            skill_id, family_id = await self._resolve_step_refs(
                skill_key=spec.get("skill_key", step.skill.key if step.skill else None),
                family_key=spec.get("family_key", step.family.key if step.family else None),
            )
            step.skill_id = skill_id
            step.family_id = family_id
        for field in ("label", "kind", "optional", "edge_label", "education_level"):
            if spec.get(field) is not None:
                setattr(step, field, spec[field])
        await self.db.commit()
        return step

    async def delete_step(self, path: CareerPath, step_id: UUID) -> None:
        steps = await self._steps_of(path.id)
        step = next((s for s in steps if s.id == step_id), None)
        if step is None:
            raise NotFoundError("Step not found")
        remaining = {s.id: s.position for s in steps if s.id != step_id}
        await self.db.delete(step)
        await self.db.flush()
        await self._resequence(path.id, remaining)
        await self.db.commit()

    async def reorder_steps(
        self, path: CareerPath, *, parent_step_id: UUID | None, ordered: list[UUID]
    ) -> None:
        """Rearrange one sibling set among the positions it already holds."""
        steps = await self._steps_of(path.id)
        siblings = [
            s
            for s in steps
            if (s.parent_step_id == parent_step_id)
            or (parent_step_id is None and s.parent_step_id is None)
        ]
        sibling_ids = {s.id for s in siblings}
        if set(ordered) != sibling_ids or len(ordered) != len(siblings):
            raise ValidationError("ordered must list exactly this sibling set")
        slots = sorted(s.position for s in siblings)
        positions = dict(zip(ordered, slots, strict=True))
        await self._resequence(path.id, positions)
        await self.db.commit()

    async def index(
        self,
        user,
        *,
        job_id: UUID | None = None,
        family_key: str | None = None,
        stage=None,
    ) -> list[CareerPathOut]:
        """Published paths + the caller's own copies, newest first."""
        query = (
            select(CareerPath)
            .options(
                selectinload(CareerPath.steps).selectinload(CareerPathStep.family),
                selectinload(CareerPath.steps).selectinload(CareerPathStep.skill),
                selectinload(CareerPath.job),
            )
            .where(self._visible_condition(user.id))
            .order_by(CareerPath.created_at.desc())
        )
        if job_id is not None:
            query = query.where(CareerPath.job_id == job_id)
        if family_key:
            query = query.join(Job, Job.id == CareerPath.job_id).where(
                Job.family.has(key=family_key)
            )
        rows = (await self.db.execute(query)).scalars().unique().all()
        flags = {
            flag.path_id: flag.flag
            for flag in await self.path_flags_all(user.id, [path.id for path in rows])
        }
        outs = [self._path_out(path, my_flag=flags.get(path.id)) for path in rows]
        if stage is not None and stage != PathStage.STUDENT:
            outs = self._experience_first_out(outs)
        return outs

    async def path_flags_all(self, user_id: UUID, path_ids: list[UUID]) -> list[UserPathFlag]:
        if not path_ids:
            return []
        rows = await self.db.execute(
            select(UserPathFlag).where(
                UserPathFlag.user_id == user_id,
                UserPathFlag.step_id.is_(None),
                UserPathFlag.path_id.in_(path_ids),
            )
        )
        return list(rows.scalars().all())

    @staticmethod
    def _experience_first_out(paths: list[CareerPathOut]) -> list[CareerPathOut]:
        def sort_key(path: CareerPathOut) -> tuple[int, int]:
            steps = path.steps or []
            education = sum(1 for s in steps if s.kind == "education")
            experience = sum(1 for s in steps if s.kind in ("experience", "certification"))
            return (education, -experience)

        return sorted(paths, key=sort_key)

    async def for_job(
        self, job_id: UUID, *, include_drafts: bool = False, user_id: UUID | None = None
    ) -> list[CareerPath]:
        query = (
            select(CareerPath)
            .options(
                selectinload(CareerPath.steps).selectinload(CareerPathStep.family),
                selectinload(CareerPath.steps).selectinload(CareerPathStep.skill),
            )
            .where(CareerPath.job_id == job_id)
            .order_by(CareerPath.created_at)
        )
        if include_drafts:
            pass
        elif user_id is not None:
            query = query.where(
                or_(
                    CareerPath.status == PathStatus.PUBLISHED.value,
                    (CareerPath.source == PathSource.USER.value)
                    & CareerPath.id.in_(
                        select(UserPathFlag.path_id).where(
                            UserPathFlag.user_id == user_id,
                            UserPathFlag.step_id.is_(None),
                        )
                    ),
                )
            )
        else:
            query = query.where(CareerPath.status == PathStatus.PUBLISHED.value)
        return list((await self.db.execute(query)).scalars().unique().all())

    async def paths_out(
        self,
        job_id: UUID,
        *,
        include_drafts: bool = False,
        stage=None,
        user_id: UUID | None = None,
    ) -> list[CareerPathOut]:
        """Paths for a job; non-student stages get experience-first ordering
        ."""
        paths = await self.for_job(job_id, include_drafts=include_drafts, user_id=user_id)
        if stage is not None and stage != PathStage.STUDENT:
            paths = _experience_first(paths)
        flags: dict[UUID, str] = {}
        if user_id is not None:
            flags = {
                flag.path_id: flag.flag
                for flag in await self.path_flags_all(user_id, [p.id for p in paths])
            }
        return [self._path_out(p, my_flag=flags.get(p.id)) for p in paths]

    def _path_out(self, path: CareerPath, *, my_flag: str | None = None) -> CareerPathOut:
        return CareerPathOut(
            id=path.id,
            job_id=path.job_id,
            title=path.title,
            description=path.description,
            source=path.source,
            status=path.status,
            job_code=path.job.code if path.job else None,
            job_title=path.job.title if path.job else None,
            my_flag=my_flag,
            steps=[self._step_out(step) for step in path.steps],
        )

    @staticmethod
    def _step_out(step: CareerPathStep) -> PathStepOut:
        return PathStepOut(
            id=step.id,
            position=step.position,
            kind=step.kind,
            label=step.label,
            optional=step.optional,
            family_key=step.family.key if step.family else None,
            family_label=step.family.label if step.family else None,
            skill_key=step.skill.key if step.skill else None,
            skill_label=step.skill.label if step.skill else None,
            education_level=step.education_level,
            parent_step_id=step.parent_step_id,
            edge_label=step.edge_label,
        )

    async def detail(self, path: CareerPath, user) -> PathDetailOut:
        """Path + the caller's marks, per-step skill gaps against the
        target job, and the mark-aware completeness count."""
        flags = {flag.step_id: flag for flag in await self.path_flags(user.id, path.id)}
        path_flag = flags.get(None)
        skill_ids = [step.skill_id for step in path.steps if step.skill_id is not None]
        levels: dict[UUID, int] = {}
        if skill_ids:
            rows = await self.db.execute(
                select(UserSkill).where(
                    UserSkill.user_id == user.id,
                    UserSkill.skill_id.in_(skill_ids),
                )
            )
            levels = {row.skill_id: row.level for row in rows.scalars().all()}
        required: dict[UUID, int] = {}
        if skill_ids:
            rows = await self.db.execute(
                select(JobSkill).where(
                    JobSkill.job_id == path.job_id,
                    JobSkill.skill_id.in_(skill_ids),
                )
            )
            required = {row.skill_id: row.required_level for row in rows.scalars().all()}
        steps: list[PathStepDetailOut] = []
        total = 0
        met = 0
        for step in path.steps:
            step_flag = flags.get(step.id)
            skill_out = None
            if step.skill_id is not None and step.skill is not None:
                user_level = levels.get(step.skill_id)
                required_level = required.get(step.skill_id)
                skill_out = PathStepSkillOut(
                    skill_id=step.skill_id,
                    key=step.skill.key,
                    label=step.skill.label,
                    user_level=user_level,
                    required_level=required_level,
                )
                dismissed = step_flag is not None and step_flag.flag == PathFlag.DISMISSED.value
                if not step.optional and not dismissed:
                    total += 1
                    threshold = required_level if required_level is not None else 1
                    if (user_level or 0) >= threshold:
                        met += 1
            steps.append(
                PathStepDetailOut(
                    **self._step_out(step).model_dump(),
                    my_flag=step_flag.flag if step_flag else None,
                    my_note=step_flag.note if step_flag else "",
                    skill=skill_out,
                )
            )
        return PathDetailOut(
            id=path.id,
            job_id=path.job_id,
            title=path.title,
            description=path.description,
            source=path.source,
            status=path.status,
            job_code=path.job.code if path.job else None,
            job_title=path.job.title if path.job else None,
            my_flag=path_flag.flag if path_flag else None,
            my_note=path_flag.note if path_flag else "",
            skills_total=total,
            skills_met=met,
            steps=steps,
        )

    async def set_flag(
        self,
        path: CareerPath,
        user,
        *,
        step_id: UUID | None,
        flag: str | None,
        note: str,
    ) -> str | None:
        """Upsert (or clear) one mark; marks never feed scoring."""

        def scope(target: UUID | None):
            return (
                UserPathFlag.step_id.is_(None) if target is None else UserPathFlag.step_id == target
            )

        if flag is None:
            rows = await self.db.execute(
                select(UserPathFlag).where(
                    UserPathFlag.user_id == user.id,
                    UserPathFlag.path_id == path.id,
                    scope(step_id),
                )
            )
            for row in rows.scalars().all():
                await self.db.delete(row)
            await self.db.commit()
            return None
        rows = await self.db.execute(
            select(UserPathFlag).where(
                UserPathFlag.user_id == user.id,
                UserPathFlag.path_id == path.id,
                scope(step_id),
            )
        )
        mark = rows.scalars().first()
        if mark is None:
            mark = UserPathFlag(
                user_id=user.id,
                path_id=path.id,
                step_id=step_id,
                flag=flag,
                note=note,
            )
            self.db.add(mark)
        else:
            mark.flag = flag
            mark.note = note
        await self.db.commit()
        return mark.flag

    async def graph(self, job: Job, depth: int = 4) -> PathGraphOut:
        """BFS backwards over leads_to/prerequisite_of edges (cycle-safe).

        A step towards `job` is any career X with X --leads_to--> job or
        X --prerequisite_of--> job; we walk incoming edges level by level.
        """
        incoming = or_(
            (JobRelation.relation_type == RelationType.LEADS_TO.value),
            (JobRelation.relation_type == RelationType.PREREQUISITE_OF.value),
        )
        nodes: dict[UUID, dict] = {}
        edges: list[GraphEdgeOut] = []
        truncated = False
        seen_edges: set[tuple[str, str, str]] = set()

        root_row = job
        nodes[job.id] = {
            "job": root_row,
            "depth": 0,
        }
        frontier = [(job.id, 0)]
        while frontier and len(nodes) < MAX_GRAPH_NODES:
            next_frontier = []
            for job_id, level in frontier:
                if level >= depth:
                    continue
                current = nodes[job_id]["job"]
                rows = await self.db.execute(
                    select(JobRelation)
                    .options(selectinload(JobRelation.from_job).selectinload(Job.family))
                    .where(
                        JobRelation.to_job_id == job_id,
                        incoming,
                    )
                )
                for rel in rows.scalars().unique().all():
                    source = rel.from_job
                    edge_key = (source.code, current.code, rel.relation_type)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges.append(
                            GraphEdgeOut(
                                from_code=source.code,
                                to_code=current.code,
                                relation_type=rel.relation_type,
                                weight=rel.weight,
                            )
                        )
                    if source.id in nodes:
                        continue
                    if len(nodes) >= MAX_GRAPH_NODES:
                        truncated = True
                        break
                    nodes[source.id] = {"job": source, "depth": level + 1}
                    next_frontier.append((source.id, level + 1))
            frontier = next_frontier
        return PathGraphOut(
            root=job.code,
            nodes=[
                GraphNodeOut(
                    code=node["job"].code,
                    title=node["job"].title,
                    family_key=node["job"].family.key if node["job"].family else "",
                    demand=(node["job"].attributes or {}).get("demand", {}).get("outlook"),
                    depth=node["depth"],
                )
                for node in nodes.values()
            ],
            edges=edges,
            truncated=truncated,
        )

    async def get_path(self, path_id: UUID) -> CareerPath:
        rows = await self.db.execute(
            select(CareerPath)
            .options(selectinload(CareerPath.steps))
            .where(CareerPath.id == path_id)
        )
        path = rows.scalars().first()
        if path is None:
            raise NotFoundError("Path not found")
        return path

    async def publish(self, path_id: UUID) -> CareerPath:
        path = await self.get_path(path_id)
        path.status = PathStatus.PUBLISHED.value
        await self.db.commit()
        return path

    async def reject(self, path_id: UUID) -> None:
        """Delete a draft path (published paths are withdrawn, not deleted)."""
        path = await self.get_path(path_id)
        if path.status == PathStatus.PUBLISHED.value:
            path.status = PathStatus.DRAFT.value
            await self.db.commit()
            return
        await self.db.delete(path)
        await self.db.commit()
