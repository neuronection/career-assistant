"""Read-only tokenizer/limits evidence for Tools -> Retrieval (plan 52 T1-min).

Nothing here writes: it composes the same views/records the char chunker
already produces, counts tokens with the resolved tokenizer, and returns
**aggregates only** — no document text, query text or prompt ever leaves.
The corpus scan is bounded per kind and is an admin read, never a request on
the retrieval hot path.

The multilingual reference block is a fixed synthetic corpus shipped under
``app/data/tokenizers``; it makes the char-vs-token mismatch visible for
English, Greek, German, CJK and code/markdown even before a real corpus is
indexed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import resolution
from app.ai.tokenizers import (
    EmbeddingModelProfile,
    TokenizerService,
    get_tokenizer_service,
)
from app.models.enums import AITaskType
from app.services import embedding_profiles
from app.services.vector_composers import (
    BODY_CHUNK_CHARS,
    BODY_CHUNK_OVERLAP_CHARS,
    CHUNKER_VERSION,
    COMPOSER_VERSION,
    ComposedRecord,
)
from app.services.vector_index_service import list_sources, load_source
from app.storage import retrieval_ops as ops
from app.storage.tokenizer_contract import TokenizerSpec

logger = logging.getLogger(__name__)

REFERENCE_CORPUS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "tokenizers" / ("reference_corpus.json")
)

REPORT_KINDS = ("posting", "job", "profile", "skill")
DEFAULT_CORPUS_LIMIT = 10
MAX_CORPUS_LIMIT = 100


@dataclass(frozen=True)
class _Bucket:
    documents: int = 0
    records: int = 0
    chars: int = 0
    tokens: int = 0
    max_record_tokens: int = 0
    records_over_limit: int = 0
    failed_documents: int = 0

    def add_record(self, chars: int, tokens: int, limit: int) -> _Bucket:
        return _Bucket(
            documents=self.documents,
            records=self.records + 1,
            chars=self.chars + chars,
            tokens=self.tokens + tokens,
            max_record_tokens=max(self.max_record_tokens, tokens),
            records_over_limit=self.records_over_limit + (1 if tokens > limit else 0),
            failed_documents=self.failed_documents,
        )

    def plus(self, other: _Bucket) -> _Bucket:
        return _Bucket(
            documents=self.documents + other.documents,
            records=self.records + other.records,
            chars=self.chars + other.chars,
            tokens=self.tokens + other.tokens,
            max_record_tokens=max(self.max_record_tokens, other.max_record_tokens),
            records_over_limit=self.records_over_limit + other.records_over_limit,
            failed_documents=self.failed_documents + other.failed_documents,
        )

    def failed(self) -> _Bucket:
        return _Bucket(
            documents=self.documents,
            records=self.records,
            chars=self.chars,
            tokens=self.tokens,
            max_record_tokens=self.max_record_tokens,
            records_over_limit=self.records_over_limit,
            failed_documents=self.failed_documents + 1,
        )

    def with_documents(self, documents: int) -> _Bucket:
        return _Bucket(
            documents=documents,
            records=self.records,
            chars=self.chars,
            tokens=self.tokens,
            max_record_tokens=self.max_record_tokens,
            records_over_limit=self.records_over_limit,
            failed_documents=self.failed_documents,
        )


def _ratio(chars: int, tokens: int) -> float:
    return round(chars / tokens, 3) if tokens else 0.0


def _bucket_dict(bucket: _Bucket) -> dict[str, Any]:
    return {
        "documents": bucket.documents,
        "records": bucket.records,
        "chars": bucket.chars,
        "tokens": bucket.tokens,
        "chars_per_token": _ratio(bucket.chars, bucket.tokens),
        "max_record_tokens": bucket.max_record_tokens,
        "records_over_limit": bucket.records_over_limit,
        "failed_documents": bucket.failed_documents,
    }


def _tokenizer_dict(profile: EmbeddingModelProfile, service: TokenizerService) -> dict[str, Any]:
    effective, degraded = service.effective_spec(profile.tokenizer)
    return {
        "kind": effective.kind.value,
        "identifier": effective.identifier,
        "revision": effective.revision,
        "artifact_sha256": effective.artifact_sha256,
        "exact": effective.exact,
        "source": effective.source.value,
        "identity": effective.identity,
        "max_input_tokens": effective.max_input_tokens,
        "max_input_assumed": profile.max_input_assumed,
        "degraded_reason": degraded,
    }


@lru_cache(maxsize=1)
def load_reference_corpus() -> tuple[dict[str, Any], ...]:
    """The bundled synthetic multilingual samples (text stays test/runtime data)."""
    payload = json.loads(REFERENCE_CORPUS_PATH.read_text(encoding="utf-8"))
    samples = payload.get("samples") or []
    return tuple(
        {
            "language": str(row["language"]),
            "label": str(row.get("label") or row["language"]),
            "text": str(row["text"]),
        }
        for row in samples
    )


def measure_records(
    records: Sequence[ComposedRecord],
    *,
    spec: TokenizerSpec,
    service: TokenizerService,
) -> dict[str, Any]:
    """Per-view and total token aggregates for already-composed records."""
    limit = int(spec.max_input_tokens)
    views: dict[str, _Bucket] = {}
    total = _Bucket()
    exact = spec.exact
    degraded: str | None = None
    for record in records:
        counted = service.count_or_fallback(spec, record.text)
        exact = exact and counted.exact
        degraded = degraded or counted.degraded_reason
        bucket = views.setdefault(record.view, _Bucket())
        views[record.view] = bucket.add_record(len(record.text), counted.tokens, limit)
        total = total.add_record(len(record.text), counted.tokens, limit)
    return {
        "views": [{"view": view, **_bucket_dict(bucket)} for view, bucket in sorted(views.items())],
        "totals": {
            **_bucket_dict(total),
            "exact": exact,
            "degraded_reason": degraded,
            "chars_per_token": _ratio(total.chars, total.tokens),
        },
    }


def measure_reference(*, spec: TokenizerSpec, service: TokenizerService) -> dict[str, Any]:
    """Count the bundled multilingual samples; aggregates only, never their text."""
    rows: list[dict[str, Any]] = []
    total_chars = 0
    total_tokens = 0
    exact = spec.exact
    degraded: str | None = None
    for sample in load_reference_corpus():
        counted = service.count_or_fallback(spec, sample["text"])
        exact = exact and counted.exact
        degraded = degraded or counted.degraded_reason
        chars = len(sample["text"])
        total_chars += chars
        total_tokens += counted.tokens
        rows.append(
            {
                "language": sample["language"],
                "label": sample["label"],
                "chars": chars,
                "tokens": counted.tokens,
                "chars_per_token": _ratio(chars, counted.tokens),
            }
        )
    return {
        "state": "ok" if rows else "empty",
        "samples": rows,
        "total_chars": total_chars,
        "total_tokens": total_tokens,
        "chars_per_token": _ratio(total_chars, total_tokens),
        "exact": exact,
        "degraded_reason": degraded,
    }


async def measure_corpus(
    db: AsyncSession,
    *,
    spec: TokenizerSpec,
    service: TokenizerService,
    kinds: Sequence[str] = REPORT_KINDS,
    limit_per_kind: int = DEFAULT_CORPUS_LIMIT,
) -> dict[str, Any]:
    """Bounded shadow scan over real composed records (aggregates only).

    Logs one aggregate line per call — counts, ratios and the exact flag,
    never a document id or any text. The caller's session is only read.
    """
    limit = max(1, min(int(limit_per_kind), MAX_CORPUS_LIMIT))
    total = _Bucket()
    per_kind: list[dict[str, Any]] = []
    for kind in kinds:
        bucket = _Bucket()
        rows = await list_sources(db, kind, limit=limit)
        documents = 0
        for row in rows:
            try:
                loaded = await load_source(db, kind, row.source_id)
            except Exception:
                logger.warning("tokenizer shadow: %s source load failed", kind, exc_info=True)
                bucket = bucket.failed()
                continue
            if loaded is None:
                continue
            documents += 1
            for record in loaded.composed.records:
                counted = service.count_or_fallback(spec, record.text)
                bucket = bucket.add_record(len(record.text), counted.tokens, spec.max_input_tokens)
        bucket = bucket.with_documents(documents)
        per_kind.append({"kind": kind, **_bucket_dict(bucket)})
        total = total.plus(bucket)
    state = "ok" if total.records else "empty"
    payload = {
        "state": state,
        "limit_per_kind": limit,
        "kinds": per_kind,
        **_bucket_dict(total),
        "chars_per_token": _ratio(total.chars, total.tokens),
        "exact": spec.exact,
    }
    logger.info(
        "tokenizer shadow: state=%s documents=%d records=%d chars=%d tokens=%d "
        "chars_per_token=%.2f max_record_tokens=%d over_limit=%d exact=%s",
        state,
        total.documents,
        total.records,
        total.chars,
        total.tokens,
        payload["chars_per_token"],
        total.max_record_tokens,
        total.records_over_limit,
        spec.exact,
    )
    return payload


async def build_report(
    db: AsyncSession,
    *,
    service: TokenizerService | None = None,
    kinds: Sequence[str] = REPORT_KINDS,
    limit_per_kind: int = DEFAULT_CORPUS_LIMIT,
) -> dict[str, Any]:
    """The Tools -> Retrieval tokenizer/limits report (aggregates only)."""
    tokenizer_service = service or get_tokenizer_service()
    resolved = await resolution.resolve_task_model(
        db, AITaskType.EMBED.value, None, allow_dev_bootstrap=False
    )
    provider_type = resolved.provider_type if resolved is not None else None
    model_name = resolved.model_name if resolved is not None else None
    profile = await embedding_profiles.resolve_for(db, provider_type, model_name)
    effective, _degraded = tokenizer_service.effective_spec(profile.tokenizer)

    reference = measure_reference(spec=effective, service=tokenizer_service)
    corpus = await measure_corpus(
        db,
        spec=effective,
        service=tokenizer_service,
        kinds=kinds,
        limit_per_kind=limit_per_kind,
    )
    payload = {
        "state": "ok" if resolved is not None else "unconfigured",
        "model": {
            "provider": provider_type or "unconfigured",
            "model": model_name or "unconfigured",
            "max_input_assumed": profile.max_input_assumed,
        },
        "tokenizer": _tokenizer_dict(profile, tokenizer_service),
        "profile": embedding_profiles.profile_dto(profile, service=tokenizer_service),
        "chunking": {
            "view": "body",
            "max_chunk_chars": BODY_CHUNK_CHARS,
            "overlap_chars": BODY_CHUNK_OVERLAP_CHARS,
            "chunker_version": CHUNKER_VERSION,
            "composer_version": COMPOSER_VERSION,
            "token_aware": False,
        },
        "reference": reference,
        "corpus": corpus,
        "shadow": {"writes": False},
    }
    return ops.assert_no_raw_text(payload)


__all__ = [
    "DEFAULT_CORPUS_LIMIT",
    "MAX_CORPUS_LIMIT",
    "REFERENCE_CORPUS_PATH",
    "REPORT_KINDS",
    "build_report",
    "load_reference_corpus",
    "measure_corpus",
    "measure_records",
    "measure_reference",
]
