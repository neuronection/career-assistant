"""Career paths: curated listing, computed BFS graph, moderation."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.models.enums import CareerStage as PathStage
from app.models.enums import PathStatus, RelationType
from app.models.job_model import Job, JobRelation
from app.models.career_path_model import CareerPath, CareerPathStep
from app.schemas.paths import (
    CareerPathOut,
    GraphEdgeOut,
    GraphNodeOut,
    PathGraphOut,
    PathStepOut,
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

    async def for_job(
        self, job_id: UUID, *, include_drafts: bool = False
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
        if not include_drafts:
            query = query.where(CareerPath.status == PathStatus.PUBLISHED.value)
        return list((await self.db.execute(query)).scalars().unique().all())

    async def paths_out(
        self,
        job_id: UUID,
        *,
        include_drafts: bool = False,
        stage=None,
    ) -> list[CareerPathOut]:
        """Paths for a job; non-student stages get experience-first ordering
        (plan 25 — a presentation rule, never new data)."""
        paths = await self.for_job(job_id, include_drafts=include_drafts)
        if stage is not None and stage != PathStage.STUDENT:
            paths = _experience_first(paths)
        return [self._path_out(p) for p in paths]

    @staticmethod
    def _path_out(path: CareerPath) -> CareerPathOut:
        return CareerPathOut(
            id=path.id,
            job_id=path.job_id,
            title=path.title,
            description=path.description,
            source=path.source,
            status=path.status,
            steps=[
                PathStepOut(
                    position=step.position,
                    kind=step.kind,
                    label=step.label,
                    optional=step.optional,
                    family_key=step.family.key if step.family else None,
                    family_label=step.family.label if step.family else None,
                    skill_key=step.skill.key if step.skill else None,
                    skill_label=step.skill.label if step.skill else None,
                    education_level=step.education_level,
                )
                for step in path.steps
            ],
        )

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
                    .options(
                        selectinload(JobRelation.from_job).selectinload(Job.family)
                    )
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
                    demand=(node["job"].attributes or {})
                    .get("demand", {})
                    .get("outlook"),
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
