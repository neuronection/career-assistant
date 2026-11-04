"""The persisted embedding-model profile registry (plan 52 T2a).

Curated profiles live in :mod:`app.ai.tokenizers.registry`; this service owns
the admin override row, its validation and the read/write API helpers. The
resolution order is admin → curated → fallback and is implemented once in
the registry; here we only load the explicit row for an exact
``(provider_class, model)`` pair.

A profile change is **configuration, never a rewrite**. It does not
rechunk, re-embed or cut over an existing space: plan 52 T3 makes the write
path token-aware, and a chunk-budget change becomes a new space at that
point. The change itself is audited through the existing
``vector.model.changed`` event, so no second ledger is introduced.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import resolution
from app.ai.tokenizers import (
    CL100K_BASE,
    HF_TOKENIZER_FILENAME,
    MAX_TOKENIZER_JSON_BYTES,
    EmbeddingModelProfile,
    get_tokenizer_service,
    provider_class,
    resolve_embedding_profile,
)
from app.ai.tokenizers.registry import (
    CURATED_EMBEDDING_PROFILES,
    UNAVAILABLE_HF_PRESETS,
)
from app.ai.tokenizers.service import CL100K_BASE_BPE_SHA256
from app.core.errors import ValidationError
from app.models.embedding_profile_model import EmbeddingModelProfile as EmbeddingModelProfileRow
from app.models.enums import AITaskType
from app.services.audit import emitter
from app.storage.tokenizer_contract import (
    ChunkConfig,
    TokenizerKind,
    TokenizerSource,
    TokenizerSpec,
)

MAX_MODEL_LENGTH = 200
MAX_PROVIDER_CLASS_LENGTH = 40
MAX_IDENTIFIER_LENGTH = 200
MAX_REVISION_LENGTH = 120
MAX_INPUT_TOKENS = 1_000_000
MAX_BATCH_ITEMS = 4096
MAX_BATCH_TOKENS = 10_000_000
MAX_CHUNK_TOKENS = 1_000_000
MAX_CHUNK_CHARS = 1_000_000

SUPPORTED_PROFILE_KINDS = (
    TokenizerKind.TIKTOKEN,
    TokenizerKind.HF_TOKENIZERS,
    TokenizerKind.HEURISTIC,
)
SUPPORTED_TIKTOKEN_IDENTIFIERS = (CL100K_BASE,)
HF_REPO_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
PINNED_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")

PROFILE_BOUNDS: dict[str, Any] = {
    "max_provider_class_length": MAX_PROVIDER_CLASS_LENGTH,
    "max_model_length": MAX_MODEL_LENGTH,
    "max_identifier_length": MAX_IDENTIFIER_LENGTH,
    "max_revision_length": MAX_REVISION_LENGTH,
    "max_input_tokens": MAX_INPUT_TOKENS,
    "max_batch_items": MAX_BATCH_ITEMS,
    "max_batch_tokens": MAX_BATCH_TOKENS,
    "max_chunk_tokens": MAX_CHUNK_TOKENS,
    "max_chunk_chars": MAX_CHUNK_CHARS,
    "supported_kinds": [kind.value for kind in SUPPORTED_PROFILE_KINDS],
    "supported_tiktoken_identifiers": list(SUPPORTED_TIKTOKEN_IDENTIFIERS),
    "hf_tokenizer_filename": HF_TOKENIZER_FILENAME,
    "max_tokenizer_json_bytes": MAX_TOKENIZER_JSON_BYTES,
    "requires_pinned_revision": True,
}


def _bounded(value: str | None, field: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{field} is required")
    if len(text) > limit:
        raise ValidationError(f"{field} must be at most {limit} characters")
    return text


def _positive(value: int, field: str, *, minimum: int = 1, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise ValidationError(f"{field} must be between {minimum} and {maximum}")
    return value


def _build_spec(
    *,
    tokenizer_kind: str,
    tokenizer_identifier: str,
    tokenizer_revision: str | None,
    tokenizer_artifact_sha256: str | None,
    max_input_tokens: int,
) -> TokenizerSpec:
    kind = str(tokenizer_kind or "").strip()
    if kind not in {member.value for member in SUPPORTED_PROFILE_KINDS}:
        raise ValidationError(
            "tokenizer_kind must be one of "
            f"{sorted(member.value for member in SUPPORTED_PROFILE_KINDS)}"
        )
    identifier = _bounded(tokenizer_identifier, "tokenizer_identifier", MAX_IDENTIFIER_LENGTH)
    revision = (
        None
        if tokenizer_revision is None
        else _bounded(tokenizer_revision, "tokenizer_revision", MAX_REVISION_LENGTH)
    )
    sha = (
        None
        if tokenizer_artifact_sha256 is None
        else _bounded(tokenizer_artifact_sha256, "tokenizer_artifact_sha256", 64).lower()
    )
    limit = _positive(max_input_tokens, "max_input_tokens", minimum=1, maximum=MAX_INPUT_TOKENS)
    try:
        if kind == TokenizerKind.HEURISTIC.value:
            if revision is not None or sha is not None:
                raise ValidationError(
                    "a heuristic profile carries no revision or artifact checksum"
                )
            return TokenizerSpec(
                kind=TokenizerKind.HEURISTIC,
                identifier=identifier,
                max_input_tokens=limit,
                source=TokenizerSource.ADMIN,
            )
        if kind == TokenizerKind.HF_TOKENIZERS.value:
            if not HF_REPO_PATTERN.fullmatch(identifier):
                raise ValidationError(
                    "a Hugging Face profile identifier must be a repository id (org/model)"
                )
            if revision is None or not PINNED_REVISION_PATTERN.fullmatch(revision):
                raise ValidationError(
                    "a Hugging Face profile needs a pinned 40-character commit revision"
                )
            if sha is None or len(sha) != 64:
                raise ValidationError(
                    "a Hugging Face profile needs the tokenizer.json artifact sha256"
                )
            return TokenizerSpec(
                kind=TokenizerKind.HF_TOKENIZERS,
                identifier=identifier,
                max_input_tokens=limit,
                source=TokenizerSource.ADMIN,
                artifact_sha256=sha,
                revision=revision,
            )
        if identifier not in SUPPORTED_TIKTOKEN_IDENTIFIERS:
            raise ValidationError(
                "this build bundles only "
                f"{list(SUPPORTED_TIKTOKEN_IDENTIFIERS)} for tiktoken profiles"
            )
        return TokenizerSpec(
            kind=TokenizerKind.TIKTOKEN,
            identifier=identifier,
            max_input_tokens=limit,
            source=TokenizerSource.ADMIN,
            artifact_sha256=sha or CL100K_BASE_BPE_SHA256,
            revision=revision,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def build_override(
    *,
    provider: str,
    model: str,
    tokenizer_kind: str,
    tokenizer_identifier: str,
    tokenizer_revision: str | None = None,
    tokenizer_artifact_sha256: str | None = None,
    max_input_tokens: int,
    batch_max_items: int,
    batch_max_tokens: int,
    chunk_max_tokens: int,
    chunk_overlap_tokens: int = 0,
    chunk_max_chars: int,
) -> EmbeddingModelProfile:
    """Validate and build an admin override (no database access).

    Every bound is checked here, not only in the HTTP model: the same
    builder serves tests and any future non-HTTP writer. The tokenizer
    contract validates the encoding/exact law, and the chunk budget must
    fit the model input and one batch.
    """
    klass = provider_class(_bounded(provider, "provider_class", MAX_PROVIDER_CLASS_LENGTH))
    model_name = _bounded(model, "model", MAX_MODEL_LENGTH)
    spec = _build_spec(
        tokenizer_kind=tokenizer_kind,
        tokenizer_identifier=tokenizer_identifier,
        tokenizer_revision=tokenizer_revision,
        tokenizer_artifact_sha256=tokenizer_artifact_sha256,
        max_input_tokens=max_input_tokens,
    )
    items = _positive(batch_max_items, "batch_max_items", minimum=1, maximum=MAX_BATCH_ITEMS)
    tokens = _positive(batch_max_tokens, "batch_max_tokens", minimum=1, maximum=MAX_BATCH_TOKENS)
    chunk_tokens = _positive(
        chunk_max_tokens, "chunk_max_tokens", minimum=32, maximum=MAX_CHUNK_TOKENS
    )
    overlap = _positive(
        chunk_overlap_tokens,
        "chunk_overlap_tokens",
        minimum=0,
        maximum=MAX_CHUNK_TOKENS,
    )
    chars = _positive(chunk_max_chars, "chunk_max_chars", minimum=1, maximum=MAX_CHUNK_CHARS)
    try:
        chunk = ChunkConfig(
            max_chunk_tokens=chunk_tokens,
            overlap_tokens=overlap,
            max_chars=chars,
        )
        chunk.assert_fits(spec.max_input_tokens)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if tokens < chunk.max_chunk_tokens:
        raise ValidationError(
            f"batch_max_tokens must fit at least one chunk ({chunk.max_chunk_tokens} tokens)"
        )
    return EmbeddingModelProfile(
        provider_class=klass,
        model=model_name,
        tokenizer=spec,
        chunk=chunk,
        batch_max_items=items,
        batch_max_tokens=tokens,
        max_input_assumed=False,
        override=True,
    )


def _profile_from_row(row: EmbeddingModelProfileRow) -> EmbeddingModelProfile:
    try:
        spec = TokenizerSpec(
            kind=row.tokenizer_kind,
            identifier=row.tokenizer_identifier,
            revision=row.tokenizer_revision,
            artifact_sha256=row.tokenizer_artifact_sha256,
            exact=row.tokenizer_exact,
            max_input_tokens=row.max_input_tokens,
            source=TokenizerSource.ADMIN,
        )
        chunk = ChunkConfig(
            max_chunk_tokens=row.chunk_max_tokens,
            overlap_tokens=row.chunk_overlap_tokens,
            max_chars=row.chunk_max_chars,
        )
    except ValueError as exc:  # pragma: no cover - the writer validates
        raise ValidationError(f"stored embedding profile is invalid: {exc}") from exc
    return EmbeddingModelProfile(
        provider_class=row.provider_class,
        model=row.model_name,
        tokenizer=spec,
        chunk=chunk,
        batch_max_items=row.batch_max_items,
        batch_max_tokens=row.batch_max_tokens,
        max_input_assumed=False,
        override=True,
        updated_by=str(row.updated_by) if row.updated_by is not None else None,
        updated_at=row.updated_at,
    )


async def get_override(db: AsyncSession, klass: str, model: str) -> EmbeddingModelProfile | None:
    """The persisted admin row for one exact provider class/model pair."""
    row = (
        await db.execute(
            select(EmbeddingModelProfileRow).where(
                EmbeddingModelProfileRow.provider_class == klass,
                EmbeddingModelProfileRow.model_name == model,
            )
        )
    ).scalar_one_or_none()
    return None if row is None else _profile_from_row(row)


async def resolve_for(
    db: AsyncSession, provider_type: str | None, model: str | None
) -> EmbeddingModelProfile:
    """Resolve the effective profile for a provider/model pair from the DB."""
    klass = provider_class(provider_type)
    model_name = str(model or "").strip()
    override = await get_override(db, klass, model_name)
    return resolve_embedding_profile(provider_type, model_name, override=override)


def profile_dto(
    profile: EmbeddingModelProfile,
    *,
    service=None,
    runtime: bool = True,
) -> dict[str, Any]:
    """The bounded profile read DTO (no document/query/prompt text).

    The selected tokenizer identity is what the profile *asks* for; ``exact``
    and ``degraded_reason`` describe what will actually count right now.
    ``tokenizer_available`` is false for an unfetched/corrupt HF artifact, so
    the UI can offer the fetch action without pretending the asset exists.
    ``runtime=False`` is the curated-catalog form: it describes the code fact
    without loading every HF asset just to render the list.
    """
    if runtime:
        tokenizer_service = service or get_tokenizer_service()
        effective, degraded = tokenizer_service.effective_spec(profile.tokenizer)
        available = (
            profile.tokenizer.kind is TokenizerKind.HEURISTIC
            or tokenizer_service.available(profile.tokenizer)
        )
    else:
        effective, degraded = profile.tokenizer, None
        available = profile.tokenizer.kind is TokenizerKind.HEURISTIC or profile.usable
    return {
        "provider_class": profile.provider_class,
        "model": profile.model,
        "source": profile.source.value,
        "exact": effective.exact,
        "override": profile.override,
        "identity": profile.tokenizer.identity,
        "counted_identity": effective.identity,
        "tokenizer_available": available,
        "tokenizer_kind": profile.tokenizer.kind.value,
        "tokenizer_identifier": profile.tokenizer.identifier,
        "tokenizer_revision": profile.tokenizer.revision,
        "tokenizer_artifact_sha256": profile.tokenizer.artifact_sha256,
        "max_input_tokens": profile.tokenizer.max_input_tokens,
        "max_input_assumed": profile.max_input_assumed,
        "degraded_reason": degraded,
        "family": profile.family,
        "license": profile.license,
        "source_url": profile.source_url,
        "repository": profile.repository,
        "preset_revision": profile.preset_revision,
        "usable": profile.usable,
        "usable_reason": profile.usable_reason,
        "batch_max_items": profile.batch_max_items,
        "batch_max_tokens": profile.batch_max_tokens,
        "chunk": {
            "max_chunk_tokens": profile.chunk.max_chunk_tokens,
            "overlap_tokens": profile.chunk.overlap_tokens,
            "max_chars": profile.chunk.max_chars,
        },
        "updated_by": profile.updated_by,
        "updated_at": _iso(profile.updated_at),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def list_payload(
    db: AsyncSession,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Curated catalog + admin overrides + the selected resolution.

    Without query params the selected resolution is the assigned embedding
    model (the same pair the tokenizer report reads). With both, it resolves
    the requested pair — the build-space preview uses this.
    """
    if provider is not None and model is not None:
        selected = await resolve_for(db, provider, model)
        requested: dict[str, str] | None = {
            "provider_class": selected.provider_class,
            "model": selected.model,
        }
        assigned = None
    else:
        resolved = await resolution.resolve_task_model(
            db, AITaskType.EMBED.value, None, allow_dev_bootstrap=False
        )
        provider_type = resolved.provider_type if resolved is not None else None
        model_name = resolved.model_name if resolved is not None else None
        selected = await resolve_for(db, provider_type, model_name)
        requested = None
        assigned = (
            {"provider": provider_type, "model": model_name} if resolved is not None else None
        )
    rows = (
        await db.execute(
            select(EmbeddingModelProfileRow).order_by(
                EmbeddingModelProfileRow.provider_class,
                EmbeddingModelProfileRow.model_name,
            )
        )
    ).scalars()
    overrides = [_profile_from_row(row) for row in rows]
    return {
        "state": "ok",
        "requested": requested,
        "assigned": assigned,
        "resolution": profile_dto(selected),
        "curated": [profile_dto(profile, runtime=False) for profile in CURATED_EMBEDDING_PROFILES],
        "unavailable_presets": [
            {
                "family": preset.family,
                "repository": preset.repository,
                "revision": preset.revision,
                "license": preset.license,
                "source_url": preset.source_url,
                "max_input_tokens": preset.max_input_tokens,
                "models": list(preset.models),
                "usable": preset.usable,
                "usable_reason": preset.unusable_reason,
            }
            for preset in UNAVAILABLE_HF_PRESETS
        ],
        "overrides": [profile_dto(profile) for profile in overrides],
        "bounds": PROFILE_BOUNDS,
        "token_aware_writes": False,
    }


async def save_override(
    db: AsyncSession,
    *,
    actor: uuid.UUID,
    profile: EmbeddingModelProfile,
) -> EmbeddingModelProfile:
    """Insert or update one admin override and audit the change atomically."""
    row = (
        await db.execute(
            select(EmbeddingModelProfileRow).where(
                EmbeddingModelProfileRow.provider_class == profile.provider_class,
                EmbeddingModelProfileRow.model_name == profile.model,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = EmbeddingModelProfileRow(
            provider_class=profile.provider_class,
            model_name=profile.model,
        )
        db.add(row)
    row.tokenizer_kind = profile.tokenizer.kind.value
    row.tokenizer_identifier = profile.tokenizer.identifier
    row.tokenizer_revision = profile.tokenizer.revision
    row.tokenizer_artifact_sha256 = profile.tokenizer.artifact_sha256
    row.tokenizer_exact = profile.tokenizer.exact
    row.max_input_tokens = profile.tokenizer.max_input_tokens
    row.batch_max_items = profile.batch_max_items
    row.batch_max_tokens = profile.batch_max_tokens
    row.chunk_max_tokens = profile.chunk.max_chunk_tokens
    row.chunk_overlap_tokens = profile.chunk.overlap_tokens
    row.chunk_max_chars = profile.chunk.max_chars
    row.source = TokenizerSource.ADMIN.value
    row.updated_by = actor
    await db.flush()
    db.add(
        emitter.audit_event(
            actor=actor,
            action="vector.model.changed",
            resource_ref=emitter.resource(
                f"model_profile:{profile.provider_class}/{profile.model}"
            ),
        )
    )
    await db.commit()
    await db.refresh(row)
    return _profile_from_row(row)


async def delete_override(
    db: AsyncSession,
    *,
    actor: uuid.UUID,
    provider: str,
    model: str,
) -> bool:
    """Delete one admin override; the curated/fallback profile takes over."""
    klass = provider_class(provider)
    model_name = str(model or "").strip()
    existing = (
        await db.execute(
            select(EmbeddingModelProfileRow.id).where(
                EmbeddingModelProfileRow.provider_class == klass,
                EmbeddingModelProfileRow.model_name == model_name,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        await db.commit()
        return False
    await db.execute(
        delete(EmbeddingModelProfileRow).where(
            EmbeddingModelProfileRow.provider_class == klass,
            EmbeddingModelProfileRow.model_name == model_name,
        )
    )
    db.add(
        emitter.audit_event(
            actor=actor,
            action="vector.model.changed",
            resource_ref=emitter.resource(f"model_profile:{klass}/{model_name}"),
        )
    )
    await db.commit()
    return True


__all__ = [
    "MAX_BATCH_ITEMS",
    "MAX_BATCH_TOKENS",
    "MAX_CHUNK_CHARS",
    "MAX_CHUNK_TOKENS",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_INPUT_TOKENS",
    "MAX_MODEL_LENGTH",
    "MAX_PROVIDER_CLASS_LENGTH",
    "MAX_REVISION_LENGTH",
    "PROFILE_BOUNDS",
    "SUPPORTED_PROFILE_KINDS",
    "SUPPORTED_TIKTOKEN_IDENTIFIERS",
    "build_override",
    "delete_override",
    "get_override",
    "list_payload",
    "profile_dto",
    "resolve_for",
    "save_override",
]
