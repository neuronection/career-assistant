"""Admin review surface for skill relations (plan 138, step 6).

One resource on the ``/admin`` family; every write goes through
:class:`SkillRelationService` (the single write seam) and every write that
can add an approved ``is_a`` runs the tree catch-up so the taxonomy
reflects the human's click immediately (step 7).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import DomainError, NotFoundError
from app.models.enums import SkillRelationType
from app.models.taxonomy_model import Skill, SkillRelation
from app.schemas.skill_relations import (
    SkillRelationCreateIn,
    SkillRelationOut,
    SkillRelationRunLedgerOut,
    SkillRelationRunOut,
    SkillRelationSaveAliasOut,
    SkillRelationSkillOut,
    SkillRelationThresholdsIn,
    SkillRelationThresholdsOut,
)
from app.services.catalog.skill_relation_learn import (
    Thresholds,
    backfill_parent_edges,
    list_runs,
    load_thresholds,
    save_thresholds,
)
from app.services.catalog.skill_relations import SkillRelationService
from app.services.catalog.taxonomy_service import TaxonomyService
from app.services.deps import get_current_user, require_admin

router = APIRouter(
    prefix="/admin/skill-relations", tags=["admin"], dependencies=[Depends(require_admin)]
)


def _endpoint_out(skill: Skill) -> SkillRelationSkillOut:
    return SkillRelationSkillOut(
        id=skill.id,
        key=skill.key,
        label=skill.label,
        status=skill.status,
        evidence_quote=(skill.provenance or {}).get("evidence_quote"),
    )


def _alias_candidate(first: Skill, second: Skill) -> bool:
    """A proposed label row paired with an active skill — the save-as-alias
    affordance (decision 6: a raw label is an alias, never an edge)."""
    return {first.status, second.status} == {"active", "proposed"}


async def _out(db: AsyncSession, rows: list[SkillRelation]) -> list[SkillRelationOut]:
    ids = {row.from_skill_id for row in rows} | {row.to_skill_id for row in rows}
    skills: dict[uuid.UUID, Skill] = {}
    if ids:
        for skill in (await db.execute(select(Skill).where(Skill.id.in_(ids)))).scalars().all():
            skills[skill.id] = skill
    out: list[SkillRelationOut] = []
    for row in rows:
        first = skills[row.from_skill_id]
        second = skills[row.to_skill_id]
        out.append(
            SkillRelationOut(
                id=row.id,
                relation=SkillRelationType(row.relation),
                status=row.status,
                source=row.source,
                confidence=row.confidence,
                evidence=row.evidence,
                decided_by=row.decided_by,
                decided_at=row.decided_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
                from_skill=_endpoint_out(first),
                to_skill=_endpoint_out(second),
                alias_candidate=_alias_candidate(first, second),
            )
        )
    return out


async def _catch_up(db: AsyncSession, row: SkillRelation) -> None:
    if row.status == "approved" and row.relation == SkillRelationType.IS_A.value:
        await backfill_parent_edges(db)


async def _one(db: AsyncSession, row: SkillRelation) -> SkillRelationOut:
    return (await _out(db, [row]))[0]


def _http(exc: DomainError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(code, str(exc))


@router.get("", response_model=list[SkillRelationOut])
async def list_skill_relations(
    row_status: str | None = Query(
        default=None, alias="status", pattern="^(proposed|approved|rejected)$"
    ),
    skill_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[SkillRelationOut]:
    """The review queue / editor listing (one row per (pair, relation),
    newest first and bounded)."""
    rows = await SkillRelationService(db).list_relations(
        status=row_status, skill_id=skill_id, limit=limit
    )
    return await _out(db, rows)


@router.get("/thresholds", response_model=SkillRelationThresholdsOut)
async def get_skill_relation_thresholds(
    db: AsyncSession = Depends(get_db),
) -> SkillRelationThresholdsOut:
    """Effective discovery thresholds (constant fallbacks included)."""
    thresholds = await load_thresholds(db)
    return SkillRelationThresholdsOut(
        min_support=thresholds.min_support,
        batch_size=thresholds.batch_size,
        max_pairs_per_run=thresholds.max_pairs_per_run,
        min_negative_confidence=thresholds.min_negative_confidence,
    )


@router.put("/thresholds", response_model=SkillRelationThresholdsOut)
async def put_skill_relation_thresholds(
    data: SkillRelationThresholdsIn,
    db: AsyncSession = Depends(get_db),
) -> SkillRelationThresholdsOut:
    """Admin overrides for the discovery job (clamped server-side)."""
    thresholds = Thresholds(**data.model_dump())
    await save_thresholds(db, thresholds)
    return SkillRelationThresholdsOut(
        min_support=thresholds.min_support,
        batch_size=thresholds.batch_size,
        max_pairs_per_run=thresholds.max_pairs_per_run,
        min_negative_confidence=thresholds.min_negative_confidence,
    )


@router.get("/runs", response_model=list[SkillRelationRunOut])
async def list_skill_relation_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[SkillRelationRunOut]:
    """Recent discovery runs and their ledgers (watermark may be null)."""
    runs = await list_runs(db, limit=limit)
    return [
        SkillRelationRunOut(
            id=run.id,
            status=run.status,
            created_at=run.created_at,
            finished_at=run.finished_at,
            error=run.error,
            ledger=SkillRelationRunLedgerOut.from_result(run.result),
        )
        for run in runs
    ]


@router.post("", response_model=SkillRelationOut, status_code=201)
async def add_skill_relation(
    data: SkillRelationCreateIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillRelationOut:
    """Manual edge add — approved on arrival when the pair is new.

    An existing (pair, relation) row refreshes its confidence instead of
    duplicating and keeps its own lifecycle (the seam's dedup-update —
    accept it from the queue); relation kinds are re-pointed by removing
    the row and re-adding it (manual edit).
    """
    service = SkillRelationService(db)
    try:
        row = await service.add(
            data.from_skill,
            data.to_skill,
            data.relation,
            source="manual",
            confidence=data.confidence,
            decided_by=user.id,
        )
    except DomainError as exc:
        raise _http(exc) from exc
    await _catch_up(db, row)
    return await _one(db, row)


@router.post("/{relation_id}/accept", response_model=SkillRelationOut)
async def accept_skill_relation(
    relation_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillRelationOut:
    """Accept a proposed edge (`approve()` — cycles are re-checked and
    refused at click time, leaving the row proposed)."""
    service = SkillRelationService(db)
    try:
        row = await service.approve(relation_id, decided_by=user.id)
    except DomainError as exc:
        raise _http(exc) from exc
    await _catch_up(db, row)
    return await _one(db, row)


@router.post("/{relation_id}/dismiss", response_model=SkillRelationOut)
async def dismiss_skill_relation(
    relation_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillRelationOut:
    """Dismiss a suggestion — `reject()`, i.e. the negative edge (this
    pair + relation never comes back)."""
    service = SkillRelationService(db)
    try:
        row = await service.reject(relation_id, decided_by=user.id)
    except DomainError as exc:
        raise _http(exc) from exc
    return await _one(db, row)


@router.post("/{relation_id}/save-alias", response_model=SkillRelationSaveAliasOut)
async def save_skill_relation_as_alias(
    relation_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillRelationSaveAliasOut:
    """The alias-add path (decision 6): a raw label is not an edge.

    The proposed label row merges into the active skill — its key/label
    become aliases the matcher resolves — and the edge row is dismissed so
    the pair never returns as an edge suggestion.
    """
    service = SkillRelationService(db)
    try:
        row = await service.get(relation_id)
    except DomainError as exc:
        raise _http(exc) from exc
    if row.status == "approved":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "An approved edge is not an alias candidate — dismiss it first",
        )
    skills = {
        skill.id: skill
        for skill in (
            (
                await db.execute(
                    select(Skill).where(Skill.id.in_([row.from_skill_id, row.to_skill_id]))
                )
            )
            .scalars()
            .all()
        )
    }
    first, second = skills[row.from_skill_id], skills[row.to_skill_id]
    if not _alias_candidate(first, second):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Save-as-alias needs one proposed label row and one active skill",
        )
    source, target = (first, second) if first.status == "proposed" else (second, first)
    try:
        merged = await TaxonomyService(db).merge(source.id, target.id)
        row = await service.reject(row.id, decided_by=user.id)
    except DomainError as exc:
        raise _http(exc) from exc
    return SkillRelationSaveAliasOut(
        relation=(await _out(db, [row]))[0],
        target=_endpoint_out(merged),
        aliases=list(merged.aliases or []),
    )


@router.delete("/{relation_id}", status_code=204)
async def remove_skill_relation(
    relation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Hard-delete an edge (admin cleanup; dismiss is the negative edge)."""
    service = SkillRelationService(db)
    try:
        await service.remove(relation_id)
    except DomainError as exc:
        raise _http(exc) from exc
