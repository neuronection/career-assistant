"""The single write seam for skill edges (plan 138, decision 5).

Every path to ``skill_relations`` goes through :class:`SkillRelationService`
— the admin API, the relation-learning job and the tree backfill alike.
Health-assistant enforces its endpoint matrix only in the AI tool layer,
which leaves raw writes unguarded; here the guards live in one place:

- endpoint-pair matrix (``SKILL_LINK_MATRIX``) + relation vocabulary,
- no self-loops,
- no cycles on the directed kinds (``is_a`` also follows the ``parent_id``
  backbone — one generality walk, :func:`assert_acyclic`, shared with
  ``TaxonomyService.update_skill``'s re-parent),
- canonical endpoint ordering for symmetric kinds (the enum owns the set),
- one row per (pair, relation): an existing row is updated, never duplicated,
  evidence is write-once (a later suggestion refreshes the confidence, never
  the first provenance), and a ``rejected`` row is never resurrected by a
  later suggestion.
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

    async def list_relations(
        self,
        *,
        status: str | SkillRelationStatus | None = None,
        skill_id: uuid.UUID | None = None,
        limit: int = 200,
    ) -> list[SkillRelation]:
        """Review-grain listing: every (pair, relation) row, any status.

        ``load_graph`` is expansion-only (approved rows); this is the
        admin queue's read API — pair ids, evidence and provenance ride
        each row, newest first and bounded (the table grows without one).
        """
        query = select(SkillRelation)
        if status is not None:
            query = query.where(SkillRelation.status == self._status(status).value)
        if skill_id is not None:
            query = query.where(
                (SkillRelation.from_skill_id == skill_id) | (SkillRelation.to_skill_id == skill_id)
            )
        query = query.order_by(SkillRelation.created_at.desc()).limit(max(1, limit))
        rows = await self.db.execute(query)
        return list(rows.scalars().all())

    # ------------------------------------------------------------ write path

    async def get(self, edge_id: SkillRef) -> SkillRelation:
        """One row by id (queue actions operate on exactly this grain)."""
        return await self._require_edge(edge_id)

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
        """Add one edge, or refresh an existing non-rejected row.

        Manual and import sources land ``approved``; llm/derived land
        ``proposed``. An existing row keeps its status (only ``approve()``
        and ``reject()`` move it) and a ``rejected`` row is never
        resurrected by a later suggestion — that is the negative edge.
        """
        kind = self._relation(relation)
        origin = self._source(source)
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
            if evidence is not None and not existing.evidence:
                # Provenance is write-once: a later suggestion refreshes the
                # confidence but never overwrites the first evidence.
                existing.evidence = evidence
            await self.db.commit()
            return existing

        if kind.is_directed:
            await assert_acyclic(self.db, source_skill.id, target_skill.id, kind)

        resolution = self._status(status) if status is not None else None
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
            await assert_acyclic(self.db, edge.from_skill_id, edge.to_skill_id, kind)
        edge.status = SkillRelationStatus.APPROVED.value
        edge.decided_by = decided_by
        edge.decided_at = datetime.now(UTC)
        await self.db.commit()
        return edge

    async def reject(self, edge_id: SkillRef, decided_by: uuid.UUID | None = None) -> SkillRelation:
        """Write (or confirm) the negative edge for this pair + relation.

        Rejecting an ``is_a`` row can strand a ``learned`` tree placement
        it justified — the placement heal re-derives it from the surviving
        approved support (plan 139 decision 4).
        """
        edge = await self._require_edge(edge_id)
        kind = self._relation(edge.relation)
        subject = edge.from_skill_id
        edge.status = SkillRelationStatus.REJECTED.value
        edge.decided_by = decided_by
        edge.decided_at = datetime.now(UTC)
        await self.db.commit()
        if kind is SkillRelationType.IS_A:
            await self._heal_learned_placement(subject)
        return edge

    async def remove(self, edge_id: SkillRef) -> None:
        """Hard-delete an edge (admin cleanup; rejections are the negative edge).

        Deleting an ``is_a`` row can strand a ``learned`` tree placement it
        justified — the placement heal re-derives it from the surviving
        approved support, so the tree never keeps a placement nobody's
        evidence endorses (and materialization has nothing to resurrect,
        plan 139 decision 4).
        """
        edge = await self._require_edge(edge_id)
        kind = self._relation(edge.relation)
        subject = edge.from_skill_id
        await self.db.delete(edge)
        await self.db.commit()
        if kind is SkillRelationType.IS_A:
            await self._heal_learned_placement(subject)

    async def _heal_learned_placement(self, skill_id: uuid.UUID) -> None:
        """Route the placement heal through the tree-write owner.

        The tree write belongs to ``TaxonomyService`` — the deferred
        import breaks the module cycle (``taxonomy_service`` imports this
        module's ``assert_acyclic``), the same pattern the tree catch-up
        uses. Edge writes stay here; this reads nothing but the skill.
        """
        from app.services.catalog.taxonomy_service import TaxonomyService

        await TaxonomyService(self.db).heal_learned_placement(skill_id)

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _relation(relation: str | SkillRelationType) -> SkillRelationType:
        try:
            return SkillRelationType(relation)
        except ValueError as exc:
            raise ValidationError(f"Unknown skill relation: {relation}") from exc

    @staticmethod
    def _source(source: str | SkillRelationSource) -> SkillRelationSource:
        try:
            return SkillRelationSource(source)
        except ValueError as exc:
            raise ValidationError(f"Unknown skill relation source: {source}") from exc

    @staticmethod
    def _status(status: str | SkillRelationStatus) -> SkillRelationStatus:
        try:
            return SkillRelationStatus(status)
        except ValueError as exc:
            raise ValidationError(f"Unknown skill relation status: {status}") from exc

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


async def assert_acyclic(
    db: AsyncSession, from_id: uuid.UUID, to_id: uuid.UUID, kind: SkillRelationType
) -> None:
    """Reject ``from -> to`` when ``from`` is already one of ``to``'s generalities.

    The one generality walk, shared by the edge seam and
    :meth:`TaxonomyService.update_skill`'s re-parent: ``parent_id`` and
    approved ``kind`` edges both count, so the two cycle guards can never
    disagree (plan 138 slice C F6).
    """
    seen: set[uuid.UUID] = set()
    frontier = [to_id]
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        if current == from_id:
            raise ValidationError(f"{kind.value} edge would create a cycle")
        frontier.extend(await _generalities(db, current, kind))


async def _generalities(
    db: AsyncSession, skill_id: uuid.UUID, kind: SkillRelationType
) -> list[uuid.UUID]:
    """One step towards the general end of the axis, approved rows only."""
    out: list[uuid.UUID] = []
    if kind is SkillRelationType.IS_A:
        parent_id = (
            await db.execute(select(Skill.parent_id).where(Skill.id == skill_id))
        ).scalar_one_or_none()
        if parent_id is not None:
            out.append(parent_id)
    rows = await db.execute(
        select(SkillRelation.to_skill_id).where(
            SkillRelation.from_skill_id == skill_id,
            SkillRelation.relation == kind.value,
            SkillRelation.status == SkillRelationStatus.APPROVED.value,
        )
    )
    out.extend(rows.scalars().all())
    return out
