"""Embedding model profile registry and precedence (plan 52 T2a/T2b).

A profile is the tokenizer identity, model input limit, per-request batch
budget and default :class:`~app.storage.tokenizer_contract.ChunkConfig` for
one embedding model. Resolution order:

1. **admin** — an explicit ``embedding_model_profiles`` row (persisted, see
   :mod:`app.services.embedding_profiles`);
2. **curated** — the code catalog below: the usable OpenAI embedding models
   (bundled ``cl100k_base``) and verified open-source Hugging Face mappings;
3. **fallback** — the conservative UTF-8/codepoint heuristic, visibly
   ``exact=False``.

The key is always ``(provider_class, model)``. A model name alone never
selects an exact tokenizer: an unknown model, or a known model served by an
uncurated provider class, resolves to the labelled fallback. Curated
open-source rows carry provenance (repository, pinned revision, artifact
SHA-256, license and source URL); a family whose tokenizer/repository cannot
be fetched honestly today is listed as an unavailable preset, never claimed
as supported.

The open-source hashes below were verified against the Hugging Face model API
and the exact ``tokenizer.json`` bytes at the pinned revision. The fetch job
re-verifies the SHA-256 on download; nothing is inferred from a model name.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.ai.tokenizers.service import (
    FALLBACK_MAX_INPUT_TOKENS,
    OPENAI_EMBEDDING_MAX_INPUT_TOKENS,
    fallback_spec,
    hf_tokenizer_spec,
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

# Open-source embeddings are normally served one text per request through an
# OpenAI-compatible endpoint; keep the batch envelope conservative.
CURATED_HF_BATCH_MAX_ITEMS = 256
CURATED_HF_BATCH_MAX_TOKENS = 250_000
CURATED_HF_CHUNK = ChunkConfig(max_chunk_tokens=512, overlap_tokens=64, max_chars=1600)

# The fallback is deliberately smaller: an unknown model has no confirmed
# input limit, so the conservative profile never exceeds the assumed 2048.
FALLBACK_BATCH_MAX_ITEMS = 64
FALLBACK_BATCH_MAX_TOKENS = 8192
FALLBACK_CHUNK = ChunkConfig(max_chunk_tokens=256, overlap_tokens=32, max_chars=800)

# Currently usable OpenAI embedding models. o200k_base is a chat encoding and
# stays out; the verified open-source rows below are separate presets.
CURATED_OPENAI_MODELS = (
    "text-embedding-3-small",
    "text-embedding-3-large",
    "text-embedding-ada-002",
)


@dataclass(frozen=True)
class CuratedPreset:
    """One open-source embedding family's verified tokenizer provenance."""

    family: str
    repository: str
    revision: str
    artifact_sha256: str
    license: str
    source_url: str
    max_input_tokens: int
    models: tuple[str, ...]
    usable: bool = True
    unusable_reason: str | None = None


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
    family: str | None = None
    license: str | None = None
    source_url: str | None = None
    repository: str | None = None
    preset_revision: str | None = None
    usable: bool = True
    usable_reason: str | None = None

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
        family="openai",
        license="openai-terms",
        source_url="https://platform.openai.com/docs/guides/embeddings",
    )


# Verified open-source tokenizer mappings. A preset may cover several exact
# model ids (HF repository id, Ollama library/tag name); the mapping is still
# keyed by provider class + model, never by a substring. Aliases were checked
# against the Ollama model pages and the HF repository's tokenizer.json at the
# stated revision; a family we could not verify stays out (or is listed as an
# unavailable preset below).
CURATED_HF_PRESETS: tuple[CuratedPreset, ...] = (
    CuratedPreset(
        family="nomic",
        repository="nomic-ai/nomic-embed-text-v1.5",
        revision="e9b6763023c676ca8431644204f50c2b100d9aab",
        artifact_sha256="d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
        license="apache-2.0",
        source_url="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5",
        max_input_tokens=8192,
        models=(
            "nomic-embed-text",
            "nomic-embed-text:latest",
            "nomic-embed-text-v1.5",
            "nomic-ai/nomic-embed-text-v1.5",
        ),
    ),
    CuratedPreset(
        family="mixedbread",
        repository="mixedbread-ai/mxbai-embed-large-v1",
        revision="b33106f585b9ce46904ad7443a3b52b7a63e231c",
        artifact_sha256="d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
        license="apache-2.0",
        source_url="https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1",
        max_input_tokens=512,
        models=(
            "mxbai-embed-large",
            "mxbai-embed-large:latest",
            "mixedbread-ai/mxbai-embed-large-v1",
        ),
    ),
    CuratedPreset(
        family="bge",
        repository="BAAI/bge-m3",
        revision="5617a9f61b028005a4858fdac845db406aefb181",
        artifact_sha256="21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08",
        license="mit",
        source_url="https://huggingface.co/BAAI/bge-m3",
        max_input_tokens=8192,
        models=("bge-m3", "bge-m3:latest", "BAAI/bge-m3"),
    ),
    CuratedPreset(
        family="bge",
        repository="BAAI/bge-large-en-v1.5",
        revision="d4aa6901d3a41ba39fb536a557fa166f842b0e09",
        artifact_sha256="d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
        license="mit",
        source_url="https://huggingface.co/BAAI/bge-large-en-v1.5",
        max_input_tokens=512,
        models=(
            "bge-large",
            "bge-large-en-v1.5",
            "BAAI/bge-large-en-v1.5",
        ),
    ),
    CuratedPreset(
        family="qwen",
        repository="Qwen/Qwen3-Embedding-0.6B",
        revision="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
        artifact_sha256="def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a",
        license="apache-2.0",
        source_url="https://huggingface.co/Qwen/Qwen3-Embedding-0.6B",
        max_input_tokens=32768,
        models=(
            "qwen3-embedding:0.6b",
            "Qwen/Qwen3-Embedding-0.6B",
        ),
    ),
    CuratedPreset(
        family="qwen",
        repository="Qwen/Qwen3-Embedding-8B",
        revision="1d8ad4ca9b3dd8059ad90a75d4983776a23d44af",
        artifact_sha256="83cdf8c3a34f68862319cb1810ee7b1e2c0a44e0864ae930194ddb76bb7feb8d",
        license="apache-2.0",
        source_url="https://huggingface.co/Qwen/Qwen3-Embedding-8B",
        max_input_tokens=32768,
        models=(
            "qwen3-embedding:8b",
            "Qwen/Qwen3-Embedding-8B",
        ),
    ),
    CuratedPreset(
        family="e5",
        repository="intfloat/multilingual-e5-large",
        revision="3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3",
        artifact_sha256="62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626",
        license="mit",
        source_url="https://huggingface.co/intfloat/multilingual-e5-large",
        max_input_tokens=512,
        models=(
            "multilingual-e5-large",
            "intfloat/multilingual-e5-large",
        ),
    ),
)

# Known families whose tokenizer we could not verify/fetch honestly. They are
# listed so the admin sees the family, license and repository, but they never
# resolve to an exact tokenizer and are never presented as supported.
UNAVAILABLE_HF_PRESETS: tuple[CuratedPreset, ...] = (
    CuratedPreset(
        family="embeddinggemma",
        repository="google/embeddinggemma-300m",
        revision="57c266a740f537b4dc058e1b0cda161fd15afa75",
        artifact_sha256="",
        license="gemma",
        source_url="https://huggingface.co/google/embeddinggemma-300m",
        max_input_tokens=2048,
        models=(
            "embeddinggemma",
            "embeddinggemma:latest",
            "embeddinggemma-2:440m",
        ),
        usable=False,
        unusable_reason="gated_repository",
    ),
)


def _hf_profile(model: str, preset: CuratedPreset) -> EmbeddingModelProfile:
    return EmbeddingModelProfile(
        provider_class="openai",
        model=model,
        tokenizer=hf_tokenizer_spec(
            identifier=preset.repository,
            revision=preset.revision,
            artifact_sha256=preset.artifact_sha256,
            max_input_tokens=preset.max_input_tokens,
            source=TokenizerSource.CURATED,
        ),
        chunk=CURATED_HF_CHUNK,
        batch_max_items=CURATED_HF_BATCH_MAX_ITEMS,
        batch_max_tokens=CURATED_HF_BATCH_MAX_TOKENS,
        max_input_assumed=False,
        family=preset.family,
        license=preset.license,
        source_url=preset.source_url,
        repository=preset.repository,
        preset_revision=preset.revision,
        usable=preset.usable,
        usable_reason=preset.unusable_reason,
    )


CURATED_EMBEDDING_PROFILES: tuple[EmbeddingModelProfile, ...] = tuple(
    [_curated_profile(model) for model in CURATED_OPENAI_MODELS]
    + [_hf_profile(model, preset) for preset in CURATED_HF_PRESETS for model in preset.models]
)

_CURATED_BY_KEY = {
    (profile.provider_class, profile.model): profile for profile in CURATED_EMBEDDING_PROFILES
}

_UNAVAILABLE_BY_KEY = {
    ("openai", model): preset for preset in UNAVAILABLE_HF_PRESETS for model in preset.models
}


def fallback_profile(
    klass: str, model: str, *, preset: CuratedPreset | None = None
) -> EmbeddingModelProfile:
    """The labelled conservative profile for an uncurated provider/model.

    When ``preset`` is an unavailable family, its provenance still travels so
    the UI can explain *why* the model stays fallback instead of silently
    treating it as unknown.
    """
    return EmbeddingModelProfile(
        provider_class=klass,
        model=model,
        tokenizer=fallback_spec(FALLBACK_MAX_INPUT_TOKENS),
        chunk=FALLBACK_CHUNK,
        batch_max_items=FALLBACK_BATCH_MAX_ITEMS,
        batch_max_tokens=FALLBACK_BATCH_MAX_TOKENS,
        max_input_assumed=True,
        family=preset.family if preset is not None else None,
        license=preset.license if preset is not None else None,
        source_url=preset.source_url if preset is not None else None,
        repository=preset.repository if preset is not None else None,
        preset_revision=preset.revision if preset is not None else None,
        usable=preset.usable if preset is not None else True,
        usable_reason=preset.unusable_reason if preset is not None else None,
    )


def curated_profile(provider_type: str | None, model: str | None) -> EmbeddingModelProfile | None:
    """The curated selection for a provider/model pair, if one exists."""
    return _CURATED_BY_KEY.get((provider_class(provider_type), str(model or "").strip()))


def unavailable_preset(provider_type: str | None, model: str | None) -> CuratedPreset | None:
    """The known-but-unavailable family for a pair, if one exists."""
    return _UNAVAILABLE_BY_KEY.get((provider_class(provider_type), str(model or "").strip()))


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
    return fallback_profile(klass, model_name, preset=_UNAVAILABLE_BY_KEY.get((klass, model_name)))


def resolve_tokenizer_spec(provider_type: str | None, model: str | None) -> TokenizerSpec:
    """Convenience wrapper around :func:`resolve_embedding_profile`."""
    return resolve_embedding_profile(provider_type, model).tokenizer


__all__ = [
    "CURATED_BATCH_MAX_ITEMS",
    "CURATED_BATCH_MAX_TOKENS",
    "CURATED_CHUNK",
    "CURATED_EMBEDDING_PROFILES",
    "CURATED_HF_BATCH_MAX_ITEMS",
    "CURATED_HF_BATCH_MAX_TOKENS",
    "CURATED_HF_CHUNK",
    "CURATED_HF_PRESETS",
    "CURATED_OPENAI_MODELS",
    "FALLBACK_BATCH_MAX_ITEMS",
    "FALLBACK_BATCH_MAX_TOKENS",
    "FALLBACK_CHUNK",
    "UNAVAILABLE_HF_PRESETS",
    "CuratedPreset",
    "EmbeddingModelProfile",
    "curated_profile",
    "fallback_profile",
    "resolve_embedding_profile",
    "resolve_tokenizer_spec",
    "unavailable_preset",
]
