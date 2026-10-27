"""The single write seam for skill edges (plan 138, decision 5).

Every path to ``skill_relations`` goes through :class:`SkillRelationService`
— the admin API, the relation-learning job and the tree backfill alike.
Health-assistant enforces its endpoint matrix only in the AI tool layer,
which leaves raw writes unguarded; here the guards live in one place:

- endpoint-pair matrix (``SKILL_LINK_MATRIX``) + relation vocabulary,
- no self-loops,
- no cycles on the directed kinds (``is_a`` also follows the ``parent_id``
  backbone, mirroring ``TaxonomyService.update_skill``),
- canonical endpoint ordering for symmetric kinds (the enum owns the set),
- one row per (pair, relation): an existing row is updated, never duplicated,
  and a ``rejected`` row is never resurrected by a later suggestion.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.enums import SkillRelationSource, SkillRelationStatus, SkillRelationType
from app.models.taxonomy_model import Skill, SkillRelation
from app.services.catalog.skill_graph import SkillEdge, SkillGraph, SkillNode

# v1 has exactly one endpoint kind; the matrix exists so a future endpoint
# kind (job family, category…) cannot bypass the seam.
SKILL_LINK_MATRIX: dict[tuple[str, str], frozenset[SkillRelationType]] = {
    ("skill", "skill"): frozenset(SkillRelationType),
}

# Curated/imported edges are trusted; anything model-derived queues for review.
_AUTO_APPROVED_SOURCES = frozenset({SkillRelationSource.MANUAL, SkillRelationSource.IMPORT})

SkillRef = str | uuid.UUID


class SkillRelationService:
    """Guard, dedupe and review skill edges; load the graph for expansion."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ----------------------------------------------------------- graph read

    async def load_graph(self) -> SkillGraph:
        """Every skill plus its *approved* edges (proposals never expand)."""
        node_rows = (await self.db.execute(select(Skill.id, Skill.key, Skill.parent_id))).all()
        edge_rows = (
            await self.db.execute(
                select(
                    SkillRelation.from_skill_id,
                    SkillRelation.to_skill_id,
                    SkillRelation.relation,
                ).where(SkillRelation.status == SkillRelationStatus.APPROVED.value)
            )
        ).all()
        nodes = {
            row.id: SkillNode(id=row.id, key=row.key, parent_id=row.parent_id) for row in node_rows
        }
        edges = tuple(
            SkillEdge(
                from_skill_id=row.from_skill_id,
                to_skill_id=row.to_skill_id,
                relation=row.relation,
            )
            for row in edge_rows
        )
        return SkillGraph(nodes=nodes, edges=edges)

    # ------------------------------------------------------------ write path

    async def add(
        self,
        from_ref: SkillRef,
        to_ref: SkillRef,
        relation: str | SkillRelationType,
        *,
        source: str | SkillRelationSource = SkillRelationSource.MANUAL,
        status: str | SkillRelationStatus | None = None,
        confidence: float | None = None,
        evidence: dict | None = None,
        decided_by: uuid.UUID | None = None,
    ) -> SkillRelation:
        """Add (or refresh) one edge; manual/import land approved, AI queued."""
        kind = self._relation(relation)
        origin = SkillRelationSource(source)
        source_skill = await self._require_skill(from_ref)
        target_skill = await self._require_skill(to_ref)
        if source_skill.id == target_skill.id:
            raise ValidationError("A skill cannot relate to itself")
        self._validate_matrix(kind)
        first, second = self._canonical_pair(source_skill.id, target_skill.id, kind)

        existing = await self._find(kind, first, second)
        if existing is not None:
            if existing.status == SkillRelationStatus.REJECTED.value:
                # The negative edge is final for suggestions: only an explicit
                # approve() may ever bring this pair back.
                return existing
            if confidence is not None:
                existing.confidence = confidence
            if evidence is not None:
                existing.evidence = evidence
            await self.db.commit()
            return existing

        if kind.is_directed:
            await self._assert_acyclic(source_skill.id, target_skill.id, kind)

        resolution = SkillRelationStatus(status) if status is not None else None
        if resolution is None:
            resolution = (
                SkillRelationStatus.APPROVED
                if origin in _AUTO_APPROVED_SOURCES
                else SkillRelationStatus.PROPOSED
            )
        edge = SkillRelation(
            from_skill_id=first,
            to_skill_id=second,
            relation=kind.value,
            status=resolution.value,
            source=origin.value,
            confidence=confidence,
            evidence=evidence,
            decided_by=decided_by,
            decided_at=datetime.now(UTC) if decided_by is not None else None,
        )
        self.db.add(edge)
        await self.db.commit()
        await self.db.refresh(edge)
        return edge

    async def approve(
        self, edge_id: SkillRef, decided_by: uuid.UUID | None = None
    ) -> SkillRelation:
        """Approve a proposed (or previously rejected) edge — the human override."""
        edge = await self._require_edge(edge_id)
        if edge.status == SkillRelationStatus.APPROVED.value:
            return edge
        kind = self._relation(edge.relation)
        if kind.is_directed:
            # The graph may have grown since the proposal: re-check the cycle.
            await self._assert_acyclic(edge.from_skill_id, edge.to_skill_id, kind)
        edge.status = SkillRelationStatus.APPROVED.value
        edge.decided_by = decided_by
        edge.decided_at = datetime.now(UTC)
        await self.db.commit()
        return edge

    async def reject(self, edge_id: SkillRef, decided_by: uuid.UUID | None = None) -> SkillRelation:
        """Write (or confirm) the negative edge for this pair + relation."""
        edge = await self._require_edge(edge_id)
        edge.status = SkillRelationStatus.REJECTED.value
        edge.decided_by = decided_by
        edge.decided_at = datetime.now(UTC)
        await self.db.commit()
        return edge

    async def remove(self, edge_id: SkillRef) -> None:
        """Hard-delete an edge (admin cleanup; rejections are the negative edge)."""
        edge = await self._require_edge(edge_id)
        await self.db.delete(edge)
        await self.db.commit()

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _relation(relation: str | SkillRelationType) -> SkillRelationType:
        try:
            return SkillRelationType(relation)
        except ValueError as exc:
            raise ValidationError(f"Unknown skill relation: {relation}") from exc

    @staticmethod
    def _validate_matrix(kind: SkillRelationType) -> None:
        allowed = SKILL_LINK_MATRIX.get(("skill", "skill"), frozenset())
        if kind not in allowed:
            raise ValidationError(f"Relation {kind.value} is not allowed between two skills")

    @staticmethod
    def _canonical_pair(
        first: uuid.UUID, second: uuid.UUID, kind: SkillRelationType
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """Symmetric kinds store the lower UUID first (the DB CHECK's order).

        ``str(uuid)`` ordering equals the schema's comparison on both
        dialects (Postgres compares the 16 bytes; SQLite compares the
        hyphenated text, which only differs in hex digits).
        """
        if kind.is_directed:
            return first, second
        return (first, second) if str(first) <= str(second) else (second, first)

    async def _find(
        self, kind: SkillRelationType, first: uuid.UUID, second: uuid.UUID
    ) -> SkillRelation | None:
        row = await self.db.execute(
            select(SkillRelation).where(
                SkillRelation.from_skill_id == first,
                SkillRelation.to_skill_id == second,
                SkillRelation.relation == kind.value,
            )
        )
        return row.scalars().first()

    async def _require_skill(self, ref: SkillRef) -> Skill:
        skill = None
        try:
            skill_id = uuid.UUID(str(ref))
        except ValueError:
            skill_id = None
        if skill_id is not None:
            skill = await self.db.get(Skill, skill_id)
        if skill is None:
            skill = (
                (await self.db.execute(select(Skill).where(Skill.key == str(ref))))
                .scalars()
                .first()
            )
        if skill is None:
            raise NotFoundError(f"Skill not found: {ref}")
        return skill

    async def _require_edge(self, edge_id: SkillRef) -> SkillRelation:
        try:
            row_id = uuid.UUID(str(edge_id))
        except ValueError as exc:
            raise NotFoundError(f"Skill relation not found: {edge_id}") from exc
        edge = await self.db.get(SkillRelation, row_id)
        if edge is None:
            raise NotFoundError(f"Skill relation not found: {edge_id}")
        return edge

    async def _assert_acyclic(
        self, from_id: uuid.UUID, to_id: uuid.UUID, kind: SkillRelationType
    ) -> None:
        """Reject ``from -> to`` when ``from`` is already one of ``to``'s ancestors."""
        seen: set[uuid.UUID] = set()
        frontier = [to_id]
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            if current == from_id:
                raise ValidationError(f"{kind.value} edge would create a cycle")
            frontier.extend(await self._generalities(current, kind))

    async def _generalities(self, skill_id: uuid.UUID, kind: SkillRelationType) -> list[uuid.UUID]:
        """One step towards the general end of the axis, approved rows only."""
        out: list[uuid.UUID] = []
        if kind is SkillRelationType.IS_A:
            parent_id = (
                await self.db.execute(select(Skill.parent_id).where(Skill.id == skill_id))
            ).scalar_one_or_none()
            if parent_id is not None:
                out.append(parent_id)
        rows = await self.db.execute(
            select(SkillRelation.to_skill_id).where(
                SkillRelation.from_skill_id == skill_id,
                SkillRelation.relation == kind.value,
                SkillRelation.status == SkillRelationStatus.APPROVED.value,
            )
        )
        out.extend(rows.scalars().all())
        return out
