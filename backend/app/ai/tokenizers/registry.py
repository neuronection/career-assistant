"""Embedding model profile registry and precedence (plan 52 T2a).

A profile is the tokenizer identity, model input limit, per-request batch
budget and default :class:`~app.storage.tokenizer_contract.ChunkConfig` for
one embedding model. Resolution order:

1. **admin** — an explicit ``embedding_model_profiles`` row (persisted, see
   :mod:`app.services.embedding_profiles`);
2. **curated** — the code catalog below, currently the three usable OpenAI
   embedding models and their bundled ``cl100k_base`` tokenizer;
3. **fallback** — the conservative UTF-8/codepoint heuristic, visibly
   ``exact=False``.

The key is always ``(provider_class, model)``. A model name alone never
selects an exact tokenizer: an Ollama/HF/unknown model, or a known OpenAI
model served by another provider class, resolves to the labelled fallback.
Plan 52 T2b adds provider fetch/HF assets; the fallback stays the floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.ai.tokenizers.service import (
    FALLBACK_MAX_INPUT_TOKENS,
    OPENAI_EMBEDDING_MAX_INPUT_TOKENS,
    fallback_spec,
    provider_class,
    tiktoken_spec,
)
from app.storage.tokenizer_contract import (
    ChunkConfig,
    TokenizerSource,
    TokenizerSpec,
)

# Reference defaults for a curated embedding profile. The chunk budget is a
# preview until plan 52 T3 makes the write path token-aware; it comfortably
# fits the OpenAI input limit after prefixes and a safety margin.
CURATED_BATCH_MAX_ITEMS = 2048
CURATED_BATCH_MAX_TOKENS = 300_000
CURATED_CHUNK = ChunkConfig(max_chunk_tokens=512, overlap_tokens=64, max_chars=1600)

# The fallback is deliberately smaller: an unknown model has no confirmed
# input limit, so the conservative profile never exceeds the assumed 2048.
FALLBACK_BATCH_MAX_ITEMS = 64
FALLBACK_BATCH_MAX_TOKENS = 8192
FALLBACK_CHUNK = ChunkConfig(max_chunk_tokens=256, overlap_tokens=32, max_chars=800)

# Currently usable OpenAI embedding models. o200k_base is a chat encoding and
# stays out; no Ollama or Hugging Face entry is invented here.
CURATED_OPENAI_MODELS = (
    "text-embedding-3-small",
    "text-embedding-3-large",
    "text-embedding-ada-002",
)


@dataclass(frozen=True)
class EmbeddingModelProfile:
    """One resolved tokenizer/limits profile for an embedding model."""

    provider_class: str
    model: str
    tokenizer: TokenizerSpec
    chunk: ChunkConfig
    batch_max_items: int
    batch_max_tokens: int
    max_input_assumed: bool = False
    override: bool = False
    updated_by: str | None = None
    updated_at: datetime | None = None

    @property
    def source(self) -> TokenizerSource:
        """Where the selection came from (the tokenizer spec owns it)."""
        return self.tokenizer.source

    @property
    def exact(self) -> bool:
        """Whether the selected tokenizer is exact (heuristic is never exact)."""
        return self.tokenizer.exact


def _curated_profile(model: str) -> EmbeddingModelProfile:
    return EmbeddingModelProfile(
        provider_class="openai",
        model=model,
        tokenizer=tiktoken_spec(
            max_input_tokens=OPENAI_EMBEDDING_MAX_INPUT_TOKENS,
            source=TokenizerSource.CURATED,
        ),
        chunk=CURATED_CHUNK,
        batch_max_items=CURATED_BATCH_MAX_ITEMS,
        batch_max_tokens=CURATED_BATCH_MAX_TOKENS,
        max_input_assumed=False,
    )


CURATED_EMBEDDING_PROFILES: tuple[EmbeddingModelProfile, ...] = tuple(
    _curated_profile(model) for model in CURATED_OPENAI_MODELS
)

_CURATED_BY_KEY = {
    (profile.provider_class, profile.model): profile for profile in CURATED_EMBEDDING_PROFILES
}


def fallback_profile(klass: str, model: str) -> EmbeddingModelProfile:
    """The labelled conservative profile for an uncurated provider/model."""
    return EmbeddingModelProfile(
        provider_class=klass,
        model=model,
        tokenizer=fallback_spec(FALLBACK_MAX_INPUT_TOKENS),
        chunk=FALLBACK_CHUNK,
        batch_max_items=FALLBACK_BATCH_MAX_ITEMS,
        batch_max_tokens=FALLBACK_BATCH_MAX_TOKENS,
        max_input_assumed=True,
    )


def curated_profile(provider_type: str | None, model: str | None) -> EmbeddingModelProfile | None:
    """The curated selection for a provider/model pair, if one exists."""
    return _CURATED_BY_KEY.get((provider_class(provider_type), str(model or "").strip()))


def resolve_embedding_profile(
    provider_type: str | None,
    model: str | None,
    *,
    override: EmbeddingModelProfile | None = None,
) -> EmbeddingModelProfile:
    """Resolve one embedding model's profile by precedence.

    ``override`` is the persisted admin row for this exact
    ``(provider_class, model)`` pair; it is ignored when it names another
    pair. Nothing here looks at substrings of ``model`` — a known model
    served by an uncurated provider class still resolves to the fallback.
    """
    klass = provider_class(provider_type)
    model_name = str(model or "").strip()
    if override is not None and (override.provider_class, override.model) == (klass, model_name):
        return override
    curated = _CURATED_BY_KEY.get((klass, model_name))
    if curated is not None:
        return curated
    return fallback_profile(klass, model_name)


def resolve_tokenizer_spec(provider_type: str | None, model: str | None) -> TokenizerSpec:
    """Convenience wrapper around :func:`resolve_embedding_profile`."""
    return resolve_embedding_profile(provider_type, model).tokenizer


__all__ = [
    "CURATED_BATCH_MAX_ITEMS",
    "CURATED_BATCH_MAX_TOKENS",
    "CURATED_CHUNK",
    "CURATED_EMBEDDING_PROFILES",
    "CURATED_OPENAI_MODELS",
    "FALLBACK_BATCH_MAX_ITEMS",
    "FALLBACK_BATCH_MAX_TOKENS",
    "FALLBACK_CHUNK",
    "EmbeddingModelProfile",
    "curated_profile",
    "fallback_profile",
    "resolve_embedding_profile",
    "resolve_tokenizer_spec",
]
