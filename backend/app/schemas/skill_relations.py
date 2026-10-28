"""Admin review surface for skill edges (plan 138, step 6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import SkillRelationType


class SkillRelationSkillOut(BaseModel):
    """One pair endpoint with the facts the review queue shows."""

    id: uuid.UUID
    key: str
    label: str
    status: str
    evidence_quote: str | None = None


class SkillRelationOut(BaseModel):
    """One (pair, relation) row — the seam's grain, provenance included."""

    id: uuid.UUID
    relation: SkillRelationType
    status: str
    source: str
    confidence: float | None = None
    evidence: dict | None = None
    decided_by: uuid.UUID | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    from_skill: SkillRelationSkillOut
    to_skill: SkillRelationSkillOut
    alias_candidate: bool = False


class SkillRelationCreateIn(BaseModel):
    """Manual edge add; endpoints accept a skill key or id.

    Manual adds land approved — unless the pair already carries a row,
    whose lifecycle then stands (accept it from the queue).
    """

    model_config = {"extra": "forbid"}

    from_skill: str = Field(min_length=1, max_length=120)
    to_skill: str = Field(min_length=1, max_length=120)
    relation: SkillRelationType
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SkillRelationThresholdsOut(BaseModel):
    """Effective discovery thresholds (constant fallbacks included)."""

    min_support: int
    batch_size: int
    max_pairs_per_run: int
    min_negative_confidence: float


class SkillRelationThresholdsIn(BaseModel):
    """Admin overrides for `skill_relation_learn.thresholds` (clamped)."""

    model_config = {"extra": "forbid"}

    min_support: int = Field(ge=1)
    batch_size: int = Field(ge=1, le=40)
    max_pairs_per_run: int = Field(ge=1)
    min_negative_confidence: float = Field(ge=0.0, le=1.0)


class SkillRelationSaveAliasOut(BaseModel):
    """The saved outcome: the edge row is dismissed (negative edge) and
    the label now resolves through the surviving skill's aliases."""

    relation: SkillRelationOut
    target: SkillRelationSkillOut
    aliases: list[str]


class SkillRelationRunLedgerOut(BaseModel):
    """The run ledger keys the stats view renders (missing counters = 0)."""

    candidates: int = 0
    batches: int = 0
    judged_batches: int = 0
    failed_batches: int = 0
    uncovered: int = 0
    derived: int = 0
    edges_proposed: int = 0
    negatives: int = 0
    dropped: int = 0
    below_bar: int = 0
    materialized: int = 0
    backfilled: int = 0
    capped: bool = False
    watermark: str | None = None

    @classmethod
    def from_result(cls, result: dict | None) -> SkillRelationRunLedgerOut:
        """Render one run ledger; a missing or mistyped counter falls back
        to its default and ``watermark`` renders as null when absent
        (capped/failed/unconfigured runs before any success)."""
        payload = result or {}
        values: dict = {}
        for name, field in cls.model_fields.items():
            default = field.default
            value = payload.get(name)
            if default is None:
                values[name] = value if isinstance(value, str) else None
            elif isinstance(default, bool):
                values[name] = value if isinstance(value, bool) else default
            elif isinstance(default, int):
                values[name] = (
                    value if isinstance(value, int) and not isinstance(value, bool) else default
                )
            else:
                values[name] = value if isinstance(value, type(default)) else default
        return cls(**values)


class SkillRelationRunOut(BaseModel):
    """One discovery run and its ledger."""

    id: uuid.UUID
    status: str
    created_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    ledger: SkillRelationRunLedgerOut
