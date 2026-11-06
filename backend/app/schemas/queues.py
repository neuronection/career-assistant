"""Row shapes for the two moderation queues behind `/settings/taxonomy`
(plans 185/202/206). Both are keyset-paged by `schemas.common.CursorPage`.
"""

from pydantic import BaseModel


class EnrichmentQueueItem(BaseModel):
    """One catalog-v2 enrichment proposal awaiting review."""

    id: str
    code: str
    title: str
    proposal: dict | None = None
    proposed_at: str | None = None


class JobProposalExistingJob(BaseModel):
    """The catalog type a v2 proposal maps onto."""

    code: str
    title: str
    status: str
    family_key: str = ""
    short_description: str = ""


class JobProposalCatalogCandidateOut(BaseModel):
    """One actionable catalog candidate for the proposal's title."""

    code: str
    title: str
    family_key: str = ""
    family_label: str = ""
    short_description: str = ""
    score: float
    source: str


class JobProposalDuplicateOut(BaseModel):
    """A published/draft type close enough to the proposal to warn about."""

    code: str
    title: str
    score: float
    reason: str


class JobProposalQueueItem(BaseModel):
    """One posting-sourced "create this job type" proposal (plans 185/202)."""

    id: str
    ref: str
    title: str
    org: str | None = None
    url: str | None = None
    proposal: dict | None = None
    proposed_at: str | None = None
    suggested_family_key: str | None = None
    mapping_signals: dict | None = None
    extract_version: int | None = None
    existing_job: JobProposalExistingJob | None = None
    catalog_candidates: list[JobProposalCatalogCandidateOut] = []
    duplicate_candidates: list[JobProposalDuplicateOut] = []
