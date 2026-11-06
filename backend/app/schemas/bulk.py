"""Shared admin bulk-action contract (plan 200)."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

MAX_BULK_IDS = 200


class BulkFailureOut(BaseModel):
    """One per-item failure: the id plus a human-readable reason."""

    id: uuid.UUID
    reason: str


class BulkActionOut(BaseModel):
    """Outcome of one bulk call — acted-on ids, per-item failures, and an
    optional post-commit warning (the action landed, a derived rebuild did
    not)."""

    affected: list[uuid.UUID] = Field(default_factory=list)
    failed: list[BulkFailureOut] = Field(default_factory=list)
    warning: str | None = None


class BulkIdsIn(BaseModel):
    """Shared request body: a bounded id batch, no unknown keys."""

    model_config = {"extra": "forbid"}

    ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK_IDS)


class OverlayBulkIn(BulkIdsIn):
    """Approve or reject a batch of catalog-label overlays."""

    action: Literal["approve", "reject"]


class EnrichmentBulkIn(BulkIdsIn):
    """Apply or reject a batch of enrichment proposals.

    Capped at 100 (not the shared 200): applying refits fit for every user
    across the batch in one pass, so the request cost scales with the batch.
    """

    action: Literal["apply", "reject"]
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
