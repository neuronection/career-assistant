"""The ``job_postings.mapping_features`` audit payload (plan 164 S1.9, P2b).

One validated, bounded document per automatic mapping: the stage-2
candidate list (job code/id, deterministic score, semantic score, blend,
shared taxonomy keys, per-view semantic scores), the pinned policy
thresholds, the embedding ``space_key`` and the structured degradation
reason. It is an open audit payload (``keep-open`` in the JSONB inventory)
validated at the service boundary by :class:`MappingFeatures`.

Bounds: the top five candidates and at most twenty shared skills per
candidate, every score rounded to four decimals. The payload is deliberately
smaller than the rerank's working set (K = 25) so the audit trail stays
readable and the storage envelope stays ~2-3 KB/posting.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.postings.mapping_candidates import CatalogCandidate, shared_skill_keys
from app.services.postings.semantic_rerank import RerankSignal

MAPPING_FEATURES_SCHEMA_VERSION = 1
MAX_FEATURE_CANDIDATES = 5
MAX_SHARED_SKILLS = 20


class MappingCandidateFeatures(BaseModel):
    """One candidate row in the bounded audit payload."""

    job_code: str
    job_id: str
    deterministic: float | None = None
    semantic: float | None = None
    blend: float | None = None
    shared_skills: list[str] = Field(default_factory=list)
    per_view: dict[str, float] = Field(default_factory=dict)


class MappingPolicyFeatures(BaseModel):
    """The pinned thresholds that produced the decision."""

    tau_job: float
    delta: float
    k: int
    blend_deterministic: float
    blend_semantic: float
    semantic_threshold: float
    semantic_min_shared_skills: int


class MappingFeatures(BaseModel):
    """The complete, versioned mapping provenance document."""

    schema_version: int = MAPPING_FEATURES_SCHEMA_VERSION
    mapping_version: int
    space_key: str | None = None
    degraded: str | None = None
    policy: MappingPolicyFeatures
    candidates: list[MappingCandidateFeatures] = Field(default_factory=list)


def _round(value: float | None) -> float | None:
    return round(float(value), 4) if value is not None else None


async def build_mapping_features(
    db: AsyncSession,
    *,
    candidates: Sequence[CatalogCandidate],
    rerank: RerankSignal | None,
    mapping_version: int,
    tau_job: float,
    delta: float,
    k: int,
    blend_deterministic: float,
    blend_semantic: float,
    semantic_threshold: float,
    semantic_min_shared_skills: int,
    space_key: str | None = None,
    degraded: str | None = None,
) -> dict[str, Any]:
    """Build and validate the bounded mapping provenance payload.

    When the rerank ran its ordered candidates are persisted (that is the
    explainable order); otherwise the deterministic order is used. Shared
    skill ids are resolved to stable taxonomy keys once per payload.
    """
    rows: list[
        tuple[
            str,
            str,
            float | None,
            float | None,
            float | None,
            tuple[uuid.UUID, ...],
            dict[str, float],
        ]
    ] = []
    if rerank is not None and rerank.ran and rerank.candidates:
        for rerank_item in rerank.candidates[:MAX_FEATURE_CANDIDATES]:
            rows.append(
                (
                    rerank_item.job_id,
                    rerank_item.code,
                    rerank_item.deterministic,
                    rerank_item.semantic,
                    rerank_item.blend,
                    rerank_item.shared_skill_ids,
                    dict(rerank_item.per_view),
                )
            )
    else:
        for det_item in candidates[:MAX_FEATURE_CANDIDATES]:
            rows.append(
                (
                    det_item.job_id,
                    det_item.code,
                    det_item.score,
                    None,
                    None,
                    det_item.shared_skill_ids,
                    {},
                )
            )

    all_shared: set[uuid.UUID] = set()
    for _job_id, _code, _det, _sem, _blend, shared_ids, _per_view in rows:
        all_shared.update(shared_ids)
    keys = await shared_skill_keys(db, all_shared)

    features = MappingFeatures(
        mapping_version=mapping_version,
        space_key=space_key,
        degraded=degraded,
        policy=MappingPolicyFeatures(
            tau_job=round(float(tau_job), 4),
            delta=round(float(delta), 4),
            k=int(k),
            blend_deterministic=round(float(blend_deterministic), 4),
            blend_semantic=round(float(blend_semantic), 4),
            semantic_threshold=round(float(semantic_threshold), 4),
            semantic_min_shared_skills=int(semantic_min_shared_skills),
        ),
        candidates=[
            MappingCandidateFeatures(
                job_code=code,
                job_id=job_id,
                deterministic=_round(det),
                semantic=_round(sem),
                blend=_round(blend),
                shared_skills=sorted(keys.get(skill_id, str(skill_id)) for skill_id in shared_ids)[
                    :MAX_SHARED_SKILLS
                ],
                per_view={view: round(float(value), 4) for view, value in sorted(per_view.items())},
            )
            for job_id, code, det, sem, blend, shared_ids, per_view in rows
        ],
    )
    return features.model_dump(mode="json")


__all__ = [
    "MAPPING_FEATURES_SCHEMA_VERSION",
    "MAX_FEATURE_CANDIDATES",
    "MAX_SHARED_SKILLS",
    "MappingCandidateFeatures",
    "MappingFeatures",
    "MappingPolicyFeatures",
    "build_mapping_features",
]
