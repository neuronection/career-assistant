"""Admin retrieval reads, the plan-50 enqueues and the plan-51 action seam.

Plan 50 ships the status/health reads and the ``VECTOR_INDEX`` /
``VECTOR_RECONCILE`` triggers; plan 51 Q1a composes the full
audit/operations read model (overview, spaces, coverage, runs, run detail,
quality, query health, failures, usage) under the same admin-only
``/admin/retrieval`` namespace. Q1b adds the only write seam: reindex,
cancel/retry, space lifecycle, maintenance and the golden-query compare.
Every action is idempotent, space-locked where it mutates, audited under the
``vector.*`` group, and delegates to the existing services/handlers rather
than duplicating execution. Notifications (Q1c) and the UI (Q2) are not here.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.ai.tokenizers import get_tokenizer_service
from app.core.database import get_db, sync_engine
from app.core.errors import NotFoundError, ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobType
from app.models.user_model import User
from app.services import embedding_profiles, tokenizer_fetch, tokenizer_report
from app.services import retrieval_actions as actions
from app.services import retrieval_jobs as retrieval_jobs
from app.services import retrieval_ops_reads as reads
from app.services.audit import emitter
from app.services.deps import require_admin
from app.services.vector_reconcile_service import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_BUDGET,
    DEFAULT_LIMIT,
    DEFAULT_SCAN_LIMIT,
    RECONCILE_KINDS,
    parse_kinds,
    parse_since,
)
from app.services.vector_status import read_health, read_space_statuses
from app.storage import retrieval_ops as ops
from app.storage.tokenizer_contract import ChunkConfig, TokenizerSpec

router = APIRouter(
    prefix="/admin/retrieval", tags=["retrieval-admin"], dependencies=[Depends(require_admin)]
)

INDEXABLE_KINDS = RECONCILE_KINDS

WINDOW_QUERY = Query(default=reads.DEFAULT_WINDOW, pattern="^(24h|7d|30d|90d)$")
SPACE_QUERY = Query(default=None, description="vector space id or name")
RUN_STATUS_QUERY = Query(default=None, pattern="^(queued|running|succeeded|failed|cancelled)$")
FAILURE_KIND_QUERY = Query(
    default=None, pattern="^(embed_provider|indexing|cutover_gate|maintenance)$"
)

IDEMPOTENCY_HEADER = Header(
    default=None,
    alias="Idempotency-Key",
    description=(
        "Client-generated replay key (8-120 chars); a repeat with the same body is a replay"
    ),
)


def _guarded(payload: dict[str, Any]) -> dict[str, Any]:
    """Every read payload passes the family no-raw-text rule before it leaves."""
    return ops.assert_no_raw_text(payload)


def _key(
    header: str | None,
    body: Any,
    *,
    required: bool,
    action: str,
) -> str | None:
    """Resolve the Idempotency-Key (header wins), validating its shape."""
    value = header or getattr(body, "idempotency_key", None)
    if value is None or str(value).strip() == "":
        if required:
            raise ValidationError(
                f"an Idempotency-Key header (or idempotency_key field) is required for {action}"
            )
        return None
    return retrieval_jobs.validate_key(value)


def _action_response(payload: dict[str, Any]) -> JSONResponse:
    """Honor the contract's http_status (202 queued, 200 sync)."""
    return JSONResponse(
        status_code=int(payload.get("http_status") or 200),
        content=payload,
    )


async def _space_or_none(db: AsyncSession, space: str | None):
    if space is None:
        return await reads.default_space(db)
    return await reads.resolve_space(db, space)


class IndexRequest(BaseModel):
    """One document to (re)index; ``space`` defaults to the content space."""

    kind: str = Field(..., description="source kind: posting | job | skill | profile")
    source_id: str = Field(..., description="source row id (UUID)")
    space: str | None = Field(default=None, description="space name; defaults to content")
    force: bool = Field(default=False, description="re-embed even unchanged records")


class ReconcileRequest(BaseModel):
    """One backfill/reconcile run (a resumable, budget-capped batch)."""

    kinds: list[str] | None = Field(
        default=None, description="source kinds to reconcile; default all supported"
    )
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=5000, description="documents per run")
    budget: int = Field(default=DEFAULT_BUDGET, ge=0, le=100_000, description="embed units per run")
    batch_size: int = Field(default=DEFAULT_BATCH_SIZE, ge=1, le=200)
    window_documents: int = Field(
        default=128,
        ge=1,
        le=512,
        description="documents per shared-batch embedding window (plan 201)",
    )
    scan_limit: int = Field(
        default=DEFAULT_SCAN_LIMIT,
        ge=1,
        le=10_000,
        description="source rows per keyset batch",
    )
    since: str | None = Field(default=None, description="ISO timestamp — only rows updated since")
    force: bool = Field(default=False, description="re-embed even unchanged content")
    auto_continue: bool = Field(
        default=True,
        description="enqueue the next bounded batch when this one is partial",
    )
    idempotency_key: str | None = Field(
        default=None, description="optional replay key; the Idempotency-Key header also works"
    )


class ReindexRequest(BaseModel):
    """One bounded reindex of a space (the plan-50 reconcile handler)."""

    space: str = Field(..., description="vector space id or name")
    kind: str | None = Field(default=None, description="one source kind; default all")
    view: str | None = Field(default=None, description="run-scope view label")
    since: str | None = Field(default=None, description="ISO timestamp — only rows updated since")
    budget: int = Field(default=DEFAULT_BUDGET, ge=0, le=100_000, description="embed units")
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=5000, description="documents per run")
    batch_size: int = Field(default=DEFAULT_BATCH_SIZE, ge=1, le=200)
    window_documents: int = Field(
        default=128,
        ge=1,
        le=512,
        description="documents per shared-batch embedding window (plan 201)",
    )
    scan_limit: int = Field(default=DEFAULT_SCAN_LIMIT, ge=1, le=10_000)
    force: bool = Field(default=False)
    auto_continue: bool = Field(default=True)
    idempotency_key: str | None = Field(default=None)


class ActionKeyRequest(BaseModel):
    """Body for path-addressed actions; the header is preferred."""

    idempotency_key: str | None = Field(default=None)


class BuildTokenizerRequest(BaseModel):
    """An explicit pinned tokenizer for a token-aware (v2) build.

    The server derives nothing from the model name here: these fields are the
    admin's selection. ``exact`` may be omitted (it follows ``kind``), and a
    non-heuristic kind needs its artifact checksum (plus a pinned revision for
    Hugging Face). Prefer ``tokenizer_profile`` when the dialog should pin the
    same effective profile the write path resolves.
    """

    kind: str = Field(..., pattern="^(tiktoken|hf_tokenizers|sentencepiece|heuristic)$")
    identifier: str = Field(..., min_length=1, max_length=200)
    revision: str | None = Field(default=None, max_length=120)
    artifact_sha256: str | None = Field(default=None, max_length=64)
    exact: bool | None = Field(
        default=None, description="defaults from kind; heuristic is always false"
    )
    max_input_tokens: int = Field(..., ge=1, le=embedding_profiles.MAX_INPUT_TOKENS)
    source: str = Field(default="admin", pattern="^(provider|curated|admin|fallback)$")


class BuildChunkRequest(BaseModel):
    """The token-aware chunk budget (bounds mirror the tokenizer contract)."""

    max_chunk_tokens: int = Field(..., ge=32, le=embedding_profiles.MAX_CHUNK_TOKENS)
    overlap_tokens: int = Field(default=0, ge=0, le=embedding_profiles.MAX_CHUNK_TOKENS)
    max_chars: int = Field(..., ge=1, le=embedding_profiles.MAX_CHUNK_CHARS)


class BuildProfileReference(BaseModel):
    """Build from the effective embedding profile of one provider/model pair."""

    provider: str = Field(..., min_length=1, max_length=60)
    model: str = Field(..., min_length=1, max_length=120)


class BuildSpaceRequest(BaseModel):
    """Provision a ``building`` space beside the active one.

    Omitting ``tokenizer``/``tokenizer_profile`` and ``chunk`` keeps the legacy
    v1 char-chunk build. Supplying either a resolved-profile reference or an
    explicit tokenizer makes the build token-aware (v2); a half-configured
    request is refused instead of silently falling back to v1.
    """

    name: str = Field(..., min_length=1, max_length=40)
    provider: str = Field(..., min_length=1, max_length=60)
    model: str = Field(..., min_length=1, max_length=120)
    dim: int = Field(..., ge=1, le=3072)
    metric: str = Field(default="cosine")
    normalize: bool = True
    query_prefix: str | None = Field(default=None, max_length=80)
    document_prefix: str | None = Field(default=None, max_length=80)
    tokenizer: BuildTokenizerRequest | None = None
    chunk: BuildChunkRequest | None = None
    tokenizer_profile: BuildProfileReference | None = None
    idempotency_key: str | None = Field(default=None)


class ModelProfileRequest(BaseModel):
    """One bounded admin embedding-tokenizer/limits override.

    The provider class + model pair is the key. The tokenizer kind is
    restricted to what this build can actually load: bundled ``tiktoken``,
    a pinned Hugging Face ``tokenizer.json`` (repo + 40-character commit +
    verified SHA-256) or the conservative heuristic. The server derives
    ``exact`` and ``source`` — a client cannot declare a heuristic as exact.
    """

    provider_class: str = Field(..., min_length=1, max_length=40)
    model: str = Field(..., min_length=1, max_length=200)
    tokenizer_kind: str = Field(..., min_length=1, max_length=30)
    tokenizer_identifier: str = Field(..., min_length=1, max_length=200)
    tokenizer_revision: str | None = Field(default=None, max_length=120)
    tokenizer_artifact_sha256: str | None = Field(
        default=None,
        max_length=64,
        pattern="^[0-9a-fA-F]{64}$",
        description=(
            "packaged/local tokenizer artifact checksum; defaults to the pinned cl100k asset"
        ),
    )
    max_input_tokens: int = Field(..., ge=1, le=embedding_profiles.MAX_INPUT_TOKENS)
    batch_max_items: int = Field(..., ge=1, le=embedding_profiles.MAX_BATCH_ITEMS)
    batch_max_tokens: int = Field(..., ge=1, le=embedding_profiles.MAX_BATCH_TOKENS)
    chunk_max_tokens: int = Field(..., ge=32, le=embedding_profiles.MAX_CHUNK_TOKENS)
    chunk_overlap_tokens: int = Field(default=0, ge=0, le=embedding_profiles.MAX_CHUNK_TOKENS)
    chunk_max_chars: int = Field(..., ge=1, le=embedding_profiles.MAX_CHUNK_CHARS)


class TokenizerFetchRequestBody(BaseModel):
    """One pinned, bounded Hugging Face tokenizer fetch (admin-only job)."""

    repository: str = Field(..., min_length=3, max_length=200, description="org/model")
    revision: str = Field(
        ...,
        min_length=40,
        max_length=40,
        pattern="^[0-9a-fA-F]{40}$",
        description="pinned 40-character commit sha (branches/tags are refused)",
    )
    files: list[str] = Field(
        default_factory=lambda: [tokenizer_fetch.PRIMARY_TOKENIZER_FILE],
        description=(
            "allowlisted small files; must include tokenizer.json "
            f"({tokenizer_fetch.ALLOWED_FILES})"
        ),
    )
    expected_sha256: str | None = Field(
        default=None,
        pattern="^[0-9a-fA-F]{64}$",
        description="optional expected tokenizer.json sha256; a mismatch fails the fetch",
    )
    idempotency_key: str | None = Field(default=None)


class TypedSpaceRequest(BaseModel):
    """Destructive lifecycle action: the typed space name is mandatory."""

    confirm_space_name: str = Field(..., min_length=1, max_length=40)
    idempotency_key: str | None = Field(default=None)


class DropSpaceRequest(TypedSpaceRequest):
    force: bool = Field(
        default=False,
        description="skip the retirement grace period; the typed name is still required",
    )


class MaintenanceRequest(BaseModel):
    """One typed maintenance action (or a scoped retry of failed documents)."""

    space: str = Field(..., description="vector space id or name")
    action: str = Field(
        ...,
        description="index-rebuild | vacuum | orphan-sweep | retry-failed",
    )
    dry_run: bool = Field(default=False)
    limit: int | None = Field(default=None, ge=1, le=5000)
    idempotency_key: str | None = Field(default=None)


class QualityCompareRequest(BaseModel):
    """Score the versioned golden set on the old and new space."""

    space: str = Field(..., description="candidate/new space id or name")
    compare_space: str = Field(..., description="baseline/old space id or name")
    idempotency_key: str | None = Field(default=None)


async def _build_tokenizer_and_chunk(
    db: AsyncSession, request: BuildSpaceRequest
) -> tuple[TokenizerSpec | None, ChunkConfig | None]:
    """Resolve the optional v2 identity; refuse a half-configured request.

    ``tokenizer_profile`` pins the same effective profile (admin → curated →
    fallback, HF included) the write path uses. Explicit ``tokenizer`` fields
    are validated through the contract and must name an artifact this instance
    can actually load; no model name is ever guessed into a tokenizer.
    """
    has_explicit = request.tokenizer is not None
    has_profile = request.tokenizer_profile is not None
    if has_explicit and has_profile:
        raise ValidationError("supply either tokenizer or tokenizer_profile, not both")
    if not has_explicit and not has_profile:
        if request.chunk is not None:
            raise ValidationError("chunk bounds require a tokenizer or tokenizer_profile")
        return None, None

    if has_profile:
        reference = request.tokenizer_profile
        assert reference is not None
        profile = await embedding_profiles.resolve_for(db, reference.provider, reference.model)
        tokenizer, _degraded = get_tokenizer_service().effective_spec(profile.tokenizer)
        chunk = profile.chunk
    else:
        payload = request.tokenizer
        assert payload is not None
        if request.chunk is None:
            raise ValidationError("an explicit tokenizer requires chunk bounds")
        try:
            tokenizer = TokenizerSpec(
                kind=payload.kind,
                identifier=payload.identifier,
                revision=payload.revision,
                artifact_sha256=payload.artifact_sha256,
                exact=payload.exact,
                max_input_tokens=payload.max_input_tokens,
                source=payload.source,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        service = get_tokenizer_service()
        if not tokenizer.exact and tokenizer.kind.value != "heuristic":
            raise ValidationError("a non-heuristic tokenizer must be exact")
        if tokenizer.kind.value != "heuristic" and not service.available(tokenizer):
            raise ValidationError(
                "the selected tokenizer artifact is not available; fetch/configure it "
                "or build from the resolved profile instead"
            )
        chunk = None

    if request.chunk is not None:
        try:
            chunk = ChunkConfig(
                max_chunk_tokens=request.chunk.max_chunk_tokens,
                overlap_tokens=request.chunk.overlap_tokens,
                max_chars=request.chunk.max_chars,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    assert tokenizer is not None and chunk is not None
    try:
        chunk.assert_fits(tokenizer.max_input_tokens)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return tokenizer, chunk


@router.get("/overview")
async def retrieval_overview(
    window: str = WINDOW_QUERY,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Instance-wide retrieval KPIs: spaces, coverage, queries, embed usage."""
    return _guarded(await reads.read_overview(db, window=window))


@router.get("/spaces")
async def retrieval_spaces(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """One row per persisted space with counts, coverage and backend label."""
    return _guarded(await reads.read_spaces(db))


@router.get("/coverage")
async def retrieval_coverage(
    space: str = Query(..., description="vector space id or name"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Latest coverage snapshot per kind; a cold space is ``never_reconciled``."""
    row = await reads.resolve_space(db, space)
    return _guarded(await reads.read_coverage(db, row))


@router.get("/documents/status")
async def retrieval_document_status(
    kind: str = Query(..., description="source kind: posting, job, skill or profile"),
    source_ids: list[str] = Query(
        ...,
        description="source ids to check; repeat the param or join them with commas",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Per-source index state in the active space (admin-only, aggregate-only).

    Returns the five-state enum (``current`` / ``stale`` / ``missing`` /
    ``incomplete`` / ``off``) with record counts, timestamps and the space
    facts. Document text never leaves this route; an empty list, more than
    50 ids or a non-UUID id is a 400 rather than a silent truncation.
    """
    ids = [part.strip() for raw in source_ids for part in raw.split(",") if part.strip()]
    return _guarded(await reads.read_document_status(db, kind=kind, source_ids=ids))


@router.get("/runs")
async def retrieval_runs(
    space: str | None = SPACE_QUERY,
    kind: str | None = Query(default=None, description="run scope source kind"),
    status: str | None = RUN_STATUS_QUERY,
    window: str = WINDOW_QUERY,
    limit: int = Query(default=reads.RUN_PAGE_LIMIT, ge=1, le=reads.RUN_PAGE_MAX),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reindex/backfill/cutover/maintenance runs from ``background_jobs``."""
    row = await reads.resolve_space(db, space) if space is not None else None
    return _guarded(
        await reads.read_runs(
            db, space=row, kind=kind, status=status, window=window, limit=limit, offset=offset
        )
    )


@router.get("/runs/{run_id}")
async def retrieval_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """One run's stage/progress/result counters and bounded ``failed_ids``."""
    return _guarded(await reads.read_run(db, run_id))


@router.get("/quality")
async def retrieval_quality(
    space: str | None = SPACE_QUERY,
    window: str = WINDOW_QUERY,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The versioned golden-query set; ``not_sampled`` until a compare exists."""
    row = await _space_or_none(db, space)
    if row is None:
        raise ValidationError("no vector space to score; pass ?space=<id|name>")
    return _guarded(await reads.read_quality(db, space=row, window=window))


@router.get("/query-health")
async def retrieval_query_health(
    space: str | None = SPACE_QUERY,
    kind: str | None = Query(default=None, description="source kind"),
    window: str = WINDOW_QUERY,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Latency/candidate/zero-result/degraded aggregates from the rollups."""
    row = await _space_or_none(db, space)
    return _guarded(await reads.read_query_health(db, space=row, kind=kind, window=window))


@router.get("/failures")
async def retrieval_failures(
    space: str | None = SPACE_QUERY,
    kind: str | None = FAILURE_KIND_QUERY,
    window: str = WINDOW_QUERY,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Failure groups: embed provider, indexing, cutover gate, maintenance."""
    row = await reads.resolve_space(db, space) if space is not None else None
    return _guarded(await reads.read_failures(db, space=row, kind=kind, window=window))


@router.get("/usage")
async def retrieval_usage(
    space: str | None = SPACE_QUERY,
    kind: str | None = Query(default=None, description="source kind"),
    window: str = WINDOW_QUERY,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Embed calls/tokens by day, space and kind, plus the token budget."""
    row = await reads.resolve_space(db, space) if space is not None else None
    return _guarded(await reads.read_usage(db, space=row, kind=kind, window=window))


@router.get("/tokenizer")
async def retrieval_tokenizer(
    kinds: list[str] | None = Query(
        default=None,
        description="source kinds to shadow-measure; default all supported",
    ),
    limit: int = Query(
        default=tokenizer_report.DEFAULT_CORPUS_LIMIT,
        ge=1,
        le=tokenizer_report.MAX_CORPUS_LIMIT,
        description="source rows per kind (bounded admin sample)",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Tokenizer/limits report: exact-or-approx source and char-vs-token evidence.

    Shadow only — no write, no stored chunk change, no document text. The
    corpus scan is bounded per kind; the multilingual reference block is a
    fixed synthetic fixture.
    """
    selected = [str(kind).strip() for kind in (kinds or tokenizer_report.REPORT_KINDS)]
    unknown = sorted(set(selected) - set(INDEXABLE_KINDS))
    if not selected or unknown:
        raise ValidationError(
            f"Unknown retrieval kind(s): {unknown or selected!r} "
            f"(expected one of {INDEXABLE_KINDS})"
        )
    return _guarded(await tokenizer_report.build_report(db, kinds=selected, limit_per_kind=limit))


@router.get("/model-profiles")
async def retrieval_model_profiles(
    provider: str | None = Query(
        default=None,
        max_length=embedding_profiles.MAX_PROVIDER_CLASS_LENGTH,
        description="provider type/label for a preview resolution",
    ),
    model: str | None = Query(
        default=None,
        max_length=embedding_profiles.MAX_MODEL_LENGTH,
        description="embedding model id for a preview resolution",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The curated catalog + admin overrides + the effective profile.

    With ``provider`` and ``model`` the ``resolution`` previews that exact
    pair (the build-space selector); without them it describes the assigned
    embedding model. Curated profiles are read-only code facts; admin rows
    are the explicit override. Nothing here rechunks or cuts over a space.
    """
    if (provider is None) != (model is None):
        raise ValidationError("pass both provider and model, or neither")
    return _guarded(await embedding_profiles.list_payload(db, provider=provider, model=model))


@router.put("/model-profiles")
async def retrieval_save_model_profile(
    request: ModelProfileRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Save one bounded admin tokenizer/limit override for a model pair."""
    profile = embedding_profiles.build_override(
        provider=request.provider_class,
        model=request.model,
        tokenizer_kind=request.tokenizer_kind,
        tokenizer_identifier=request.tokenizer_identifier,
        tokenizer_revision=request.tokenizer_revision,
        tokenizer_artifact_sha256=request.tokenizer_artifact_sha256,
        max_input_tokens=request.max_input_tokens,
        batch_max_items=request.batch_max_items,
        batch_max_tokens=request.batch_max_tokens,
        chunk_max_tokens=request.chunk_max_tokens,
        chunk_overlap_tokens=request.chunk_overlap_tokens,
        chunk_max_chars=request.chunk_max_chars,
    )
    saved = await embedding_profiles.save_override(db, actor=user.id, profile=profile)
    return _guarded(
        {
            "state": "ok",
            "profile": embedding_profiles.profile_dto(saved),
            "token_aware_writes": True,
        }
    )


@router.delete("/model-profiles")
async def retrieval_delete_model_profile(
    provider: str = Query(
        ...,
        max_length=embedding_profiles.MAX_PROVIDER_CLASS_LENGTH,
        description="provider type/label of the override",
    ),
    model: str = Query(
        ...,
        max_length=embedding_profiles.MAX_MODEL_LENGTH,
        description="embedding model id of the override",
    ),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Drop the admin override; the curated profile (or fallback) returns."""
    deleted = await embedding_profiles.delete_override(
        db, actor=user.id, provider=provider, model=model
    )
    resolved = await embedding_profiles.resolve_for(db, provider, model)
    return _guarded(
        {
            "state": "ok",
            "deleted": deleted,
            "resolution": embedding_profiles.profile_dto(resolved),
            "token_aware_writes": True,
        }
    )


@router.post("/tokenizer/fetch")
async def retrieval_tokenizer_fetch(
    request: TokenizerFetchRequestBody,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Queue one pinned tokenizer asset fetch (never on the request path).

    The handler validates the host/file allowlist, size cap and SHA-256,
    caches under the content hash, and audits ``vector.tokenizer.*``. A repeat
    with the same idempotency key and body returns the original job.
    """
    key = _key(idempotency_key, request, required=True, action="tokenizer fetch")
    try:
        fetch_request = tokenizer_fetch.TokenizerFetchRequest.from_payload(request.model_dump())
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    payload = {
        "repository": fetch_request.repository,
        "revision": fetch_request.revision,
        "files": list(fetch_request.files),
        "expected_sha256": fetch_request.expected_sha256,
    }
    audit = emitter.audit_event(
        actor=user.id,
        action="vector.tokenizer.fetch_requested",
        resource_ref=emitter.resource(
            f"tokenizer:{fetch_request.repository}@{fetch_request.revision}",
            files=",".join(fetch_request.files),
        ),
    )
    job, deduplicated = await retrieval_jobs.enqueue_retrieval_job(
        db,
        job_type=BackgroundJobType.TOKENIZER_FETCH.value,
        payload=payload,
        idempotency_key=str(key),
        user_id=user.id,
        lock=False,
        audit=audit,
    )
    return _guarded(
        {
            "state": "ok",
            "job_id": str(job.id),
            "job_type": job.job_type,
            "status": job.status,
            "progress": job.progress,
            "stage": job.stage,
            "requested": payload,
            "deduplicated": deduplicated,
            "idempotency_key": job.idempotency_key,
        }
    )


@router.get("/tokenizer/fetch/{job_id}")
async def retrieval_tokenizer_fetch_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Read one tokenizer fetch job's status/progress/result (admin-only)."""
    try:
        parsed = uuid.UUID(job_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"job_id must be a UUID, got {job_id!r}") from exc
    job = await db.get(BackgroundJob, parsed)
    if job is None or job.job_type != BackgroundJobType.TOKENIZER_FETCH.value:
        raise NotFoundError("tokenizer fetch job not found")
    return _guarded(
        {
            "state": "ok",
            "job_id": str(job.id),
            "status": job.status,
            "progress": job.progress,
            "stage": job.stage,
            "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
            "error": job.error,
            "result": job.result,
            "requested": job.payload,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }
    )


@router.get("/status")
async def retrieval_status(user: User = Depends(require_admin)) -> list[dict[str, Any]]:
    """Per-space documents/records, coverage snapshot and last reindex."""
    with Session(sync_engine) as session:
        return read_space_statuses(session)


@router.get("/health")
async def retrieval_health(user: User = Depends(require_admin)) -> dict[str, Any]:
    """Backend, extension version, capability caps and per-space health."""
    from app.storage.vector_store import VectorStoreService

    with Session(sync_engine) as session:
        return read_health(session, store=VectorStoreService(sync_engine))


@router.post("/index")
async def enqueue_index(
    request: IndexRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Enqueue a ``VECTOR_INDEX`` run for one document."""
    from app.services.job_worker import enqueue

    if request.kind not in INDEXABLE_KINDS:
        raise ValidationError(
            f"Unknown retrieval kind: {request.kind!r} (expected one of {INDEXABLE_KINDS})"
        )
    try:
        source_id = str(uuid.UUID(request.source_id))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"source_id must be a UUID, got {request.source_id!r}") from exc
    payload: dict[str, Any] = {
        "kind": request.kind,
        "source_id": source_id,
        "force": bool(request.force),
    }
    if request.space:
        payload["space"] = request.space
    job = await enqueue(
        db,
        BackgroundJobType.VECTOR_INDEX.value,
        payload,
        user_id=user.id,
    )
    return {
        "job_id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "payload": payload,
    }


@router.post("/reconcile")
async def enqueue_reconcile(
    request: ReconcileRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Enqueue a ``VECTOR_RECONCILE`` run (backfill / drift repair).

    Thin enqueue: the handler owns composing, classification, the embed
    budget and the coverage snapshots, so the run is a ``background_jobs``
    row (plan 51's Runs view reads it) and the embed spend lands on the system
    path rather than the requesting admin's budget. The legacy endpoint now
    rides the same replay/lock/audit seam as ``POST /reindex``: an optional
    key makes it replay-deduped, and the run always takes the space lock.
    """
    try:
        payload: dict[str, Any] = {
            "limit": request.limit,
            "budget": request.budget,
            "batch_size": request.batch_size,
            "window_documents": request.window_documents,
            "scan_limit": request.scan_limit,
            "force": bool(request.force),
            "auto_continue": bool(request.auto_continue),
        }
        kinds = parse_kinds(request.kinds)
        if kinds is not None:
            unknown = [kind for kind in kinds if kind not in INDEXABLE_KINDS]
            if unknown:
                raise ValidationError(
                    f"Unknown retrieval kind(s): {unknown} (expected {sorted(INDEXABLE_KINDS)})"
                )
            payload["kinds"] = list(kinds)
        since = parse_since(request.since)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if since is not None:
        payload["since"] = since.isoformat()
    key = _key(idempotency_key, request, required=False, action="reconcile")
    if key is None:
        key = f"auto:{uuid.uuid4().hex}"
    try:
        space = await reads.resolve_space(db, "content")
    except NotFoundError:
        # The handler's default is the content space; if it does not exist
        # yet, there is no space to lock (the first index creates it).
        space = None
    audit = emitter.audit_event(
        actor=user.id,
        action="vector.reindex.started",
        resource_ref=emitter.resource(
            f"space:{space.id}" if space is not None else "space:content",
            trigger="reconcile",
        ),
    )
    job, deduplicated = await retrieval_jobs.enqueue_retrieval_job(
        db,
        job_type=BackgroundJobType.VECTOR_RECONCILE.value,
        payload=payload,
        idempotency_key=key,
        user_id=user.id,
        space_id=space.id if space is not None else None,
        lock=space is not None,
        audit=audit,
    )
    return {
        "job_id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "payload": payload,
        "idempotency_key": job.idempotency_key,
        "deduplicated": deduplicated,
    }


# ---------------------------------------------------------------------------
# the plan-51 Q1b action surface
# ---------------------------------------------------------------------------


@router.post("/reindex")
async def retrieval_reindex(
    request: ReindexRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Queue the existing ``VECTOR_RECONCILE`` handler for one bounded run."""
    key = _key(idempotency_key, request, required=True, action="reindex")
    payload = await actions.start_reindex(
        db,
        space_ref=request.space,
        kind=request.kind,
        view=request.view,
        since=request.since,
        window_documents=request.window_documents,
        budget=request.budget,
        limit=request.limit,
        batch_size=request.batch_size,
        scan_limit=request.scan_limit,
        force=request.force,
        auto_continue=request.auto_continue,
        idempotency_key=str(key),
        actor=user.id,
    )
    return _action_response(payload)


@router.post("/runs/{run_id}/cancel")
async def retrieval_cancel_run(
    run_id: str,
    request: ActionKeyRequest | None = None,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Request cancellation; the running work observes the flag itself."""
    key = _key(idempotency_key, request, required=True, action="cancel")
    payload = await actions.cancel_run(db, run_id=run_id, idempotency_key=str(key), actor=user.id)
    return _action_response(payload)


@router.post("/runs/{run_id}/retry")
async def retrieval_retry_run(
    run_id: str,
    request: ActionKeyRequest | None = None,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Bounded re-enqueue of a terminal run under a fresh idempotency scope."""
    key = _key(idempotency_key, request, required=True, action="retry")
    payload = await actions.retry_run(db, run_id=run_id, idempotency_key=str(key), actor=user.id)
    return _action_response(payload)


@router.post("/spaces")
async def retrieval_build_space(
    request: BuildSpaceRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Provision a ``building`` space through the lifecycle service."""
    key = _key(idempotency_key, request, required=True, action="build")
    tokenizer, chunk = await _build_tokenizer_and_chunk(db, request)
    payload = await actions.build_space(
        db,
        name=request.name,
        provider=request.provider,
        model=request.model,
        dim=request.dim,
        metric=request.metric,
        normalize=request.normalize,
        query_prefix=request.query_prefix,
        document_prefix=request.document_prefix,
        idempotency_key=str(key),
        actor=user.id,
        tokenizer=tokenizer,
        chunk=chunk,
    )
    return _action_response(payload)


@router.post("/spaces/{space_id}/activate")
async def retrieval_activate_space(
    space_id: str,
    request: ActionKeyRequest | None = None,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Activate only when coverage **and** the golden-query quality gate pass."""
    key = _key(idempotency_key, request, required=True, action="activate")
    payload = await actions.activate_space(
        db, space_ref=space_id, idempotency_key=str(key), actor=user.id
    )
    return _action_response(payload)


@router.post("/spaces/{space_id}/retire")
async def retrieval_retire_space(
    space_id: str,
    request: TypedSpaceRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Retire a non-active space; the typed name must match exactly."""
    key = _key(idempotency_key, request, required=True, action="retire")
    payload = await actions.retire_space(
        db,
        space_ref=space_id,
        confirm_space_name=request.confirm_space_name,
        idempotency_key=str(key),
        actor=user.id,
    )
    return _action_response(payload)


@router.post("/spaces/{space_id}/drop")
async def retrieval_drop_space(
    space_id: str,
    request: DropSpaceRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Drop a retired space; the typed name is mandatory (never a boolean)."""
    key = _key(idempotency_key, request, required=True, action="drop")
    payload = await actions.drop_space(
        db,
        space_ref=space_id,
        confirm_space_name=request.confirm_space_name,
        force=request.force,
        idempotency_key=str(key),
        actor=user.id,
    )
    return _action_response(payload)


@router.post("/maintenance")
async def retrieval_maintenance(
    request: MaintenanceRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Queue one typed maintenance action (index-rebuild/vacuum/orphan/retry)."""
    key = _key(idempotency_key, request, required=True, action="maintenance")
    payload = await actions.run_maintenance(
        db,
        space_ref=request.space,
        action=request.action,
        dry_run=request.dry_run,
        limit=request.limit,
        idempotency_key=str(key),
        actor=user.id,
    )
    return _action_response(payload)


@router.post("/quality/compare")
async def retrieval_quality_compare(
    request: QualityCompareRequest,
    idempotency_key: str | None = IDEMPOTENCY_HEADER,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run the versioned golden set on old vs new space; persist the result."""
    key = _key(idempotency_key, request, required=False, action="quality compare")
    payload = await actions.compare_quality(
        db,
        space_ref=request.space,
        compare_space_ref=request.compare_space,
        idempotency_key=key,
        actor=user.id,
    )
    return _action_response(payload)
